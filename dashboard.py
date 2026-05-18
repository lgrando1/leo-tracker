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
# 1. DESIGN DE PRODUTO (REDUÇÃO DE TEXTO / FOCO EM BADGES)
# ============================================================================
st.set_page_config(page_title="Leo's Physiology Engine", page_icon="🧬", layout="wide", initial_sidebar_state="collapsed")

# ============================================================================
# 1. DESIGN DE PRODUTO (MODO CLARO RESPONSIVO / ALTO CONTRASTE)
# ============================================================================
st.set_page_config(page_title="Leo's Physiology Engine", page_icon="🧬", layout="wide", initial_sidebar_state="collapsed")

st.markdown("""
    <style>
    #MainMenu {visibility: hidden;} footer {visibility: hidden;} header {visibility: hidden;}
    
    /* Painel de Badges */
    .badge-panel { display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 20px; }
    .badge { padding: 6px 12px; border-radius: 20px; font-size: 12px; font-weight: bold; font-family: monospace; }
    .badge-green { background-color: rgba(16, 185, 129, 0.15); color: #059669; border: 1px solid #10b981; }
    .badge-yellow { background-color: rgba(245, 158, 11, 0.15); color: #d97706; border: 1px solid #f59e0b; }
    .badge-red { background-color: rgba(239, 68, 68, 0.15); color: #dc2626; border: 1px solid #ef4444; }
    .badge-blue { background-color: rgba(59, 130, 246, 0.15); color: #2563eb; border: 1px solid #3b82f6; }
    
    /* MODO CLARO POR PADRÃO (Cards com fundo suave e borda leve) */
    div[data-testid="stMetric"] { 
        background-color: #f8fafc; 
        padding: 15px; 
        border-radius: 12px; 
        border: 1px solid #e2e8f0;
        box-shadow: 2px 2px 8px rgba(0,0,0,0.04);
    }
    
    /* SÓ ativa fundo escuro se o celular/navegador do Leo pedir o modo noturno */
    @media (prefers-color-scheme: dark) { 
        div[data-testid="stMetric"] { 
            background-color: #1e293b; 
            border: 1px solid #334155; 
            box-shadow: none;
        }
        .badge-green { color: #10b981; }
        .badge-yellow { color: #f59e0b; }
        .badge-red { color: #ef4444; }
        .badge-blue { color: #3b82f6; }
    }
    </style>
    """, unsafe_allow_html=True)

# ============================================================================
# 2. CONEXÃO E ETL BLINDADO COM CHAVE UNIFICADA
# ============================================================================
@st.cache_resource(ttl=600)
def get_engine():
    db_url = st.secrets.get("DATABASE_URL", "")
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)
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

# Extrações
df_perfil = run_query("SELECT * FROM public.perfil WHERE id = 1")
df_peso = run_query("SELECT * FROM public.peso ORDER BY data ASC")
df_medidas = run_query("SELECT * FROM public.body_measurements ORDER BY log_date ASC")
df_bp = run_query("SELECT * FROM public.blood_pressure ORDER BY measurement_time ASC")
df_hist = run_query("SELECT data, SUM(kcal) as tkcal, SUM(proteina) as tprot, SUM(carbo) as tcarb, SUM(gordura) as tgord FROM public.consumo WHERE data >= :d GROUP BY data ORDER BY data ASC", {"d": DATA_INICIO})
df_treino = run_query("SELECT data, SUM(duracao_min) as t_min, SUM(passos_trabalho) as t_passos_trabalho, SUM(calorias) as t_cal_out FROM public.exercicios WHERE data >= :d GROUP BY data ORDER BY data ASC", {"d": DATA_INICIO})
df_hidra = run_query("SELECT data, SUM(agua_ml) as tagua FROM public.hidratacao WHERE data >= :d GROUP BY data ORDER BY data ASC", {"d": DATA_INICIO})
df_hoje_c = run_query("SELECT SUM(kcal) as k, SUM(proteina) as p, SUM(carbo) as c, SUM(gordura) as g FROM public.consumo WHERE data = :d", {"d": hoje})

p = df_perfil.iloc[0] if not df_perfil.empty else {'meta_kcal': 1415, 'meta_proteina': 104, 'meta_carbo': 105, 'meta_gordura': 71, 'meta_peso_alvo': 120.0, 'fator_atividade': 1.2}
meta_kcal, meta_prot, meta_carb, meta_gord = int(p['meta_kcal']), int(p['meta_proteina']), int(p['meta_carbo']), int(p['meta_gordura'])

