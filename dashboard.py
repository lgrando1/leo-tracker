import streamlit as st
import pandas as pd
import psycopg2
from datetime import datetime, timedelta
import pytz
import plotly.graph_objects as go
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

# --- CONEXÃO COM BLINDAGEM ---
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
                        except Exception: pass 
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

# --- BUSCA DE DADOS ---
df_perfil = run_query("SELECT * FROM public.perfil WHERE id = 1")
df_peso_last = run_query("SELECT peso_kg FROM public.peso ORDER BY data DESC, id DESC LIMIT 1")
df_medidas = run_query("SELECT * FROM public.body_measurements ORDER BY log_date ASC")
df_bp = run_query("SELECT * FROM public.blood_pressure ORDER BY measurement_time ASC")

if not df_perfil.empty:
    p = df_perfil.iloc[0]
else:
    p = {'genero': 'Masculino', 'idade': 41, 'altura_cm': 178, 'atividade': 'Sedentário (1.2)', 
         'objetivo': 'Perder Peso (Moderado)', 'ritmo_semanal': 0.8, 'meta_kcal': 1650, 
         'meta_proteina': 130, 'meta_carbo': 150, 'meta_gordura': 59, 'meta_peso_alvo': 120.0}

PESO_ATUAL = float(df_peso_last.iloc[0]['peso_kg']) if not df_peso_last.empty else 141.9
ALTURA_ATUAL = int(p.get('altura_cm', 178))

# --- SIDEBAR ---
st.sidebar.header("🧮 Perfil Biométrico")
st.sidebar.info(f"🧬 **Metas:**\n🔥 {p['meta_kcal']} kcal | 🥩 {p['meta_proteina']}g\n🍞 {p.get('meta_carbo', 150)}g | 🥑 {p.get('meta_gordura', 59)}g")

# --- DADOS PRINCIPAIS ---
hoje = datetime.now(pytz.timezone('America/Sao_Paulo')).date()
DATA_INICIO = pd.to_datetime("2025-12-30").date()

df_hoje = run_query("SELECT * FROM public.consumo WHERE data = %s", (hoje,))
df_hist = run_query("SELECT data, SUM(kcal) as tkcal, SUM(proteina) as tprot, SUM(carbo) as tcarb, SUM(gordura) as tgord FROM public.consumo WHERE data >= %s GROUP BY data ORDER BY data ASC", (hoje - timedelta(days=30),))
df_peso = run_query("SELECT * FROM public.peso ORDER BY data ASC")

st.markdown(f"# 🦁 Leo's Performance | {hoje.strftime('%d/%m')}")

# KPI PRINCIPAIS
k_act, p_act = (df_hoje['kcal'].sum(), df_hoje['proteina'].sum()) if not df_hoje.empty else (0,0)
c1, c2, c3, c4 = st.columns(4)
c1.metric("🔥 Calorias", f"{int(k_act)}", f"Meta: {p['meta_kcal']}")
c2.metric("🥩 Proteína", f"{int(p_act)}g", f"Meta: {p['meta_proteina']}g")

# KPI Pressão
last_sys, last_dia, last_pulse = "--", "--", "--"
if not df_bp.empty:
    last_bp = df_bp.iloc[-1]
    last_sys, last_dia, last_pulse = last_bp['systolic'], last_bp['diastolic'], last_bp['pulse']

c3.metric("❤️ Pressão", f"{last_sys} x {last_dia}", "Normal" if isinstance(last_sys, int) and last_sys < 130 else "Atenção")
c4.metric("💓 Pulsação", f"{last_pulse} bpm")

st.divider()

# --- NOVA SEÇÃO: COMPOSIÇÃO CORPORAL ---
st.subheader("🧬 Análise Corporal Avançada")

if not df_medidas.empty:
    last_m = df_medidas.iloc[-1]
    
    # Cálculos Avançados
    bf_atual = last_m['body_fat_est']
    cintura = last_m['waist_cm']
    quadril = last_m['hip_cm']
    pescoco = last_m['neck_cm']
    
    # Relação Cintura-Quadril (RCQ)
    rcq = cintura / quadril if quadril > 0 else 0
    risco_rcq = "Baixo" if rcq < 0.90 else ("Moderado" if rcq < 0.95 else "Alto Risco")
    
    mc1, mc2, mc3, mc4 = st.columns(4)
    mc1.metric("⚖️ Peso Atual", f"{last_m.get('weight_kg', PESO_ATUAL)} kg")
    mc2.metric("🐷 Gordura (BF)", f"{bf_atual:.1f}%", "-1.2% (Est)" if len(df_medidas) > 1 else None)
    mc3.metric("📏 Cintura", f"{cintura} cm")
    mc4.metric("🫀 Risco Cardíaco (RCQ)", f"{rcq:.2f}", risco_rcq, delta_color="inverse")
    
    # GRÁFICOS LADO A LADO
    gc1, gc2 = st.columns(2)
    
    with gc1:
        st.markdown("**📉 Queda de Gordura Corporal (%)**")
        fig_bf = go.Figure()
        fig_bf.add_trace(go.Scatter(x=df_medidas['log_date'], y=df_medidas['body_fat_est'], mode='lines+markers', name='% Gordura', line=dict(color='#e67e22', width=3)))
        fig_bf.update_layout(height=250, margin=dict(l=10,r=10,t=10,b=10))
        st.plotly_chart(fig_bf, use_container_width=True)

    with gc2:
        st.markdown("**📏 Evolução das Medidas (cm)**")
        fig_m = go.Figure()
        fig_m.add_trace(go.Scatter(x=df_medidas['log_date'], y=df_medidas['waist_cm'], name='Cintura', line=dict(color='red')))
        fig_m.add_trace(go.Scatter(x=df_medidas['log_date'], y=df_medidas['hip_cm'], name='Quadril', line=dict(color='blue')))
        fig_m.add_trace(go.Scatter(x=df_medidas['log_date'], y=df_medidas['neck_cm'], name='Pescoço', line=dict(color='green')))
        fig_m.update_layout(height=250, margin=dict(l=10,r=10,t=10,b=10))
        st.plotly_chart(fig_m, use_container_width=True)

