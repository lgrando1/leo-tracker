import streamlit as st
import pandas as pd
import numpy as np
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
# 2. CONEXÃO BLINDADA
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
# 3. ETL (EXTRAÇÃO E TRATAMENTO)
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
# 4. ORGANIZAÇÃO EM ABAS
# ============================================================================
tab_qs, tab_dash = st.tabs(["🧠 Quantified Self (Engenharia Metabólica)", "🦁 Dashboard Original"])

# ============================================================================
# ABA 1: QUANTIFIED SELF - DESINFLAMAÇÃO VS PERDA REAL
# ============================================================================
with tab_qs:
    st.markdown("### 🧠 Laboratório de Termodinâmica & Turnos de Jejum")
    
    if not df_merged.empty:
        # --- LÓGICA CORE: O ALGORITMO DE QUALIDADE DA PERDA ---
        df_qs = df_merged.copy()
        
        # 1. Delta de Peso (O que a balança diz)
        df_qs['peso_ontem'] = df_qs['peso_kg'].shift(1)
        # Se positivo: perdeu peso. Se negativo: ganhou peso.
        df_qs['perda_real_kg'] = df_qs['peso_ontem'] - df_qs['peso_kg'] 
        
        # 2. Delta Esperado (O que a física diz)
        df_qs['perda_esperada_kg'] = df_qs['deficit_real'] / 7700
        
        # 3. O Fator de Desinflamação
        df_qs['fator_desinflamacao'] = df_qs['perda_real_kg'] - df_qs['perda_esperada_kg']
        
        # Classificação do Fator
        def classificar_perda(fator):
            if pd.isna(fator): return 'Sem Dados'
            if fator > 0.1: return 'Água/Desinflamação (Azul)'
            elif fator < -0.1: return 'Retenção/Glicogênio (Amarelo)'
            else: return 'Perda de Gordura Pura (Vermelho)'
            
        def cor_fator(fator):
            if pd.isna(fator): return '#bdc3c7'
            if fator > 0.1: return '#3498DB' # Azul
            elif fator < -0.1: return '#F1C40F' # Amarelo
            else: return '#E74C3C' # Vermelho
            
        df_qs['tipo_perda'] = df_qs['fator_desinflamacao'].apply(classificar_perda)
        df_qs['cor'] = df_qs['fator_desinflamacao'].apply(cor_fator)

        # 4. Variável de Jejum (Simulada temporariamente até criação da coluna real no banco)
        if 'jejum_h' not in df_qs.columns:
            np.random.seed(42) # Mantém visualização consistente
            df_qs['jejum_h'] = np.random.uniform(14, 24, size=len(df_qs)).round(1)
            st.info("💡 **Aviso Tático:** As horas de jejum estão sendo simuladas. Precisamos conectar o `timestamp` das suas refeições do banco de dados para o algoritmo ler o Shift real.")

        # Limpar o primeiro dia (sem 'ontem' para comparar)
        df_qs = df_qs.dropna(subset=['perda_real_kg'])

        # --- EXIBIÇÃO DE KPIs (ÚLTIMO DIA VÁLIDO) ---
        last_day = df_qs.iloc[-1]
        
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("⚖️ Balança (Real)", f"{last_day['perda_real_kg']*1000:.0f} g", "Variação Diária")
        col2.metric("📐 Termodinâmica (Esperado)", f"{last_day['perda_esperada_kg']*1000:.0f} g", "Gordura Pura Calculada")
        col3.metric("💧 Fator Desinflamação", f"{last_day['fator_desinflamacao']*1000:.0f} g", 
                    help="Positivo = Eliminou água. Negativo = Reteu líquido/glicogênio.")
        
        # Status
        status_color = "🟢" if last_day['tipo_perda'] == 'Perda de Gordura Pura (Vermelho)' else "🔵" if "Desinflamação" in last_day['tipo_perda'] else "🟡"
        col4.markdown(f"**Qualidade da Perda (Hoje):**<br> {status_color} {last_day['tipo_perda'].split(' (')[0]}", unsafe_allow_html=True)

        st.markdown("---")

        # --- GRÁFICOS DO LABORATÓRIO ---
        c_qs1, c_qs2 = st.columns([2, 1])

        with c_qs1:
            st.markdown("##### 🧬 Série Temporal: Água vs Gordura vs Retenção")
            fig_qs_time = go.Figure()
            
            # Barras representando a perda real de peso, pintadas pela "Qualidade"
            fig_qs_time.add_trace(go.Bar(
                x=df_qs['data_dt'], 
                y=df_qs['perda_real_kg'], 
                marker_color=df_qs['cor'],
                name='Variação na Balança',
                text=df_qs['tipo_perda'],
                hoverinfo='x+y+text'
            ))
            
            # Linha tracejada do déficit teórico
            fig_qs_time.add_trace(go.Scatter(
                x=df_qs['data_dt'], 
                y=df_qs['perda_esperada_kg'], 
                mode='lines', 
                name='Queima de Gordura Teórica', 
                line=dict(color='#2ECC71', dash='dash', width=2)
            ))
            
            fig_qs_time.update_layout(height=400, template="plotly_white", hovermode="x unified",
                                      yaxis_title="Variação de Peso (kg)",
                                      legend=dict(orientation="h", y=1.1))
            st.plotly_chart(fig_qs_time, use_container_width=True)

        with c_qs2:
            st.markdown("##### ⏳ O 'Shift' Metabólico (Jejum vs Perda)")
            fig_shift = go.Figure()
            
            # Gráfico de Dispersão para encontrar o Sweet Spot do Jejum
            fig_shift.add_trace(go.Scatter(
                x=df_qs['jejum_h'], 
                y=df_qs['perda_real_kg'],
                mode='markers',
                marker=dict(size=10, color=df_qs['cor'], opacity=0.8, line=dict(width=1, color='black')),
                text=df_qs['data_dt'],
                hoverinfo='text+x+y'
            ))
            
            # Linha de tendência (Moving Average ou Polyfit simples)
            if len(df_qs) > 2:
                z = np.polyfit(df_qs['jejum_h'], df_qs['perda_real_kg'], 1)
                poly_func = np.poly1d(z) # <-- Variável isolada para não conflitar com o Perfil
                x_trend = np.linspace(df_qs['jejum_h'].min(), df_qs['jejum_h'].max(), 100)
                fig_shift.add_trace(go.Scatter(x=x_trend, y=poly_func(x_trend), mode='lines', name='Tendência', line=dict(color='black', dash='dot')))

            fig_shift.update_layout(height=400, template="plotly_white", 
                                    xaxis_title="Horas de Jejum", yaxis_title="Delta de Peso (kg)",
                                    showlegend=False)
            st.plotly_chart(fig_shift, use_container_width=True)

        st.markdown("""
        **🔍 Como ler o seu painel:**
        * 🔵 **Barras Azuis:** Dias de jejum pesado ou restrição severa. Você perdeu peso na balança muito além da queima calórica (Desinflamou/Perdeu água).
        * 🔴 **Barras Vermelhas:** O peso que caiu na balança bate exatamente com as calorias que você cortou. Isso é fogo na gordura pura.
        * 🟡 **Barras Amarelas:** A balança subiu ou estagnou, mas o seu déficit calórico existiu. Isso não é engordar. É retenção hídrica ou reabastecimento de glicogênio nos músculos.
        """)