# Consolidação em tempo de execução via chave unificada 'data_dt'
if not df_hist.empty and not df_peso.empty:
    df_peso_u = df_peso.copy()
    df_peso_u['data_dt'] = df_peso_u['data']
    df_peso_u = df_peso_u.drop_duplicates(subset=['data_dt'], keep='last')
    
    df_hist['data_dt'] = df_hist['data']
    df_merged = pd.merge(df_hist, df_peso_u[['data_dt', 'peso_kg']], on='data_dt', how='left').ffill()
    df_merged['peso_kg'] = df_merged['peso_kg'].bfill().fillna(115.0)
    
    for df_tmp, col_list in [(df_treino, ['t_min', 't_passos_trabalho', 't_cal_out']), (df_hidra, ['tagua'])]:
        if not df_tmp.empty:
            df_tmp['data_dt'] = df_tmp['data']
            df_merged = pd.merge(df_merged, df_tmp.groupby('data_dt')[col_list].sum().reset_index(), on='data_dt', how='left').fillna(0)
            
    if not df_medidas.empty:
        df_med_tmp = df_medidas.copy()
        df_med_tmp['data_dt'] = df_med_tmp['log_date']
        df_merged = pd.merge(df_merged, df_med_tmp.groupby('data_dt')[['waist_cm']].last().reset_index(), on='data_dt', how='left').ffill()
    else:
        df_merged['waist_cm'] = np.nan

    df_merged['data'] = df_merged['data_dt']
    df_merged['peso_ewma'] = df_merged['peso_kg'].ewm(span=7, adjust=False).mean()
    df_merged['cintura_ewma'] = df_merged['waist_cm'].ewm(span=7, adjust=False).mean().ffill()
    
    df_merged['get_total'] = (((10 * df_merged['peso_kg']) + (6.25 * 178) - (5 * 41) + 5) * float(p['fator_atividade'])) + df_merged['t_cal_out']
    df_merged['deficit_real'] = df_merged['get_total'] - df_merged['tkcal']
    df_merged['%G_weltman'] = (0.31457 * df_merged['cintura_ewma']) - (0.10969 * df_merged['peso_ewma']) + 10.834
    df_merged['massa_magra'] = df_merged['peso_ewma'] * (1 - (df_merged['%G_weltman'] / 100))

# ============================================================================
# 3. MOTOR DE PROBABILIDADE FISIOLÓGICA (PROBABILISTIC COGNITION)
# ============================================================================
if not df_merged.empty and len(df_merged) >= 3:
    atual, anterior = df_merged.iloc[-1], df_merged.iloc[-2]
    
    # 📐 Deltas Suavizados
    d_peso = atual['peso_ewma'] - anterior['peso_ewma']
    d_cintura = (atual['cintura_ewma'] - anterior['cintura_ewma']) if pd.notnull(atual['cintura_ewma']) else 0
    
    # 🧠 Heurísticas Contínuas (Fuzzy/Probabilísticas)
    # 1. Nível de Confiança do Sistema (Baseado em Dados Faltantes)
    input_metrics = [pd.notnull(atual['peso_kg']), pd.notnull(atual['waist_cm']), atual['tagua'] > 0, atual['t_passos_trabalho'] > 0]
    confidence_score = int(sum(input_metrics) / len(input_metrics) * 100)
    
    # 2. Score de Retenção Hídrica (0 a 100%)
    criterio_ret_1 = 40 if d_peso > 0.05 and d_cintura <= 0 else 0
    criterio_ret_2 = 30 if atual['t_passos_trabalho'] > 12000 else 0
    criterio_ret_3 = 30 if atual['tagua'] < (atual['peso_kg'] * 30) else 0
    retention_score = criterio_ret_1 + criterio_ret_2 + criterio_ret_3
    
    # 3. Score de Recuperação / Carga (0 a 100%)
    criterio_rec_1 = 50 if atual['t_passos_trabalho'] > 14000 else (25 if atual['t_passos_trabalho'] > 9000 else 0)
    criterio_rec_2 = 50 if atual['deficit_real'] > 800 else (25 if atual['deficit_real'] > 400 else 0)
    recovery_load =开 = criterio_rec_1 + criterio_rec_2

    # 4. Score de Consistência Comportamental (Últimos 3 dias)
    ultimos_dias = df_merged.tail(3)
    macro_check = sum((ultimos_dias['tprot'] >= meta_prot - 10).astype(int))
    agua_check = sum((ultimos_dias['tagua'] >= (ultimos_dias['peso_kg'] * 35)).astype(int))
    consistency_score = int(((macro_check + agua_check) / 6) * 100)
    
    # Classificação de Estado por Predominância Contínua
    if retention_score >= 60:
        status_txt, status_class = "RETENÇÃO PROVÁVEL", "badge-yellow"
    elif d_cintura < 0 and d_peso <= 0.05:
        status_txt, status_class = "RECOMPOSIÇÃO EFICIENTE", "badge-green"
    elif recovery_load >= 75:
        status_txt, status_class = "RECUPERAÇÃO COMPROMETIDA", "badge-red"
    else:
        status_txt, status_class = "ESTÁVEL / CRUZEIRO", "badge-blue"
