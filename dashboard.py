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
# 1. CONFIGURAÇÃO VISUAL (LAYOUT CLEAN DE DECISÃO)
# ============================================================================
st.set_page_config(page_title="Leo's Fisiology Engine", page_icon="🦁", layout="wide", initial_sidebar_state="collapsed")

st.markdown("""
    <style>
    #MainMenu {visibility: hidden;} footer {visibility: hidden;} header {visibility: hidden;}
    .state-card { background-color: #1e293b; padding: 20px; border-radius: 16px; border: 1px solid #334155; margin-bottom: 20px; }
    .insight-box { background-color: #0f172a; padding: 15px; border-radius: 12px; border-left: 5px solid #3b82f6; margin-bottom: 10px; }
    div[data-testid="stMetric"] { background-color: #f0f2f6; padding: 15px; border-radius: 12px; border: 1px solid #e0e0e0; }
    @media (prefers-color-scheme: dark) { div[data-testid="stMetric"] { background-color: #1e293b; border: 1px solid #334155; } }
    </style>
    """, unsafe_allow_html=True)

# ============================================================================
# 2. CONEXÃO E ETL BLINDADO
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

# --- EXTRAÇÃO BASE ---
hoje = datetime.now(pytz.timezone('America/Sao_Paulo')).date()
DATA_INICIO = pd.to_datetime("2025-12-30").date()

df_perfil = run_query("SELECT * FROM public.perfil WHERE id = 1")
df_peso = run_query("SELECT * FROM public.peso ORDER BY data ASC")
df_medidas = run_query("SELECT * FROM public.body_measurements ORDER BY log_date ASC")
df_bp = run_query("SELECT * FROM public.blood_pressure ORDER BY measurement_time ASC")
df_hist = run_query("SELECT data, SUM(kcal) as tkcal, SUM(proteina) as tprot, SUM(carbo) as tcarb, SUM(gordura) as tgord FROM public.consumo WHERE data >= :d GROUP BY data ORDER BY data ASC", {"d": DATA_INICIO})
df_treino = run_query("SELECT data, SUM(duracao_min) as t_min, SUM(passos_trabalho) as t_passos_trabalho, SUM(calorias) as t_cal_out FROM public.exercicios WHERE data >= :d GROUP BY data ORDER BY data ASC", {"d": DATA_INICIO})
df_hidra = run_query("SELECT data, SUM(agua_ml) as tagua FROM public.hidratacao WHERE data >= :d GROUP BY data ORDER BY data ASC", {"d": DATA_INICIO})

# Configuração de Metas Estritamente Atualizadas
p = df_perfil.iloc[0] if not df_perfil.empty else {'meta_kcal': 1415, 'meta_proteina': 104, 'meta_carbo': 105, 'meta_gordura': 71, 'meta_peso_alvo': 120.0, 'fator_atividade': 1.2}
meta_kcal, meta_prot, meta_carb, meta_gord = int(p['meta_kcal']), int(p['meta_proteina']), int(p['meta_carbo']), int(p['meta_gordura'])

# --- CONSOLIDAÇÃO DA FEATURE STORE ---
if not df_hist.empty and not df_peso.empty:
    df_peso_u = df_peso.drop_duplicates(subset=['data'], keep='last')
    df_merged = pd.merge(df_hist, df_peso_u[['data', 'peso_kg']], on='data', how='left').ffill()
    df_merged['peso_kg'] = df_merged['peso_kg'].bfill().fillna(115.0)
    
    # Merge complementares
    for df_tmp, col_list in [(df_treino, ['t_min', 't_passos_trabalho', 't_cal_out']), (df_hidra, ['tagua'])]:
        if not df_tmp.empty:
            df_merged = pd.merge(df_merged, df_tmp.groupby('data')[col_list].sum().reset_index(), on='data', how='left').fillna(0)
            
    if not df_medidas.empty:
        df_merged = pd.merge(df_merged, df_medidas.groupby('data')[['waist_cm']].last().reset_index(), on='data', how='left').ffill()
    else:
        df_merged['waist_cm'] = np.nan

    # 📈 SINAL VERDADEIRO: EWMA DE 7 DIAS (Isolando Ruído Hídrico)
    df_merged['peso_ewma'] = df_merged['peso_kg'].ewm(span=7, adjust=False).mean()
    df_merged['cintura_ewma'] = df_merged['waist_cm'].ewm(span=7, adjust=False).mean().ffill()
    
    # Termodinâmica Humana
    df_merged['get_basal'] = ((10 * df_merged['peso_kg']) + (6.25 * 178) - (5 * 41) + 5) * float(p['fator_atividade'])
    df_merged['get_total'] = df_merged['get_basal'] + df_merged['t_cal_out']
    df_merged['deficit_real'] = df_merged['get_total'] - df_merged['tkcal']

    # --- MATEMÁTICA DE WELTMAN INCORPORADA ---
    df_merged['%G_weltman'] = (0.31457 * df_merged['cintura_ewma']) - (0.10969 * df_merged['peso_ewma']) + 10.834
    df_merged['massa_magra'] = df_merged['peso_ewma'] * (1 - (df_merged['%G_weltman'] / 100))

