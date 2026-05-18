import os
import streamlit as st
import pandas as pd
import numpy as np
from sqlalchemy import create_engine, text
from datetime import datetime, timedelta
import pytz
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# ============================================================================
# 1. DESIGN DE PRODUTO (MODO CLARO RESPONSIVO / ALTO CONTRASTE)
# ============================================================================
st.set_page_config(page_title="Leo's Physiology Engine", page_icon="🧬", layout="wide", initial_sidebar_state="collapsed")

st.markdown("""
    <style>
    #MainMenu {visibility: hidden;} footer {visibility: hidden;} header {visibility: hidden;}
    .badge-panel { display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 20px; }
    .badge { padding: 6px 12px; border-radius: 20px; font-size: 12px; font-weight: bold; font-family: monospace; }
    .badge-green { background-color: rgba(16, 185, 129, 0.15); color: #059669; border: 1px solid #10b981; }
    .badge-yellow { background-color: rgba(245, 158, 11, 0.15); color: #d97706; border: 1px solid #f59e0b; }
    .badge-red { background-color: rgba(239, 68, 68, 0.15); color: #dc2626; border: 1px solid #ef4444; }
    .badge-blue { background-color: rgba(59, 130, 246, 0.15); color: #2563eb; border: 1px solid #3b82f6; }
    
    div[data-testid="stMetric"] { 
        background-color: #f8fafc; padding: 15px; border-radius: 12px; border: 1px solid #e2e8f0; box-shadow: 2px 2px 8px rgba(0,0,0,0.04);
    }
    @media (prefers-color-scheme: dark) { 
        div[data-testid="stMetric"] { background-color: #1e293b; border: 1px solid #334155; box-shadow: none; }
        .badge-green { color: #10b981; } .badge-yellow { color: #f59e0b; } .badge-red { color: #ef4444; } .badge-blue { color: #3b82f6; }
    }
    </style>
    """, unsafe_allow_html=True)

# ============================================================================
# 2. CONEXÃO E ETL BLINDADO
# ============================================================================
@st.cache_resource(ttl=600)
def get_engine():
    db_url = st.secrets.get("DATABASE_URL", "")
    if db_url.startswith("postgres://"): db_url = db_url.replace("postgres://", "postgresql://", 1)
    return create_engine(db_url, pool_pre_ping=True)

def run_query(query, params=None):
    engine = get_engine()
    try:
        with engine.connect() as conn:
            df = pd.read_sql(text(query), conn, params=params)
            for col in ['data', 'log_date', 'measurement_time']:
                if col in df.columns:
                    try: df[col] = pd.to_datetime(df[col]).dt.date
                    except: pass
            return df
    except Exception as e:
        st.error(f"🚨 DB Error: {e}")
        return pd.DataFrame()

if st.query_params.get("token") != st.secrets.get("DASH_ACCESS_TOKEN"):
    st.error("🔒 Acesso Restrito."); st.stop()

hoje = datetime.now(pytz.timezone('America/Sao_Paulo')).date()
DATA_INICIO = pd.to_datetime("2025-12-30").date()

df_perfil = run_query("SELECT * FROM public.perfil WHERE id = 1")
df_peso = run_query("SELECT * FROM public.peso ORDER BY data ASC")
df_medidas = run_query("SELECT * FROM public.body_measurements ORDER BY log_date ASC")
df_bp = run_query("SELECT * FROM public.blood_pressure ORDER BY measurement_time ASC")
df_hist = run_query("SELECT data, SUM(kcal) as tkcal, SUM(proteina) as tprot, SUM(carbo) as tcarb, SUM(gordura) as tgord FROM public.consumo WHERE data >= :d GROUP BY data ORDER BY data ASC", {"d": DATA_INICIO})
df_treino = run_query("SELECT data, SUM(duracao_min) as t_min, SUM(passos_trabalho) as t_passos_trabalho, SUM(calorias) as t_cal_out FROM public.exercicios WHERE data >= :d GROUP BY data ORDER BY data ASC", {"d": DATA_INICIO})
df_hidra = run_query("SELECT data, SUM(agua_ml) as tagua FROM public.hidratacao WHERE data >= :d GROUP BY data ORDER BY data ASC", {"d": DATA_INICIO})
df_hoje_c = run_query("SELECT SUM(kcal) as k, SUM(proteina) as p, SUM(carbo) as c, SUM(gordura) as g FROM public.consumo WHERE data = :d", {"d": hoje})

