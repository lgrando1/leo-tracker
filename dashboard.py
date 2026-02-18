import streamlit as st
import pandas as pd
from sqlalchemy import create_engine, text
from datetime import datetime, timedelta
import pytz
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# ============================================================================
# 1. CONFIGURAÇÃO VISUAL
# ============================================================================
st.set_page_config(page_title="Leo's Nutrition Control", page_icon="🦁", layout="wide", initial_sidebar_state="collapsed")

st.markdown("""
    <style>
    #MainMenu {visibility: hidden;} footer {visibility: hidden;} header {visibility: hidden;}
    div[data-testid="stMetric"] { background-color: #f0f2f6; padding: 15px; border-radius: 12px; border: 1px solid #e0e0e0; box-shadow: 2px 2px 5px rgba(0,0,0,0.05); }
    @media (prefers-color-scheme: dark) { div[data-testid="stMetric"] { background-color: #262730; border: 1px solid #464b5c; } }
    h1, h2, h3 { font-family: 'Helvetica', sans-serif; font-weight: 700; }
    /* Estilo para aba de engenharia */
    .control-text { font-family: 'Consolas', monospace; color: #4CAF50; }
    </style>
    """, unsafe_allow_html=True)

# ============================================================================
# 2. CONEXÃO BLINDADA (MANTIDA IGUAL)
# ============================================================================
@st.cache_resource(ttl=600)
def get_engine():
    db_url = st.secrets["DATABASE_URL"]
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)
    return create_engine(db_url, pool_pre_ping=True)

def run_query(query, params=None, is_select=True):
    engine = get_engine()
    try:
        if is_select:
            with engine.connect() as conn:
                df = pd.read_sql(text(query), conn, params=params)
                for col in ['data', 'log_date', 'measurement_time']:
                    if col in df.columns:
                        try: df[col] = pd.to_datetime(df[col])
                        except: pass
                return df
    except Exception:
        return pd.DataFrame()

# --- TRAVA DE SEGURANÇA (TOKEN) ---
if st.query_params.get("token") != st.secrets.get("DASH_ACCESS_TOKEN"):
    st.error("🔒 Acesso Restrito. Token inválido."); st.stop()

# ============================================================================
# 3. ETL (EXTRAÇÃO E TRATAMENTO - MANTIDO IGUAL)
# ============================================================================
hoje = datetime.now(pytz.timezone('America/Sao_Paulo')).date()
DATA_INICIO = pd.to_datetime("2025-12-30").date()

# Fetch Data
df_perfil = run_query("SELECT * FROM public.perfil WHERE id = 1")
df_peso = run_query("SELECT * FROM public.peso ORDER BY data ASC")
df_medidas = run_query("SELECT * FROM public.body_measurements ORDER BY log_date ASC")
df_bp = run_query("SELECT * FROM public.blood_pressure ORDER BY measurement_time ASC")
df_hist = run_query("""
    SELECT data, SUM(kcal) as tkcal, SUM(proteina) as tprot, SUM(carbo) as tcarb, 
           SUM(gordura) as tgord, SUM(quantidade) as tqtd
    FROM public.consumo WHERE data >= :d GROUP BY data ORDER BY data ASC
""", {"d": DATA_INICIO})
df_treino = run_query("""
    SELECT data, SUM(duracao_min) as t_min, SUM(passos) as t_passos, SUM(calorias) as t_cal_out 
    FROM public.exercicios WHERE data >= :d GROUP BY data ORDER BY data ASC
""", {"d": DATA_INICIO})

# Fetch Hoje
df_hoje_comida = run_query("SELECT * FROM public.consumo WHERE data = :d", {"d": hoje})
df_hoje_treino = run_query("SELECT * FROM public.exercicios WHERE data = :d", {"d": hoje})

# --- SETUP PERFIL ---
if not df_perfil.empty:
    p = df_perfil.iloc[0]
else:
    p = {'meta_kcal': 1650, 'meta_proteina': 130, 'meta_carbo': 150, 'meta_gordura': 59, 
         'meta_peso_alvo': 120.0, 'ritmo_semanal': 0.8, 'idade': 41, 'altura_cm': 178, 'fator_atividade': 1.2}