else:
    confidence_score = retention_score = recovery_load = consistency_score = 0
    status_txt, status_class = "COLETANDO SINAIS", "badge-blue"

# ============================================================================
# 4. INTERFACE GRÁFICA EVOLUÍDA (CAMADA DE INTELIGÊNCIA VISUAL)
# ============================================================================
st.title("🦁 Leo-Tracker Pro — Feature Store Coerente")

# 🥇 CAMADA 1: ESTADO FISIOLÓGICO CENTRAL (BADGES & SCORES)
st.markdown("### 🧬 Estado Geral de Adaptação")
st.markdown(f"""
    <div class="badge-panel">
        <span class="badge {status_class}">🎯 ESTADO: {status_txt}</span>
        <span class="badge {'badge-green' if confidence_score >= 75 else 'badge-yellow'}">🔍 CONFIANÇA DO MODELO: {confidence_score}%</span>
        <span class="badge {'badge-green' if consistency_score >= 75 else 'badge-yellow'}">🛡️ ADERÊNCIA (3D): {consistency_score}%</span>
    </div>
    """, unsafe_allow_html=True)

# Cards de Interpretação Probabilística
c_sc1, c_sc2, c_sc3 = st.columns(3)
c_sc1.progress(retention_score / 100, text=f"💧 Probabilidade de Retenção Hídrica: {retention_score}%")
c_sc2.progress(recovery_load / 100, text=f"⚡ Sobrecarga / Necessidade de Repouso: {recovery_load}%")
c_sc3.progress(consistency_score / 100, text=f"📈 Score de Consistência Comportamental: {consistency_score}%")

st.divider()

# 🥈 CAMADA 2: TENDÊNCIAS SUAVIZADAS (FILTRO EWMA)
st.markdown("### 📉 Telemetria de Inércia Corporal")
c_met1, c_met2, c_met3, c_met4 = st.columns(4)

if not df_merged.empty:
    c_met1.metric("⚖️ Peso Tendência (EWMA)", f"{atual['peso_ewma']:.2f} kg", f"{d_peso*1000:+.0f} g (48h)")
    c_met2.metric("📐 Cintura Tendência", f"{atual['cintura_ewma']:.1f} cm" if pd.notnull(atual['cintura_ewma']) else "N/A", f"{d_cintura:+.1f} cm")
    c_met3.metric("🧬 Gordura (Weltman)", f"{atual['%G_weltman']:.1f} %" if pd.notnull(atual['%G_weltman']) else "N/A")
    c_met4.metric("💪 Massa Magra Ativa", f"{atual['massa_magra']:.1f} kg" if pd.notnull(atual['massa_magra']) else "N/A")

    # Gráficos Limpos Espelhados
    fig_trends = make_subplots(rows=1, cols=2, subplot_titles=("Trajetória de Peso (EWMA)", "Evolução Antropométrica (Cintura)"))
    fig_trends.add_trace(go.Scatter(x=df_merged['data'], y=df_merged['peso_ewma'], name="Peso EWMA", line=dict(color='#ef4444', width=4)), row=1, col=1)
    if not df_merged['cintura_ewma'].isna().all():
        fig_trends.add_trace(go.Scatter(x=df_merged['data'], y=df_merged['cintura_ewma'], name="Cintura EWMA", line=dict(color='#10b981', width=4)), row=1, col=2)
    fig_trends.update_layout(height=260, template="plotly_white", showlegend=False, margin=dict(l=10,r=10,t=30,b=10))
    st.plotly_chart(fig_trends, use_container_width=True)