p = df_perfil.iloc[0] if not df_perfil.empty else {'meta_kcal': 1415, 'meta_proteina': 104, 'meta_carbo': 105, 'meta_gordura': 71, 'meta_peso_alvo': 120.0, 'fator_atividade': 1.2, 'ritmo_semanal': 0.8}
meta_kcal, meta_prot, meta_carb, meta_gord = int(p['meta_kcal']), int(p['meta_proteina']), int(p['meta_carbo']), int(p['meta_gordura'])

# INICIALIZAÇÃO SEGURA (Evita NameError)
df_merged = pd.DataFrame()

if not df_hist.empty and not df_peso.empty:
    df_peso_u = df_peso.copy()
    df_peso_u['data_dt'] = df_peso_u['data']
    df_peso_u = df_peso_u.drop_duplicates(subset=['data_dt'], keep='last')
    
    df_hist['data_dt'] = df_hist['data']
    df_merged = pd.merge(df_hist, df_peso_u[['data_dt', 'peso_kg']], on='data_dt', how='left').ffill()
    df_merged['peso_kg'] = df_merged['peso_kg'].bfill().fillna(115.0)
    
    # Merge com preenchimento pontual de zeros (Evita poluir o DataFrame inteiro)
    for df_tmp, col_list in [(df_treino, ['t_min', 't_passos_trabalho', 't_cal_out']), (df_hidra, ['tagua'])]:
        if not df_tmp.empty:
            df_tmp['data_dt'] = df_tmp['data']
            df_merged = pd.merge(df_merged, df_tmp.groupby('data_dt')[col_list].sum().reset_index(), on='data_dt', how='left')
            for c in col_list:
                df_merged[c] = df_merged[c].fillna(0)
            
    if not df_medidas.empty:
        df_med_tmp = df_medidas.copy()
        df_med_tmp['data_dt'] = df_med_tmp['log_date']
        df_merged = pd.merge(df_merged, df_med_tmp.groupby('data_dt')[['waist_cm']].last().reset_index(), on='data_dt', how='left')
    else:
        df_merged['waist_cm'] = np.nan

    # Blindagem para o EWMA não propagar NaNs
    df_merged['waist_cm'] = df_merged['waist_cm'].bfill().ffill()

    df_merged['data'] = df_merged['data_dt']
    df_merged['peso_ewma'] = df_merged['peso_kg'].ewm(span=7, adjust=False).mean()
    df_merged['cintura_ewma'] = df_merged['waist_cm'].ewm(span=7, adjust=False).mean()
    
    df_merged['get_total'] = (((10 * df_merged['peso_kg']) + (6.25 * 178) - (5 * 41) + 5) * float(p['fator_atividade'])) + df_merged['t_cal_out']
    df_merged['deficit_real'] = df_merged['get_total'] - df_merged['tkcal']
    df_merged['%G_weltman'] = (0.31457 * df_merged['cintura_ewma']) - (0.10969 * df_merged['peso_ewma']) + 10.834
    df_merged['massa_magra'] = df_merged['peso_ewma'] * (1 - (df_merged['%G_weltman'] / 100))

