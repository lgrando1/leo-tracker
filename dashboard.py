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

# --- CONEXÃO COM BLINDAGEM DE ERRO (DATA/HORA) ---
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
                
                # --- CORREÇÃO DE DATA/HORA ---
                # Isso impede o erro "datetime.time is not convertible"
                for col in ['data', 'log_date', 'measurement_time']:
                    if col in df.columns:
                        try:
                            df[col] = pd.to_datetime(df[col])
                        except Exception:
                            pass 
                # -----------------------------
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
# Perfil, Peso, Medidas e AGORA PRESSÃO
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

# --- BARRA LATERAL (LEITURA) ---
st.sidebar.header("🧮 Perfil Biométrico")
st.sidebar.info(f"🧬 **Meta Atual:**\n🔥 {p['meta_kcal']} kcal | 🥩 {p['meta_proteina']}g\n🍞 {p.get('meta_carbo', 150)}g | 🥑 {p.get('meta_gordura', 59)}g")
st.sidebar.caption("Para editar metas, use o App Tracker.")

# --- DADOS PRINCIPAIS ---
hoje = datetime.now(pytz.timezone('America/Sao_Paulo')).date()
DATA_INICIO = pd.to_datetime("2025-12-30").date()

df_hoje = run_query("SELECT * FROM public.consumo WHERE data = %s", (hoje,))
df_hist = run_query("SELECT data, SUM(kcal) as tkcal, SUM(proteina) as tprot, SUM(carbo) as tcarb, SUM(gordura) as tgord FROM public.consumo WHERE data >= %s GROUP BY data ORDER BY data ASC", (hoje - timedelta(days=30),))
df_peso = run_query("SELECT * FROM public.peso ORDER BY data ASC")

st.markdown(f"# 🦁 Leo's Performance | {hoje.strftime('%d/%m')}")

# KPI: Macros Hoje
k_act, p_act = (df_hoje['kcal'].sum(), df_hoje['proteina'].sum()) if not df_hoje.empty else (0,0)
c1, c2, c3, c4 = st.columns(4)
c1.metric("🔥 Calorias", f"{int(k_act)}", f"Meta: {p['meta_kcal']}")
c2.metric("🥩 Proteína", f"{int(p_act)}g", f"Meta: {p['meta_proteina']}g")

# KPI: Pressão (NOVO)
last_sys, last_dia, last_pulse = "--", "--", "--"
delta_bp = ""
if not df_bp.empty:
    last_bp = df_bp.iloc[-1]
    last_sys = last_bp['systolic']
    last_dia = last_bp['diastolic']
    last_pulse = last_bp['pulse']
    if last_sys > 130 or last_dia > 85: delta_bp = "Atenção"
    else: delta_bp = "Normal"

c3.metric("❤️ Pressão (Última)", f"{last_sys} x {last_dia}", delta_bp, delta_color="inverse")
c4.metric("💓 Pulsação", f"{last_pulse} bpm", "Repouso ideal < 80")

st.divider()

# --- GRÁFICO DE PRESSÃO (NOVO) ---
st.subheader("🫀 Monitor Cardíaco (Pressão Arterial)")
if not df_bp.empty:
    fig_bp = go.Figure()
    # Linhas de Referência
    fig_bp.add_hline(y=120, line_dash="dot", line_color="green", annotation_text="Ideal (120)", annotation_position="bottom right")
    fig_bp.add_hline(y=80, line_dash="dot", line_color="green", annotation_text="Ideal (80)", annotation_position="bottom right")

    fig_bp.add_trace(go.Scatter(x=df_bp['measurement_time'], y=df_bp['diastolic'], name="Baixa", mode='lines+markers', line=dict(color='blue')))
    fig_bp.add_trace(go.Scatter(x=df_bp['measurement_time'], y=df_bp['systolic'], name="Alta", mode='lines+markers', line=dict(color='red'), fill='tonexty', fillcolor='rgba(255, 0, 0, 0.1)'))

    fig_bp.update_layout(title=dict(text="Histórico de Pressão"), yaxis=dict(title=dict(text="mmHg"), range=[40, 180]), height=300, margin=dict(l=10,r=10,t=40,b=10), hovermode="x unified")
    st.plotly_chart(fig_bp, use_container_width=True)
else: st.info("Adicione medição de pressão no Tracker.")

st.divider()