# ============================================================================
# ABA 2: DASHBOARD ORIGINAL (MANTIDO)
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
                fig_proj = go.Figure()
                fig_proj.add_trace(go.Scatter(x=datas_proj, y=pesos_estimados, mode='lines', name='Meta Ideal', line=dict(color='#29B5E8', dash='dash')))
                fig_proj.add_trace(go.Scatter(x=df_base['data_dt'], y=df_base['peso_kg'], mode='lines+markers', name='Realizado', line=dict(color='#FF4B4B', width=3)))
                fig_proj.update_layout(height=300, margin=dict(l=10,r=10,t=20,b=10), legend=dict(orientation="h", y=1.1), template="plotly_white")
                st.plotly_chart(fig_proj, use_container_width=True)

    with c_p2:
        st.markdown("##### 🏃‍♂️ Consistência de Treino")
        if not df_merged.empty and 't_passos' in df_merged.columns:
            fig_tr = make_subplots(specs=[[{"secondary_y": True}]])
            fig_tr.add_trace(go.Bar(x=df_merged['data'], y=df_merged['t_min'], name='Minutos', marker_color='#F1C40F'), secondary_y=False)
            fig_tr.add_trace(go.Scatter(x=df_merged['data'], y=df_merged['t_passos'], name='Passos', mode='lines', line=dict(color='#8E44AD', width=2)), secondary_y=True)
            fig_tr.update_layout(height=300, margin=dict(l=10,r=10,t=20,b=10), showlegend=False, template="plotly_white")
            st.plotly_chart(fig_tr, use_container_width=True)

    st.divider()

    # --- ROW 4: SAÚDE ---
    st.markdown("##### 🧬 Indicadores de Saúde")
    col_s1, col_s2, col_s3 = st.columns(3)

    with col_s1:
        if not df_medidas.empty:
            fig_bf = go.Figure(go.Scatter(x=df_medidas['log_date'], y=df_medidas['body_fat_est'], mode='lines+markers', name="BF%", line=dict(color='#e67e22')))
            fig_bf.update_layout(title="Gordura Corporal (%)", height=250, margin=dict(l=10,r=10,t=30,b=10))
            st.plotly_chart(fig_bf, use_container_width=True)

    with col_s2:
        if not df_bp.empty:
            fig_bp = go.Figure()
            fig_bp.add_trace(go.Scatter(x=df_bp['measurement_time'], y=df_bp['systolic'], name="Sys", line=dict(color='#c0392b')))
            fig_bp.add_trace(go.Scatter(x=df_bp['measurement_time'], y=df_bp['diastolic'], name="Dia", line=dict(color='#2980b9')))
            fig_bp.update_layout(title="Pressão Arterial", height=250, margin=dict(l=10,r=10,t=30,b=10))
            st.plotly_chart(fig_bp, use_container_width=True)

    with col_s3:
        if not df_hist.empty:
            df_macros = df_hist.copy()
            df_macros['tot'] = (df_macros['tprot']*4 + df_macros['tcarb']*4 + df_macros['tgord']*9).replace(0, 1)
            fig_stack = go.Figure()
            fig_stack.add_trace(go.Bar(x=df_macros['data'], y=(df_macros['tprot']*4/df_macros['tot'])*100, name='P', marker_color='#3366CC'))
            fig_stack.add_trace(go.Bar(x=df_macros['data'], y=(df_macros['tgord']*9/df_macros['tot'])*100, name='G', marker_color='#DC3912'))
            fig_stack.add_trace(go.Bar(x=df_macros['data'], y=(df_macros['tcarb']*4/df_macros['tot'])*100, name='C', marker_color='#FF9900'))
            fig_stack.update_layout(title="Distribuição Macros (%)", barmode='stack', height=250, margin=dict(l=10,r=10,t=30,b=10), yaxis=dict(range=[0, 100]), showlegend=False)
            st.plotly_chart(fig_stack, use_container_width=True)

    st.divider()

    # ============================================================================
    # 5. ANÁLISE ESTATÍSTICA (EDA)
    # ============================================================================
    st.markdown("### 📊 Análise de Tendências (Médias Móveis & Extremos)")

    if not df_merged.empty:
        cols_eda = ['peso_kg', 'tkcal', 'tprot', 'tcarb', 'tgord', 't_min', 't_passos', 'deficit_real']
        df_eda = df_merged[['data', *cols_eda]].copy().sort_values('data').fillna(0)

        def calc_mean(df, days, col): return df.tail(days)[col].mean()

        metrics_list = [
            ("⚖️ Peso Médio (kg)", 'peso_kg'),
            ("🔥 Calorias (kcal)", 'tkcal'),
            ("🥩 Proteína (g)", 'tprot'),
            ("🍞 Carbo (g)", 'tcarb'),
            ("🥑 Gordura (g)", 'tgord'),
            ("⏱️ Treino (min)", 't_min'),
            ("👣 Passos", 't_passos'),
            ("📉 Déficit Diário", 'deficit_real')
        ]

        eda_data = []
        for label, col in metrics_list:
            row = {
                "Indicador": label,
                "3 Dias": f"{calc_mean(df_eda, 3, col):.1f}",
                "7 Dias": f"{calc_mean(df_eda, 7, col):.1f}",
                "30 Dias": f"{calc_mean(df_eda, 30, col):.1f}",
                "Média (Total)": f"{df_eda[col].mean():.1f}",
                "Mínimo": f"{df_eda[col].min():.1f}",
                "Máximo": f"{df_eda[col].max():.1f}"
            }
            eda_data.append(row)

        st.table(pd.DataFrame(eda_data))

        st.markdown("##### 📈 Evolução de Macronutrientes (Gramas)")
        fig_macros_grams = go.Figure()
        fig_macros_grams.add_trace(go.Scatter(x=df_eda['data'], y=df_eda['tprot'], name='Proteína (g)', mode='lines+markers', line=dict(color='#3366CC', width=3)))
        fig_macros_grams.add_trace(go.Scatter(x=df_eda['data'], y=df_eda['tcarb'], name='Carbo (g)', mode='lines+markers', line=dict(color='#FF9900', width=2)))
        fig_macros_grams.add_trace(go.Scatter(x=df_eda['data'], y=df_eda['tgord'], name='Gordura (g)', mode='lines+markers', line=dict(color='#DC3912', width=2)))
        fig_macros_grams.update_layout(height=350, margin=dict(l=10,r=10,t=20,b=10), legend=dict(orientation="h", y=1.1), template="plotly_white", yaxis_title="Gramas")
        st.plotly_chart(fig_macros_grams, use_container_width=True)

    # ============================================================================
    # 6. GLOSSÁRIO E METODOLOGIA
    # ============================================================================
    with st.expander("📚 Metodologia e Glossário Técnico (Clique para abrir)", expanded=False):
        st.markdown("""
        ### 1. Estimativa de Gasto Energético (GET)
        * **Fórmula Base:** Equação de Mifflin-St Jeor (Padrão ouro para obesidade/perda de peso).
        * **Ajuste:** Multiplicado pelo **Fator de Atividade** (Configurado para 1.2 - Sedentário/Escritório).
        * **Gasto Ativo:** Adicionamos as calorias do exercício registradas no **Iron N1** (Caminhada/Musculação) sobre o basal.
        
        ### 2. Termodinâmica e Déficit
        * **Déficit Real:** Diferença entre o Gasto Total Estimado e as Calorias Ingeridas.
        * **Perda Teórica:** Déficit Acumulado / 7700 (Considerando que 1kg de gordura ≈ 7700kcal).
        * **Índice Termodinâmico:** Razão entre a perda na balança e a perda teórica.
            * *> 1.0:* Perda acelerada (metabolismo alto ou desidratação).
            * *< 1.0:* Perda lenta (possível retenção hídrica, erro de contagem ou adaptação metabólica).
        
        ### 3. Densidade Calórica
        * Analisa a relação entre **Volume de Comida (g)** e **Calorias (kcal)**.
        * **Objetivo:** Manter barras de volume altas e linha de calorias baixa (Saciedade).
        
        ### 4. Projeção Linear
        * Calculada com base na meta de **0.8kg/semana**.
        * A linha tracejada mostra o caminho ideal até a meta.
        """)

    st.caption("Leo Tracker Smart View v4.4 | Quantified Self Edition")