# ============================================================================
# 3. MOTOR DE PROBABILIDADE FISIOLÓGICA (ESTADOS LATENTES APROXIMADOS)
# ============================================================================
if not df_merged.empty and len(df_merged) >= 3:
    atual, anterior = df_merged.iloc[-1], df_merged.iloc[-2]
    
    d_peso = atual['peso_ewma'] - anterior['peso_ewma']
    d_cintura = (atual['cintura_ewma'] - anterior['cintura_ewma']) if pd.notnull(atual['cintura_ewma']) else 0
    
    input_metrics = [pd.notnull(atual['peso_kg']), pd.notnull(atual['waist_cm']), atual['tagua'] > 0, atual['t_passos_trabalho'] > 0]
    confidence_score = int(sum(input_metrics) / len(input_metrics) * 100)
    
    criterio_ret_1 = 40 if d_peso > 0.05 and d_cintura <= 0 else 0
    criterio_ret_2 = 30 if atual['t_passos_trabalho'] > 12000 else 0
    criterio_ret_3 = 30 if atual['tagua'] < (atual['peso_kg'] * 30) else 0
    retention_score = criterio_ret_1 + criterio_ret_2 + criterio_ret_3
    
    # Bug Fix: Caractere chinês exorcizado
    criterio_rec_1 = 50 if atual['t_passos_trabalho'] > 14000 else (25 if atual['t_passos_trabalho'] > 9000 else 0)
    criterio_rec_2 = 50 if atual['deficit_real'] > 800 else (25 if atual['deficit_real'] > 400 else 0)
    recovery_load = criterio_rec_1 + criterio_rec_2

    ultimos_dias = df_merged.tail(3)
    macro_check = sum((ultimos_dias['tprot'] >= meta_prot - 10).astype(int))
    agua_check = sum((ultimos_dias['tagua'] >= (ultimos_dias['peso_kg'] * 35)).astype(int))
    consistency_score = int(((macro_check + agua_check) / 6) * 100)
    
    if retention_score >= 60: status_txt, status_class = "RETENÇÃO PROVÁVEL", "badge-yellow"
    elif d_cintura < 0 and d_peso <= 0.05: status_txt, status_class = "RECOMPOSIÇÃO EFICIENTE", "badge-green"
    elif recovery_load >= 75: status_txt, status_class = "ESTRESSE SISTÊMICO ALTO", "badge-red"
    else: status_txt, status_class = "ESTÁVEL / CRUZEIRO", "badge-blue"
else:
    confidence_score = retention_score = recovery_load = consistency_score = 0
    status_txt, status_class = "COLETANDO SINAIS", "badge-blue"

# ============================================================================
# 4. INTERFACE GRÁFICA EVOLUÍDA
# ============================================================================
st.title("🦁 Leo-Tracker Pro — Sistema de Adaptação Fisiológica")

# 🥇 CAMADA 1: ESTADO FISIOLÓGICO CENTRAL
st.markdown("### 🧬 Estado Latente Inferido")
st.markdown(f"""
    <div class="badge-panel">
        <span class="badge {status_class}">🎯 ESTADO: {status_txt}</span>
        <span class="badge {'badge-green' if confidence_score >= 75 else 'badge-yellow'}">🔍 QUALIDADE DA TELEMETRIA: {confidence_score}%</span>
        <span class="badge {'badge-green' if consistency_score >= 75 else 'badge-yellow'}">🛡️ ADERÊNCIA (3D): {consistency_score}%</span>
    </div>
    """, unsafe_allow_html=True)

c_sc1, c_sc2, c_sc3 = st.columns(3)
c_sc1.progress(retention_score / 100, text=f"💧 Risco de Retenção Hídrica/Glicogênio: {retention_score}%")
c_sc2.progress(recovery_load / 100, text=f"⚡ Carga de Estresse Fisiológico: {recovery_load}%")
c_sc3.progress(consistency_score / 100, text=f"📈 Estabilidade Comportamental: {consistency_score}%")

st.divider()

# 🥈 CAMADA 2: TENDÊNCIAS SUAVIZADAS
st.markdown("### 📉 Telemetria de Estrutura Corporal (Filtro EWMA)")
c_met1, c_met2, c_met3, c_met4 = st.columns(4)

