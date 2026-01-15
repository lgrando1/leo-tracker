import streamlit as st
import pandas as pd
import psycopg2
from datetime import datetime, timedelta
import pytz
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import math

# 1. CONFIGURAÇÃO VISUAL
st.set_page_config(page_title="Leo's Nutrition Dash", page_icon="🦁", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
    <style>
    #MainMenu {visibility: hidden;} footer {visibility: hidden;} header {visibility: hidden;}
    div[data-testid="stMetric"] { background-color: #f0f2f6; padding: 10px; border-radius: 10px; border: 1px solid #e0e0e0; }
    @media (prefers-color-scheme: dark) { div[data-testid="stMetric"] { background-color: #262730; border: 1px solid #464b5c; } }
    </style>
    """, unsafe_allow_html=True)

# --- CONEXÃO ---
@st.cache_resource(ttl=300)
def get_connection():
    return psycopg2.connect(st.secrets["DATABASE_URL"])

def run_query(query, params=None, is_select=True):
    conn = None
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute("SET timezone TO 'America/Sao_Paulo';")
            if is_select: 
                df = pd.read_sql(query, conn, params=params)
                for col in ['data', 'log_date', 'measurement_time']:
                    if col in df.columns:
                        try: df[col] = pd.to_datetime(df[col])
                        except: pass 
                return df
            else:
                cur.execute(query, params)
                conn.commit()
                return True
    except Exception as e:
        if conn: conn.rollback()
        st.error(f"Erro DB: {e}")
        return pd.DataFrame() if is_select else False

# --- TRAVA DE SEGURANÇA ---
if st.query_params.get("token") != st.secrets.get("DASH_ACCESS_TOKEN"):
    st.error("🔒 Acesso Negado."); st.stop()

# --- 1. BUSCA DE DADOS (ORDEM CRÍTICA) ---
df_perfil = run_query("SELECT * FROM public.perfil WHERE id = 1")
df_peso_last = run_query("SELECT peso_kg FROM public.peso ORDER BY data DESC, id DESC LIMIT 1")
df_medidas = run_query("SELECT * FROM public.body_measurements ORDER BY log_date ASC")
df_bp = run_query("SELECT * FROM public.blood_pressure ORDER BY measurement_time ASC")

# Valores Padrão / Perfil
if not df_perfil.empty:
    p = df_perfil.iloc[0]
else:
    p = {'genero': 'Masculino', 'idade': 41, 'altura_cm': 178, 'atividade': 'Sedentário (1.2)', 
         'objetivo': 'Perder Peso (Moderado)', 'ritmo_semanal': 0.8, 'meta_kcal': 1650, 
         'meta_proteina': 130, 'meta_carbo': 150, 'meta_gordura': 59, 'meta_peso_alvo': 120.0}

PESO_ATUAL = float(df_peso_last.iloc[0]['peso_kg']) if not df_peso_last.empty else 141.9
ALTURA_ATUAL = int(p.get('altura_cm', 178))
META_AGUA = round((PESO_ATUAL * 35) / 1000, 1) # Cálculo: 35ml por kg

# --- 2. TRATAMENTO DE VARIÁVEIS DE PRESSÃO ---
last_sys, last_dia = "--", "--"
if not df_bp.empty:
    last_bp = df_bp.iloc[-1]
    last_sys, last_dia = last_bp['systolic'], last_bp['diastolic']

# --- 3. DADOS TEMPORAIS ---
hoje = datetime.now(pytz.timezone('America/Sao_Paulo')).date()
DATA_INICIO = pd.to_datetime("2025-12-30").date()

df_hoje = run_query("SELECT * FROM public.consumo WHERE data = %s", (hoje,))
df_hist = run_query("""
    SELECT data, SUM(kcal) as tkcal, SUM(proteina) as tprot, SUM(carbo) as tcarb, 
           SUM(gordura) as tgord, SUM(quantidade) as tqtd
    FROM public.consumo WHERE data >= %s GROUP BY data ORDER BY data ASC
""", (DATA_INICIO,))
df_peso = run_query("SELECT * FROM public.peso ORDER BY data ASC")

# --- INTERFACE INICIAL ---
st.markdown(f"# 🦁 Leo's Performance | {hoje.strftime('%d/%m')}")

# KPI PRINCIPAIS
k_act, p_act = (df_hoje['kcal'].sum(), df_hoje['proteina'].sum()) if not df_hoje.empty else (0,0)

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("🔥 Calorias", f"{int(k_act)}", f"Meta: {p['meta_kcal']}")
c2.metric("🥩 Proteína", f"{int(p_act)}g", f"Meta: {p['meta_proteina']}g")
c3.metric("💧 Água", f"{META_AGUA}L", "Meta Mínima")
c4.metric("❤️ Pressão", f"{last_sys}x{last_dia}", "Normal" if isinstance(last_sys, int) and last_sys < 130 else "Atenção")
c5.metric("⚖️ Peso", f"{PESO_ATUAL}kg", f"Alvo: {p['meta_peso_alvo']}")

st.divider()

# ==========================================
# SEÇÃO 1: ANALYTICS AVANÇADO (BIO-CALIBRADO)
# ==========================================
st.subheader("📉 Inteligência de Perda de Peso")

col_a1, col_a2 = st.columns([2, 1])

with col_a1:
    st.markdown("##### Média Semanal vs Peso Diário")
    if not df_peso.empty:
        df_peso['media_movel'] = df_peso['peso_kg'].rolling(window=7, min_periods=1).mean()
        fig_trend = go.Figure()
        fig_trend.add_trace(go.Scatter(x=df_peso['data'], y=df_peso['peso_kg'], mode='markers', name='Pesagem Diária', marker=dict(color='gray', opacity=0.4, size=6)))
        fig_trend.add_trace(go.Scatter(x=df_peso['data'], y=df_peso['media_movel'], mode='lines', name='Tendência Real (7d)', line=dict(color='#2ecc71', width=4)))
        fig_trend.update_layout(height=300, margin=dict(l=10,r=10,t=20,b=10), hovermode="x unified", legend=dict(orientation="h", y=1.1))
        st.plotly_chart(fig_trend, use_container_width=True)

with col_a2:
    st.markdown("##### 🏦 Banco de Gordura (Real)")
    if not df_hist.empty:
        df_merged = pd.merge_asof(df_hist.sort_values('data'), df_peso.sort_values('data'), on='data', direction='backward')
        df_merged['peso_kg'] = df_merged['peso_kg'].fillna(146.0)
        
        # Cálculo calibrado pela sua bioimpedância (Fator 1.09)
        idade = int(p.get('idade', 41))
        altura = int(p.get('altura_cm', 178))
        df_merged['get_dia'] = ((10 * df_merged['peso_kg']) + (6.25 * altura) - (5 * idade) + 5) * 1.09 * 1.2
        
        deficit_total = (df_merged['get_dia'] - df_merged['tkcal']).sum()
        kg_gordura = deficit_total / 7700
        
        st.metric("Déficit Acumulado", f"{int(deficit_total)} kcal")
        st.metric("Gordura Eliminada", f"{kg_gordura:.2f} kg", delta=f"{(kg_gordura*1000/15):.0f}g /dia")
        st.caption(f"ℹ️ Gasto diário estimado: ~{int(df_merged['get_dia'].mean())} kcal")

st.divider()

# ==========================================
# SEÇÃO 2: PROGRESSO DE PESO
# ==========================================
st.subheader("🎯 Planejamento vs Realidade")

peso_inicial = 146.0
ritmo_semanal = float(p.get('ritmo_semanal', 0.8))
peso_perdido = peso_inicial - PESO_ATUAL
dias_decorridos = (hoje - DATA_INICIO).days
data_esperada = DATA_INICIO + timedelta(days=int(peso_perdido / (ritmo_semanal/7))) if ritmo_semanal > 0 else hoje
diferenca_dias = (hoje - data_esperada).days

col_p1, col_p2 = st.columns([1, 2])
with col_p1:
    if diferenca_dias < 0: st.success(f"🚀 **ADIANTADO: {abs(diferenca_dias)} dias**")
    elif diferenca_dias > 0: st.warning(f"⚠️ **ATRASADO: {diferenca_dias} dias**")
    else: st.info("🎯 **NO PLANO**")
    st.metric("Perda Total", f"{peso_perdido:.1f} kg")

with col_p2:
    if not df_peso.empty:
        d_range = (hoje + timedelta(days=30) - DATA_INICIO).days
        dates_m = [DATA_INICIO + timedelta(days=i) for i in range(d_range)]
        vals_m = [max(120.0, peso_inicial - (i * (ritmo_semanal/7))) for i in range(len(dates_m))]
        fig_p = go.Figure()
        fig_p.add_trace(go.Scatter(x=dates_m, y=vals_m, name="Meta", line=dict(color='gray', dash='dot')))
        fig_p.add_trace(go.Scatter(x=df_peso['data'], y=df_peso['peso_kg'], name="Real", line=dict(color='#1f77b4', width=4)))
        fig_p.update_layout(height=300, margin=dict(l=10,r=10,t=10,b=10))
        st.plotly_chart(fig_p, use_container_width=True)

st.divider()

# ==========================================
# SEÇÃO 3: SAÚDE & COMPOSIÇÃO
# ==========================================
st.subheader("🧬 Saúde & Composição Corporal")

if not df_medidas.empty:
    l_m = df_medidas.iloc[-1]
    rcq = l_m['waist_cm'] / l_m['hip_cm'] if l_m['hip_cm'] > 0 else 0
    
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("🐷 Gordura (BF)", f"{l_m['body_fat_est']:.1f}%")
    m2.metric("📏 Cintura", f"{l_m['waist_cm']} cm")
    m3.metric("🫀 Risco (RCQ)", f"{rcq:.2f}", "Moderado" if rcq > 0.9 else "Baixo")
    m4.metric("💓 Pulsação", f"{last_pulse if 'last_pulse' in locals() else '--'} bpm")

col_left, col_right = st.columns(2)
with col_left:
    st.markdown("**📉 Evolução de Gordura (%)**")
    fig_bf = go.Figure(go.Scatter(x=df_medidas['log_date'], y=df_medidas['body_fat_est'], mode='lines+markers', line=dict(color='#e67e22')))
    fig_bf.update_layout(height=250, margin=dict(l=10,r=10,t=20,b=10))
    st.plotly_chart(fig_bf, use_container_width=True)

with col_right:
    st.markdown("**🫀 Pressão Arterial**")
    if not df_bp.empty:
        fig_bp = go.Figure()
        fig_bp.add_trace(go.Scatter(x=df_bp['measurement_time'], y=df_bp['systolic'], name="Sist.", line=dict(color='red')))
        fig_bp.add_trace(go.Scatter(x=df_bp['measurement_time'], y=df_bp['diastolic'], name="Diast.", line=dict(color='blue')))
        fig_bp.update_layout(height=250, margin=dict(l=10,r=10,t=20,b=10))
        st.plotly_chart(fig_bp, use_container_width=True)

st.divider()

# ==========================================
# SEÇÃO 4: NUTRIÇÃO
# ==========================================
st.subheader("🍽️ Comportamento Alimentar")

if not df_hist.empty:
    df_macros = df_hist.copy()
    df_macros['tot'] = (df_macros['tprot']*4 + df_macros['tcarb']*4 + df_macros['tgord']*9)
    df_macros['p_p'] = (df_macros['tprot']*4 / df_macros['tot']) * 100
    df_macros['p_c'] = (df_macros['tcarb']*4 / df_macros['tot']) * 100
    df_macros['p_g'] = (df_macros['tgord']*9 / df_macros['tot']) * 100

    c_n1, c_n2 = st.columns([2, 1])
    with c_n1:
        fig_stack = go.Figure()
        fig_stack.add_trace(go.Bar(x=df_macros['data'], y=df_macros['p_p'], name='Proteína', marker_color='#3366CC'))
        fig_stack.add_trace(go.Bar(x=df_macros['data'], y=df_macros['p_g'], name='Gordura', marker_color='#DC3912'))
        fig_stack.add_trace(go.Bar(x=df_macros['data'], y=df_macros['p_c'], name='Carbo', marker_color='#FF9900'))
        fig_stack.update_layout(barmode='stack', height=350, margin=dict(l=10,r=10,t=20,b=10), yaxis=dict(range=[0, 100]))
        st.plotly_chart(fig_stack, use_container_width=True)

    with c_n2:
        if k_act > 0:
            fig_pie = go.Figure(data=[go.Pie(labels=['P','C','G'], values=[p_act*4, (k_act-p_act*4-g_act*9), g_act*9], hole=.4)])
            fig_pie.update_layout(height=350, showlegend=False, margin=dict(l=10,r=10,t=20,b=10))
            st.plotly_chart(fig_pie, use_container_width=True)

st.caption("Leo Tracker Dash v2.2 | Bio-Calibrado & Water-Aware")