# ============================================================================
# 3. INTERPRETADOR FISIOLÓGICO (MOTOR DE INSIGHTS CAUSA-E-EFEITO)
# ============================================================================
if not df_merged.empty and len(df_merged) >= 3:
    atual, anterior = df_merged.iloc[-1], df_merged.iloc[-2]
    
    # 🧪 Cálculo de Tendências Curtas (Reta de Mudança)
    delta_peso_ewma = atual['peso_ewma'] - anterior['peso_ewma']
    delta_cintura_ewma = (atual['cintura_ewma'] - anterior['cintura_ewma']) if pd.notnull(atual['cintura_ewma']) else 0
    
    # Heurísticas de Estado Fisiológico Crítico
    insights = []
    if delta_cintura_ewma < -0.05 and delta_peso_ewma >= 0:
        estado_cor, estado_txt = "🟢", "RECOMPOSIÇÃO CORPORAL ATIVA"
        insights.append("🔥 **Sinal de Ouro:** Sua cintura está caindo enquanto o peso estabilizou ou subiu. Você está queimando gordura visceral e retendo glicogênio muscular. Ignore a balança bruta!")
    elif delta_cintura_ewma > 0.05 and delta_peso_ewma <= 0:
        estado_cor, estado_txt = "🔴", "PERDA DE MASSA MAGRA/CATABOLISMO"
        insights.append("⚠️ **Alerta Estrutural:** O peso caiu, mas a tendência da cintura subiu. Risco alto de perda de tecido ativo. Aumente o aporte proteico IMEDIATAMENTE.")
    elif delta_peso_ewma > 0.1 and atual['t_passos_trabalho'] > anterior['t_passos_trabalho']:
        estado_cor, estado_txt = "🟡", "RETENÇÃO HÍDRICA POR INFLAMAÇÃO"
        insights.append("💧 **Inércia de Carga:** Volume de passos/treino alto gerou microlesões normais. O peso subiu por acúmulo de água intracelular para reparo. Tecido adiposo intacto.")
    else:
        estado_cor, estado_txt = "🟢", "QUEIMA ADIPOSA CONSTANTE"
        insights.append("📉 **Voo de Cruzeiro:** Déficit calórico sendo perfeitamente traduzido em redução de tecido gorduroso estrutural.")

    if atual['tagua'] < (atual['peso_kg'] * 35):
        insights.append("🚨 **Déficit de Fluidos:** Sua hidratação acumulada ficou abaixo do target metabólico. Isso pode travar a filtragem renal e mascarar a perda de peso.")
else:
    estado_cor, estado_txt, insights = "⚪", "COLETANDO DADOS", ["Aguardando histórico para ativar motor fisiológico."]

# ============================================================================
# 4. INTERFACE GRÁFICA TRANSFORMATIVA (A CAMADA INTELIGENTE)
# ============================================================================
st.title("🦁 Leo-Tracker Pro — Fisiologia Avançada")

# 🥇 TOPO: ESTADO FISIOLÓGICO E INSIGHTS DIRETOS
st.markdown(f"""
    <div class="state-card">
        <h2 style='margin:0; color:#f8fafc;'>{estado_cor} Estado Atual: {estado_txt}</h2>
        <p style='color:#94a3b8; margin-top:5px; margin-bottom:15px;'>Análise de acoplamento entre Termodinâmica, Antropometria e Fluidos das últimas 48h.</p>
    </div>
    """, unsafe_allow_html=True)

col_ins_l, col_ins_r = st.columns([2, 1])
with col_ins_l:
    st.markdown("### 🧠 Diagnósticos do Sistema")
    for ins in insights:
        st.markdown(f"<div class='insight-box'>{ins}</div>", unsafe_allow_html=True)
        
with col_ins_r:
    st.markdown("### 🍽️ Nutrição Operacional (Restante)")
    df_hoje_c = run_query("SELECT SUM(kcal) as k, SUM(proteina) as p, SUM(carbo) as c, SUM(gordura) as g FROM public.consumo WHERE data = :d", {"d": hoje})
    k_hoje = df_hoje_c.iloc[0]['k'] if not df_hoje_c.empty and pd.notnull(df_hoje_c.iloc[0]['k']) else 0
    p_hoje = df_hoje_c.iloc[0]['p'] if not df_hoje_c.empty and pd.notnull(df_hoje_c.iloc[0]['p']) else 0
    c_hoje = df_hoje_c.iloc[0]['c'] if not df_hoje_c.empty and pd.notnull(df_hoje_c.iloc[0]['c']) else 0
    g_hoje = df_hoje_c.iloc[0]['g'] if not df_hoje_c.empty and pd.notnull(df_hoje_c.iloc[0]['g']) else 0
    
    rest_k = meta_kcal - k_hoje
    st.metric("🔥 Cota Calórica Restante", f"{int(rest_k)} kcal", delta=f"Consumido: {int(k_hoje)}", delta_color="inverse" if rest_k < 0 else "normal")
    
    # Status Dinâmico de Macros
    st.markdown(f"🥩 **Proteína:** {int(p_hoje)}g / {meta_prot}g " + ("🟢 OK" if p_hoje >= meta_prot else "🟡 Faltando Carboidrato Ativo"))
    st.markdown(f"🍞 **Carbo:** {int(c_hoje)}g / {meta_carb}g " + ("🔴 Limite Próximo" if c_hoje >= meta_carb - 20 else "🟢 Sobrando"))
    st.markdown(f"🥑 **Gordura:** {int(g_hoje)}g / {meta_gord}g " + ("🔴 Limite Próximo" if g_hoje >= meta_gord - 10 else "🟢 Dentro"))