if not df_merged.empty:
    c_met1.metric("⚖️ Peso Tendência (EWMA)", f"{atual['peso_ewma']:.2f} kg", f"{d_peso*1000:+.0f} g (48h)")
    c_met2.metric("📐 Cintura Tendência", f"{atual['cintura_ewma']:.1f} cm", f"{d_cintura:+.1f} cm")
    c_met3.metric("🧬 Gordura (Weltman)", f"{atual['%G_weltman']:.1f} %")
    c_met4.metric("💪 Massa Magra Ativa", f"{atual['massa_magra']:.1f} kg")

    fig_trends = make_subplots(rows=1, cols=2, subplot_titles=("Trajetória de Peso (EWMA)", "Evolução Antropométrica (Cintura)"))
    fig_trends.add_trace(go.Scatter(x=df_merged['data'], y=df_merged['peso_ewma'], name="Peso EWMA", line=dict(color='#ef4444', width=4)), row=1, col=1)
    fig_trends.add_trace(go.Scatter(x=df_merged['data'], y=df_merged['cintura_ewma'], name="Cintura EWMA", line=dict(color='#10b981', width=4)), row=1, col=2)
    fig_trends.update_layout(height=260, template="plotly_white", showlegend=False, margin=dict(l=10,r=10,t=30,b=10))
    st.plotly_chart(fig_trends, use_container_width=True)

st.divider()

# 🥉 CAMADA 3: NUTRIÇÃO ACIONÁVEL
st.markdown("### 🍽️ Cota Energética Diária")
c_nut_l, c_nut_r = st.columns([1, 2])

with c_nut_l:
    k_hoje = df_hoje_c.iloc[0]['k'] if not df_hoje_c.empty and pd.notnull(df_hoje_c.iloc[0]['k']) else 0
    p_hoje = df_hoje_c.iloc[0]['p'] if not df_hoje_c.empty and pd.notnull(df_hoje_c.iloc[0]['p']) else 0
    c_hoje = df_hoje_c.iloc[0]['c'] if not df_hoje_c.empty and pd.notnull(df_hoje_c.iloc[0]['c']) else 0
    g_hoje = df_hoje_c.iloc[0]['g'] if not df_hoje_c.empty and pd.notnull(df_hoje_c.iloc[0]['g']) else 0
    rest_k = meta_kcal - k_hoje
    st.metric("🔥 Saldo Calórico Restante", f"{int(rest_k)} kcal", delta=f"Cota Alvo: {meta_kcal}", delta_color="normal" if rest_k >= 0 else "inverse")

with c_nut_r:
    m_p_status = "🟢 ALVO SEGUIDO" if p_hoje >= meta_prot else f"🟡 FALTA {int(meta_prot - p_hoje)}g"
    m_c_status = "🔴 LIMITE CRÍTICO" if c_hoje >= meta_carb - 15 else "🟢 DENTRO DO BUDGET"
    m_g_status = "🔴 LIMITE CRÍTICO" if g_hoje >= meta_gord - 10 else "🟢 DENTRO DO BUDGET"
    st.markdown(f"🥩 **Proteínas Ingeridas:** {int(p_hoje)}g / {meta_prot}g ➔ **{m_p_status}**")
    st.markdown(f"🍞 **Carboidratos Ingeridos:** {int(c_hoje)}g / {meta_carb}g ➔ **{m_c_status}**")
    st.markdown(f"🥑 **Gorduras Ingeridas:** {int(g_hoje)}g / {meta_gord}g ➔ **{m_g_status}**")

st.divider()

# 🧠 CAMADA 4: CONTROLADOR PROPORCIONAL (P-CONTROLLER ADAPTATIVO)
st.markdown("### 🤖 Orientação de Trajetória (P-Controller Adaptativo)")