fator_atividade = float(p.get('fator_atividade') or 1.2)
peso_atual = float(df_peso.iloc[-1]['peso_kg']) if not df_peso.empty else 140.0

# --- MERGE INTELIGENTE ---
df_merged = pd.DataFrame()
if not df_hist.empty and not df_peso.empty:
    df_hist['data_dt'] = pd.to_datetime(df_hist['data']).dt.date
    df_peso['data_dt'] = pd.to_datetime(df_peso['data']).dt.date
    
    # Base: Consumo + Peso
    df_merged = pd.merge(df_hist, df_peso[['data_dt', 'peso_kg']], on='data_dt', how='left').ffill()
    if df_merged['peso_kg'].isnull().any():
         df_merged['peso_kg'] = df_merged['peso_kg'].fillna(method='bfill').fillna(peso_atual)

    # Add Treino
    if not df_treino.empty:
        df_treino['data_dt'] = pd.to_datetime(df_treino['data']).dt.date
        df_merged = pd.merge(df_merged, df_treino[['data_dt', 't_min', 't_passos', 't_cal_out']], on='data_dt', how='left')
        df_merged[['t_min', 't_passos', 't_cal_out']] = df_merged[['t_min', 't_passos', 't_cal_out']].fillna(0)
    else:
        df_merged['t_min'] = 0; df_merged['t_passos'] = 0; df_merged['t_cal_out'] = 0
    
    # Cálculos Avançados
    idade, altura = int(p.get('idade', 41)), int(p.get('altura_cm', 178))
    # GET (Mifflin-St Jeor)
    df_merged['get_basal'] = ((10 * df_merged['peso_kg']) + (6.25 * altura) - (5 * idade) + 5) * fator_atividade
    df_merged['get_total'] = df_merged['get_basal'] + df_merged['t_cal_out']
    df_merged['deficit_real'] = df_merged['get_total'] - df_merged['tkcal']

# ============================================================================
# 4. ORGANIZAÇÃO EM ABAS (NOVO)
# ============================================================================

# Aqui criamos a separação entre a visão de Engenharia e o seu Dashboard Original
tab_control, tab_dash = st.tabs(["🎛️ Sala de Controle (Engenharia)", "🦁 Dashboard Original"])