# --- GRÁFICO EVOLUÇÃO CORPORAL ---
st.subheader("📉 Evolução Corporal Unificada")
if not df_peso.empty:
    p_inicial = 144.9
    d_total = (hoje + timedelta(days=60) - DATA_INICIO).days
    dates_m = [DATA_INICIO + timedelta(days=i) for i in range(d_total + 1)]
    vals_m = [max(float(p['meta_peso_alvo']), p_inicial - (i * (float(p['ritmo_semanal'])/7))) for i in range(len(dates_m))]
    
    fig_combo = go.Figure()
    fig_combo.add_trace(go.Scatter(x=dates_m, y=vals_m, name="Meta", mode='lines', line=dict(color='gray', dash='dot')))
    fig_combo.add_trace(go.Scatter(x=df_peso['data'], y=df_peso['peso_kg'], name="Peso (kg)", mode='lines+markers', line=dict(color='#1f77b4', width=4)))
    
    if not df_medidas.empty:
        fig_combo.add_trace(go.Scatter(
            x=df_medidas['log_date'], y=df_medidas['waist_cm'], 
            name="Cintura (cm)", mode='lines+markers', 
            line=dict(color='#d62728', width=3), yaxis='y2'
        ))

    # Layout Blindado (sem erro de versão Plotly)
    fig_combo.update_layout(
        title=dict(text="Peso vs Cintura"),
        yaxis=dict(title=dict(text="Peso (kg)", font=dict(color="#1f77b4")), tickfont=dict(color="#1f77b4")),
        yaxis2=dict(title=dict(text="Cintura (cm)", font=dict(color="#d62728")), tickfont=dict(color="#d62728"), overlaying='y', side='right'),
        legend=dict(x=0.01, y=0.99, bgcolor='rgba(255,255,255,0.8)'),
        height=450, hovermode="x unified"
    )
    st.plotly_chart(fig_combo, use_container_width=True)
else: st.info("Sem dados de peso.")

st.divider()

# --- GRÁFICOS DIETA (RESTAURADOS) ---
st.subheader("🍽️ Controle Nutricional")

# Gráfico de Histórico de Macros
if not df_hist.empty:
    m1, m2, m3 = st.columns(3)
    def plot_macro(df, col_real, val_meta, nome, cor):
        fig = go.Figure()
        fig.add_trace(go.Bar(x=df['data'], y=df[col_real], name="Real", marker_color=cor))
        fig.add_trace(go.Scatter(x=df['data'], y=[val_meta]*len(df), name="Meta", mode='lines', line=dict(color='gray', dash='dot')))
        fig.update_layout(title=dict(text=nome), height=250, margin=dict(l=10,r=10,t=40,b=10), showlegend=False)
        return fig

    # Proteína
    m1.plotly_chart(plot_macro(df_hist, 'tprot', p['meta_proteina'], f"Proteína (Meta: {p['meta_proteina']}g)", "#3366CC"), use_container_width=True)
    
    # Carbo
    meta_c = p.get('meta_carbo', 150)
    m2.plotly_chart(plot_macro(df_hist, 'tcarb', meta_c, f"Carbo (Meta: {meta_c}g)", "#FF9900"), use_container_width=True)
    
    # Gordura
    meta_g = p.get('meta_gordura', 59)
    m3.plotly_chart(plot_macro(df_hist, 'tgord', meta_g, f"Gordura (Meta: {meta_g}g)", "#DC3912"), use_container_width=True)

# Pizza de Distribuição Hoje
g1, g2 = st.columns([2, 1])
with g1:
    if not df_hist.empty:
        fig_k = go.Figure()
        fig_k.add_trace(go.Bar(x=df_hist['data'], y=df_hist['tkcal'], name='Kcal', marker_color='#4CAF50'))
        fig_k.add_trace(go.Scatter(x=df_hist['data'], y=[p['meta_kcal']]*len(df_hist), mode='lines', name='Meta', line=dict(color='red', dash='dot')))
        fig_k.update_layout(title=dict(text="Calorias vs Meta"), height=300, margin=dict(l=10,r=10,t=40,b=10))
        st.plotly_chart(fig_k, use_container_width=True)
    else: st.info("Sem dados de consumo.")

with g2:
    if int(k_act) > 0:
        c_act = df_hoje['carbo'].sum()
        g_act = df_hoje['gordura'].sum()
        fig_p = go.Figure(data=[go.Pie(labels=['Prot','Carb','Gord'], values=[p_act*4, c_act*4, g_act*9], hole=.5, marker=dict(colors=['#3366CC','#FF9900','#DC3912']))])
        fig_p.update_layout(title=dict(text="Distribuição Hoje"), height=300, margin=dict(l=10,r=10,t=40,b=10))
        st.plotly_chart(fig_p, use_container_width=True)
    else: st.info("Registre hoje.")