if not df_peso.empty and not df_merged.empty and len(df_merged) >= 7:
    passado_7d = df_merged.iloc[-8] if len(df_merged) >= 8 else df_merged.iloc[0]
    peso_baseline = passado_7d['peso_ewma']
    ritmo_semanal = float(p.get('ritmo_semanal', 0.8))
    sp_hoje = peso_baseline - ritmo_semanal
    pv_hoje = atual['peso_ewma']
    erro_kg = pv_hoje - sp_hoje
    
    col_p1, col_p2, col_p3 = st.columns(3)
    col_p1.metric("🎯 Rampa Teórica da Semana", f"{sp_hoje:.2f} kg", f"Base 7d: {peso_baseline:.2f} kg", delta_color="off")
    col_p2.metric("📊 Inércia Real (EWMA)", f"{pv_hoje:.2f} kg")
    
    if erro_kg <= 0.05 and erro_kg >= -0.6:
        col_p3.metric("🏆 Status", f"{erro_kg*1000:+.0f} g", delta_color="normal")
        st.markdown(f"💡 **Voo de Cruzeiro:** Você está atingindo o ritmo de desinflamação da semana. Manter cota operacional cravada em **{meta_kcal} kcal**.")
    elif erro_kg < -0.6:
        col_p3.metric("🔥 Aceleração", f"{erro_kg*1000:+.0f} g", delta_color="normal")
        st.markdown(f"💡 **Over-performance:** Você está {abs(erro_kg):.2f}kg à frente da meta. Mantenha os **{meta_kcal} kcal** e garanta a proteína para blindar a massa magra.")
    else:
        col_p3.metric("⚠️ Desvio", f"{erro_kg*1000:+.0f} g", delta_color="inverse")
        ajuste = -(erro_kg * 500)
        kcal_recalc = max(1200, min(meta_kcal + ajuste, atual['get_total']))
        st.markdown(f"💡 **P-Controller Ativo:** Inércia levemente atrasada. Para corrigir a rota, o controlador proporcional sugere um teto de **{int(kcal_recalc)} kcal** nas próximas 24h.")
else:
    st.info("⏳ Coletando dados (mínimo de 7 dias) para acionar o P-Controller Adaptativo.")

# ============================================================================
# 5. INFERÊNCIA CAUSAL E ELASTIC NET (O GÊMEO DIGITAL LIVRE DE VAZAMENTO)
# ============================================================================
st.divider()
st.markdown("### 🧠 Gêmeo Digital Metabólico (ElasticNet ML)")