# ============================================================================
# ABA 1: VISÃO DE ENGENHARIA DE CONTROLE (NOVA LÓGICA COM VARIÁVEIS ANTIGAS)
# ============================================================================
with tab_control:
    st.markdown("### 🏭 Monitoramento de Processo (Malha Fechada)")
    
    # --- CÁLCULOS DE CONTROLE (SP, PV, ERRO) ---
    # Usando as variáveis que já existiam
    if not df_peso.empty:
        # Definir Setpoint (SP) Dinâmico baseado na meta semanal
        BASE_DATE = pd.to_datetime("2025-12-31").date()
        df_base = df_peso[df_peso['data_dt'] >= BASE_DATE].sort_values('data_dt')
        
        if not df_base.empty:
            peso_start = float(df_base.iloc[0]['peso_kg'])
            dias_passados = (hoje - BASE_DATE).days
            ritmo_diario = float(p['ritmo_semanal']) / 7
            
            # SP: Onde eu deveria estar hoje
            sp_hoje = peso_start - (dias_passados * ritmo_diario)
            
            # PV: Onde eu estou (Peso Atual já calculado no ETL)
            pv_hoje = peso_atual
            
            # Erro = SP - PV
            # Se SP=90 e PV=92, Erro = -2 (Estou pesado). Se SP=90 e PV=88, Erro=+2 (Estou leve).
            erro_t = sp_hoje - pv_hoje
            
            # MV (Variável Manipulada Sugerida - Controle Proporcional)
            kp = 300.0 # Ganho: Cortar 300kcal para cada 1kg de erro
            acao_p = kp * erro_t
            mv_sugerida = float(p['meta_kcal']) + acao_p
            # Saturação de segurança
            mv_sugerida = max(1200, min(3000, mv_sugerida))

            # --- DISPLAY VISUAL DE CONTROLE ---
            kc1, kc2, kc3, kc4 = st.columns(4)
            
            with kc1:
                st.metric("🎯 Setpoint (SP)", f"{sp_hoje:.2f} kg", help="Meta calculada linearmente")
            with kc2:
                st.metric("⚖️ Process Variable (PV)", f"{pv_hoje:.2f} kg", help="Leitura do sensor (Balança)")
            with kc3:
                # Cor invertida: Erro negativo é ruim (estou acima do peso)
                lbl_erro = "✅ No Alvo" if abs(erro_t) < 0.5 else ("⚠️ Desvio" if erro_t < 0 else "Adiantado")
                st.metric("📉 Erro (SP - PV)", f"{erro_t:.2f} kg", delta=lbl_erro, delta_color="normal" if erro_t >=0 else "inverse")
            with kc4:
                st.metric("🔥 MV (Ação P)", f"{int(mv_sugerida)} kcal", delta=f"{int(acao_p)} kcal", help="Sugestão de ingestão baseada no erro")

            st.markdown("---")
            
            # GRÁFICO DE CONTROLE (SP vs PV)
            datas_ctrl = pd.date_range(start=BASE_DATE, end=hoje)
            sp_line = [peso_start - ((ritmo_diario) * (d.date() - BASE_DATE).days) for d in datas_ctrl]
            
            # Filtrar dados reais para plotar junto
            df_plot_ctrl = df_peso[df_peso['data_dt'] >= BASE_DATE].copy()
            
            fig_ctrl = go.Figure()
            # Linha SP
            fig_ctrl.add_trace(go.Scatter(x=datas_ctrl, y=sp_line, name='Setpoint (Meta)', mode='lines', line=dict(color='green', dash='dash')))
            # Linha PV
            fig_ctrl.add_trace(go.Scatter(x=df_plot_ctrl['data_dt'], y=df_plot_ctrl['peso_kg'], name='PV (Real)', mode='lines+markers', line=dict(color='red', width=3)))
            
            fig_ctrl.update_layout(title="Resposta do Sistema (Rastreamento de Meta)", height=400, template="plotly_white")
            st.plotly_chart(fig_ctrl, use_container_width=True)
            
            st.caption(f"Controlador: Humano | Planta: Metabolismo | Ganho Kp: {kp}")