else:
    st.info("⚠️ Registre suas medidas na aba 'Saúde & Corpo' do App Tracker para ver sua análise de gordura e risco cardíaco.")

st.divider()

# --- GRÁFICO DE PESO E META ---
st.subheader("⚖️ Rumo ao Peso Ideal")
if not df_peso.empty:
    p_inicial = 144.9
    d_total = (hoje + timedelta(days=60) - DATA_INICIO).days
    dates_m = [DATA_INICIO + timedelta(days=i) for i in range(d_total + 1)]
    vals_m = [max(float(p['meta_peso_alvo']), p_inicial - (i * (float(p['ritmo_semanal'])/7))) for i in range(len(dates_m))]
    
    fig_combo = go.Figure()
    fig_combo.add_trace(go.Scatter(x=dates_m, y=vals_m, name="Meta Planejada", mode='lines', line=dict(color='gray', dash='dot')))
    fig_combo.add_trace(go.Scatter(x=df_peso['data'], y=df_peso['peso_kg'], name="Peso Real", mode='lines+markers', line=dict(color='#1f77b4', width=4)))
    
    fig_combo.update_layout(height=350, margin=dict(l=10,r=10,t=20,b=10), hovermode="x unified")
    st.plotly_chart(fig_combo, use_container_width=True)

# --- GRÁFICOS DE PRESSÃO (RESTAURADO) ---
if not df_bp.empty:
    st.divider()
    st.subheader("🫀 Histórico de Pressão Arterial")
    fig_bp = go.Figure()
    fig_bp.add_hline(y=120, line_dash="dot", line_color="green", annotation_text="Ideal (120)")
    fig_bp.add_trace(go.Scatter(x=df_bp['measurement_time'], y=df_bp['systolic'], name="Alta", line=dict(color='red')))
    fig_bp.add_trace(go.Scatter(x=df_bp['measurement_time'], y=df_bp['diastolic'], name="Baixa", line=dict(color='blue'), fill='tonexty'))
    fig_bp.update_layout(height=250, margin=dict(l=10,r=10,t=20,b=10))
    st.plotly_chart(fig_bp, use_container_width=True)

st.divider()

# --- CONTROLE NUTRICIONAL ---
st.subheader("🍽️ Controle de Dieta")
if not df_hist.empty:
    c1, c2 = st.columns([2, 1])
    with c1:
        # Gráfico de Barras de Macros
        fig_macros = go.Figure()
        fig_macros.add_trace(go.Bar(x=df_hist['data'], y=df_hist['tprot'], name='Proteína', marker_color='#3366CC'))
        fig_macros.add_trace(go.Bar(x=df_hist['data'], y=df_hist['tcarb'], name='Carbo', marker_color='#FF9900'))
        fig_macros.add_trace(go.Bar(x=df_hist['data'], y=df_hist['tgord'], name='Gordura', marker_color='#DC3912'))
        fig_macros.update_layout(barmode='stack', title="Ingestão de Macros (g)", height=300, margin=dict(l=10,r=10,t=30,b=10))
        st.plotly_chart(fig_macros, use_container_width=True)
    
    with c2:
        # Pizza de Hoje
        if k_act > 0:
            c_act = df_hoje['carbo'].sum()
            g_act = df_hoje['gordura'].sum()
            fig_p = go.Figure(data=[go.Pie(labels=['Prot','Carb','Gord'], values=[p_act*4, c_act*4, g_act*9], hole=.4, marker=dict(colors=['#3366CC','#FF9900','#DC3912']))])
            fig_p.update_layout(title="Distribuição Hoje", height=300, margin=dict(l=10,r=10,t=30,b=10), showlegend=False)
            st.plotly_chart(fig_p, use_container_width=True)
        else:
            st.info("Registre sua alimentação hoje.")