st.divider()

# 🥉 CAMADA 3: NUTRIÇÃO OPERACIONAL ACIONÁVEL
st.markdown("### 🍽️ Abastecimento e Cota Energética Diária")
c_nut_l, c_nut_r = st.columns([1, 2])

with c_nut_l:
    k_hoje = df_hoje_c.iloc[0]['k'] if not df_hoje_c.empty and pd.notnull(df_hoje_c.iloc[0]['k']) else 0
    p_hoje = df_hoje_c.iloc[0]['p'] if not df_hoje_c.empty and pd.notnull(df_hoje_c.iloc[0]['p']) else 0
    c_hoje = df_hoje_c.iloc[0]['c'] if not df_hoje_c.empty and pd.notnull(df_hoje_c.iloc[0]['c']) else 0
    g_hoje = df_hoje_c.iloc[0]['g'] if not df_hoje_c.empty and pd.notnull(df_hoje_c.iloc[0]['g']) else 0
    
    rest_k = meta_kcal - k_hoje
    st.metric("🔥 Saldo Calórico Restante", f"{int(rest_k)} kcal", delta=f"Cota: {meta_kcal}", delta_color="normal" if rest_k >= 0 else "inverse")

with c_nut_r:
    # Renderização Compacta e Sem Texto Excessivo dos Macros
    m_p_status = "🟢 ALVO SEGUIDO" if p_hoje >= meta_prot else f"🟡 FALTA {int(meta_prot - p_hoje)}g"
    m_c_status = "🔴 LIMITE CRÍTICO" if c_hoje >= meta_carb - 15 else "🟢 DENTRO DO BUDGET"
    m_g_status = "🔴 LIMITE CRÍTICO" if g_hoje >= meta_gord - 10 else "🟢 DENTRO DO BUDGET"
    
    st.markdown(f"🥩 **Proteínas Ingeridas:** {int(p_hoje)}g / {meta_prot}g ➔ **{m_p_status}**")
    st.markdown(f"🍞 **Carboidratos Ingeridos:** {int(c_hoje)}g / {meta_carb}g ➔ **{m_c_status}**")
    st.markdown(f"🥑 **Gorduras Ingeridas:** {int(g_hoje)}g / {meta_gord}g ➔ **{m_g_status}**")

st.divider()

# 🧠 CAMADA 4: CONTROLADOR ANALÍTICO DE PREVISÃO (PID RADAR)
st.markdown("### 🤖 Orientação de Trajetória (Inércia PID)")

if not df_peso.empty and not df_merged.empty:
    df_base_pid = df_peso[df_peso['data'] >= DATA_INICIO].sort_values('data')
    if not df_base_pid.empty:
        peso_start_pid = float(df_base_pid.iloc[0]['peso_kg'])
        dias_passados = (hoje - DATA_INICIO).days
        sp_hoje = peso_start_pid - (dias_passados * (float(p['ritmo_semanal']) / 7))
        pv_hoje = atual['peso_ewma']
        erro_kg = pv_hoje - sp_hoje
        
        col_p1, col_p2, col_p3 = st.columns(3)
        col_p1.metric("🎯 Rampa Teórica (Setpoint)", f"{sp_hoje:.2f} kg")
        col_p2.metric("📊 Inércia Real (EWMA)", f"{pv_hoje:.2f} kg")
        
        if erro_kg < 0:
            col_p3.metric("🏆 Status", f"{erro_kg*1000:+.0f} g", delta_color="normal")
            st.markdown("💡 **Orientação:** Sistema operando abaixo da rampa de peso projetada. Manter ingestão calórica em modo cruzeiro.")
        else:
            col_p3.metric("⚠️ Desvio", f"{erro_kg*1000:+.0f} g", delta_color="inverse")
            ajuste = -(erro_kg * 1000)
            kcal_recalc = max(1000, min(meta_kcal + ajuste, atual['get_total']))
            st.markdown(f"💡 **Sugestão Matemática:** Para reverter o desvio e compensar a inércia hídrica/adiposa, o teto sugerido é de **{int(kcal_recalc)} kcal**.")

st.caption("Leo Tracker Command Center v13.0 | Do Dado Bruto à Decisão Fisiológica")