# ============================================================================
# ABA 2: DASHBOARD ORIGINAL (SEU CÓDIGO ORIGINAL, APENAS INDENTADO)
# ============================================================================
with tab_dash:
    st.markdown(f"### 🦁 Leo's Performance Dashboard | {hoje.strftime('%d/%m/%Y')}")

    # --- KPI ROW 1: DO DIA ---
    k_act = df_hoje_comida['kcal'].sum() if not df_hoje_comida.empty else 0
    p_act = df_hoje_comida['proteina'].sum() if not df_hoje_comida.empty else 0
    meta_agua = round((peso_atual * 35) / 1000, 1)

    # Dados Treino Hoje
    treino_min = int(df_hoje_treino['duracao_min'].sum()) if not df_hoje_treino.empty else 0
    treino_passos = int(df_hoje_treino['passos'].sum()) if not df_hoje_treino.empty else 0

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("⚖️ Peso Atual", f"{peso_atual} kg", f"Meta: {p['meta_peso_alvo']}", help="Última pesagem registrada no banco de dados.")
    c2.metric("🔥 Calorias (Hoje)", f"{int(k_act)}", f"Meta: {p['meta_kcal']}", help="Soma dos alimentos registrados hoje via IA.")
    c3.metric("🥩 Proteína (Hoje)", f"{int(p_act)}g", f"Meta: {p['meta_proteina']}", help="Total de proteínas (animal + vegetal).")
    c4.metric("💧 Água", f"{meta_agua}L", "Minímo", help="Cálculo: 35ml x Peso Atual.")
    c5.metric("🏃‍♂️ Treino (Hoje)", f"{treino_min} min", f"{treino_passos} passos", help="Dados importados do Iron N1 (Caminhada/Musculação).")

    last_bp_txt = "--"
    if not df_bp.empty:
        last = df_bp.iloc[-1]
        last_bp_txt = f"{last['systolic']}x{last['diastolic']}"
    c6.metric("❤️ Pressão", last_bp_txt, f"Pulso: {last.get('pulse', '--')}")

    st.divider()

    # --- ROW 2: ENERGIA & DENSIDADE ---
    c_main1, c_main2 = st.columns([2, 1])

    with c_main1:
        st.markdown("##### 🧪 Densidade Energética: Volume vs. Calorias", help="Compara o peso da comida (g) com a energia (kcal). Barras altas com linha baixa indicam alta saciedade.")
        if not df_merged.empty:
            fig_vol = make_subplots(specs=[[{"secondary_y": True}]])
            fig_vol.add_trace(go.Bar(x=df_merged['data'], y=df_merged['tqtd'], name="Volume (g)", marker_color='#AED6F1', opacity=0.5), secondary_y=True)
            fig_vol.add_trace(go.Scatter(x=df_merged['data'], y=df_merged['tkcal'], name="Calorias In", mode='lines+markers', line=dict(color='#C0392B', width=3)), secondary_y=False)
            fig_vol.add_trace(go.Scatter(x=df_merged['data'], y=df_merged['get_total'], name="Gasto Total (Out)", mode='lines', line=dict(color='#27AE60', width=2, dash='dot')), secondary_y=False)
            
            fig_vol.update_layout(height=350, margin=dict(l=10,r=10,t=30,b=10), legend=dict(orientation="h", y=1.1), template="plotly_white")
            fig_vol.update_yaxes(title_text="Kcal", secondary_y=False, showgrid=True)
            fig_vol.update_yaxes(title_text="Gramas", secondary_y=True, showgrid=False)
            st.plotly_chart(fig_vol, use_container_width=True)
        else: st.info("Aguardando dados...")

    with c_main2:
        st.markdown("##### 🏦 Termodinâmica & Déficit", help="Compara a perda de peso real na balança com a perda matemática baseada no déficit calórico.")
        if not df_merged.empty:
            deficit_total = df_merged['deficit_real'].sum()
            kg_gordura = deficit_total / 7700
            peso_start = df_merged.iloc[0]['peso_kg']
            peso_curr = df_merged.iloc[-1]['peso_kg']
            perda_real = peso_start - peso_curr
            perda_teorica = deficit_total / 7700
            fator_termo = perda_real / perda_teorica if perda_teorica > 0.1 else 1.0

            st.metric("Déficit Acumulado", f"{int(deficit_total)} kcal")
            st.metric("Gordura Eliminada (Teórica)", f"{kg_gordura:.2f} kg", help="Baseado em 7700kcal = 1kg de gordura")
            if fator_termo > 1.15: lbl, clr = "🔥 Turbo", "normal"
            elif fator_termo < 0.85: lbl, clr = "❄️ Lento", "inverse"
            else: lbl, clr = "✅ Normal", "off"
            st.metric("Índice Termodinâmico", f"{fator_termo:.2f}x", lbl, delta_color=clr, help=">1.0: Perdendo mais que o previsto. <1.0: Perdendo menos (possível retenção ou adaptação).")
            st.caption(f"*Baseado no fator de atividade: {fator_atividade}x*")

    st.divider()

    # --- ROW 3: PROJEÇÃO & TREINO ---
    c_p1, c_p2 = st.columns([2, 1])

    with c_p1:
        st.markdown("##### 🎯 Projeção de Peso", help="Linha tracejada indica a meta de perda semanal. Linha sólida é o peso real.")
        if not df_peso.empty:
            df_peso['data_dt'] = pd.to_datetime(df_peso['data']).dt.date
            BASE_DATE = pd.to_datetime("2025-12-31").date()
            df_base = df_peso[df_peso['data_dt'] >= BASE_DATE].sort_values('data_dt')
            
            if not df_base.empty:
                peso_inicial = float(df_base.iloc[0]['peso_kg'])
                datas_proj = pd.date_range(start=BASE_DATE, end=hoje + timedelta(days=14))
                ritmo_diario = float(p['ritmo_semanal']) / 7
                pesos_estimados = [peso_inicial - (i * ritmo_diario) for i in range(len(datas_proj))]
                fig_proj = go.Figure