try:
    from sklearn.linear_model import ElasticNet
    from sklearn.preprocessing import StandardScaler
    from sklearn.metrics import r2_score
    from sklearn.model_selection import train_test_split

    if not df_merged.empty and len(df_merged) > 20:
        df_ml = df_merged.copy()

        df_ml['delta_peso'] = df_ml['peso_ewma'].diff()
        df_ml['delta_cintura'] = df_ml['cintura_ewma'].diff()
        df_ml['retencao_estimada'] = df_ml['delta_peso'] - (df_ml['delta_cintura'].fillna(0) * 0.5) 
        
        # Inserção de variáveis não lineares e proxies de comportamento
        df_ml['carb_3d_acum'] = df_ml['tcarb'].rolling(3).sum().shift(1)
        df_ml['deficit_7d_acum'] = df_ml['deficit_real'].rolling(7).sum().shift(1)
        df_ml['passos_3d_med'] = df_ml['t_passos_trabalho'].rolling(3).mean().shift(1)
        df_ml['dia_semana'] = pd.to_datetime(df_ml['data']).dt.dayofweek # Previne "Correlações Burras" do fim de semana

        lags = [1, 3, 5]
        features_base = ['tcarb', 'tprot', 'tgord', 'tagua', 't_passos_trabalho', 'deficit_real']
        for col in features_base:
            for lag in lags: df_ml[f'{col}_lag{lag}'] = df_ml[col].shift(lag)

        col_ctrl1, col_ctrl2 = st.columns([1, 2])
        with col_ctrl1:
            target_view = st.selectbox("🎯 Selecione a Lente de Observação (Alvo):", ["Retenção Hídrica/Inflamação", "Cintura (Gordura Visceral)", "Peso Bruto (Misto)"])
            target_map = {"Retenção Hídrica/Inflamação": "retencao_estimada", "Cintura (Gordura Visceral)": "delta_cintura", "Peso Bruto (Misto)": "delta_peso"}
            target_col = target_map[target_view]

        features_ml = [c for c in df_ml.columns if '_lag' in c or '_acum' in c or '_med' in c or c == 'dia_semana']
        df_ml_clean = df_ml.dropna(subset=[target_col] + features_ml)

        if len(df_ml_clean) > 25: # Exige um pouco mais de dados para não quebrar o Test Split
            X = df_ml_clean[features_ml]
            y = df_ml_clean[target_col]

            # BLINDAGEM CONTRA DATA LEAKAGE: Time-Series Split (Sem embaralhar o tempo)
            X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, shuffle=False)

            scaler = StandardScaler()
            X_train_scaled = scaler.fit_transform(X_train)
            X_test_scaled = scaler.transform(X_test)

            model = ElasticNet(alpha=0.01, l1_ratio=0.5, max_iter=2000)
            model.fit(X_train_scaled, y_train)
            
            # Validação no futuro (dados que o modelo nunca viu)
            preds = model.predict(X_test_scaled)
            r2 = r2_score(y_test, preds)

            with col_ctrl2:
                r2_color = "normal" if r2 > 0.15 else "inverse"
                st.metric("🧠 Capacidade Explicativa Real (R² em Out-of-Sample)", f"{r2:.2%}", delta="Poder de Sinal vs Ruído", delta_color=r2_color)
                if r2 < 0.1: st.caption("⚠️ R² baixo: Na validação cruzada, o modelo não sustentou a previsão. Muito ruído aleatório ou variáveis latentes faltando.")

            # Recalcula coeficientes na base inteira APENAS para visualização da autópsia causal
            X_full_scaled = scaler.fit_transform(X)
            model_viz = ElasticNet(alpha=0.01, l1_ratio=0.5, max_iter=2000)
            model_viz.fit(X_full_scaled, y)
            
            coefs = pd.DataFrame({'Variavel': features_ml, 'Impacto': model_viz.coef_})
            coefs = coefs[coefs['Impacto'].abs() > 0.001].sort_values(by='Impacto')
            
            if not coefs.empty:
                rename_map = {'tcarb': 'Carbo', 'tprot': 'Proteína', 'tgord': 'Gordura', 'tagua': 'Água', 't_passos_trabalho': 'Passos', 'deficit_real': 'Déficit', 'dia_semana': 'Dia da Semana'}
                def beautify_name(name):
                    for k, v in rename_map.items(): name = name.replace(k, v)
                    name = name.replace('_lag1', ' (Ontem)').replace('_lag3', ' (-3 Dias)').replace('_lag5', ' (-5 Dias)')
                    name = name.replace('_3d_acum', ' (Acum 3D)').replace('_7d_acum', ' (Acum 7D)').replace('_3d_med', ' (Média 3D)')
                    return name
                
                coefs['Variavel_Limpa'] = coefs['Variavel'].apply(beautify_name)
                coefs['Cor'] = coefs['Impacto'].apply(lambda x: '#ef4444' if x > 0 else '#10b981') 

                fig_ml = go.Figure(go.Bar(x=coefs['Impacto'], y=coefs['Variavel_Limpa'], orientation='h', marker_color=coefs['Cor'], text=coefs['Impacto'].apply(lambda x: f"{x:+.3f}"), textposition='auto'))
                fig_ml.update_layout(title=f"Autópsia Fisiológica (Base Global)", height=max(300, len(coefs) * 35), template="plotly_white", margin=dict(l=10,r=10,t=30,b=10), xaxis_title="Impacto (Verde = Reduz | Vermelho = Aumenta)", yaxis=dict(autorange="reversed"))
                fig_ml.add_vline(x=0, line_width=2, line_color="black")
                st.plotly_chart(fig_ml, use_container_width=True)
            else:
                st.info("🧠 O ElasticNet zerou todas as variáveis. Nenhum padrão causal forte encontrado.")
            st.caption(f"Amostragem limpa: **{len(df_ml_clean)} dias** (Treino: {len(X_train)} / Validação: {len(X_test)}).")
        else:
            st.warning("⚠️ Volume de dados pós-limpeza insuficiente para treino e validação cruzada. Continue alimentando o Tracker.")
except ImportError:
    st.error("🚨 Adicione `scikit-learn` ao seu ambiente para rodar o ElasticNet.")