st.divider()

# 🥈 SEGUNDA LINHA: SINAIS SUAVIZADOS (TENDÊNCIAS PURAS)
st.markdown("### 📉 Tendências Biométricas Limpas (Filtro de Ruído Hídrico)")
c_met1, c_met2, c_met3, c_met4 = st.columns(4)

if not df_merged.empty:
    c_met1.metric("⚖️ Peso Tendência (EWMA)", f"{atual['peso_ewma']:.2f} kg", f"{delta_peso_ewma*1000:+.0f} g (7d)")
    c_met2.metric("📐 Cintura Tendência", f"{atual['cintura_ewma']:.1f} cm" if pd.notnull(atual['cintura_ewma']) else "N/A", f"{delta_cintura_ewma:+.1f} cm")
    c_met3.metric("🧬 Gordura (Weltman)", f"{atual['%G_weltman']:.1f} %" if pd.notnull(atual['%G_weltman']) else "N/A")
    c_met4.metric("💪 Massa Magra Ativa", f"{atual['massa_magra']:.1f} kg" if pd.notnull(atual['massa_magra']) else "N/A")

# Gráficos Espelhados de Evolução de Sinal
if not df_merged.empty:
    fig_trends = make_subplots(rows=1, cols=2, subplot_titles=("Sinal Real de Peso (EWMA)", "Redução de Perímetros (Cintura)"))
    fig_trends.add_trace(go.Scatter(x=df_merged['data'], y=df_merged['peso_ewma'], name="Peso Real", line=dict(color='#ef4444', width=4)), row=1, col=1)
    if not df_merged['cintura_ewma'].isna().all():
        fig_trends.add_trace(go.Scatter(x=df_merged['data'], y=df_merged['cintura_ewma'], name="Cintura", line=dict(color='#10b981', width=4)), row=1, col=2)
    fig_trends.update_layout(height=300, template="plotly_white", showlegend=False, margin=dict(l=10,r=10,t=30,b=10))
    st.plotly_chart(fig_trends, use_container_width=True)

st.divider()

# 🥉 TERCEIRA LINHA: DINÂMICA CALÓRICA AUTOMÁTICA (ROBÔ PID)
st.markdown("### 🤖 Controlador Preditivo Calórico (PID)")

if not df_peso.empty and not df_merged.empty:
    df_base_pid = df_peso[df_peso['data'] >= DATA_INICIO].sort_values('data')
    if not df_base_pid.empty:
        peso_start_pid = float(df_base_pid.iloc[0]['peso_kg'])
        dias_passados = (hoje - DATA_INICIO).days
        sp_hoje = peso_start_pid - (dias_passados * (float(p['ritmo_semanal']) / 7))
        pv_hoje = atual['peso_ewma']
        erro_kg = pv_hoje - sp_hoje
        
        col_p1, col_p2, col_p3 = st.columns(3)
        col_p1.metric("🎯 Setpoint Calculado", f"{sp_hoje:.2f} kg")
        col_p2.metric("📊 Realidade Corporal (EWMA)", f"{pv_hoje:.2f} kg")
        
        if erro_kg < 0:
            col_p3.metric("🏆 Status da Rampa", f"{erro_kg*1000:+.0f} g", delta_color="normal")
            st.success(f"🔥 **SISTEMA EM ACELERAÇÃO:** Você quebrou a rampa e está {abs(erro_kg):.2f}kg à frente do objetivo. Meta base travada em {meta_kcal} kcal.")
        else:
            col_p3.metric("⚠️ Desvio de Trajetória", f"{erro_kg*1000:+.0f} g", delta_color="inverse")
            ajuste = -(erro_kg * 1000)
            kcal_recalc = max(1000, min(meta_kcal + ajuste, atual['get_total']))
            st.error(f"🚨 **AÇÃO CORRETIVA PID:** Inércia metabólica pesando. Cota calórica comprimida para **{int(kcal_recalc)} kcal** nas próximas 24h.")

st.caption("Leo Tracker Command Center v13.0 | Do Dado Bruto à Decisão Fisiológica")
