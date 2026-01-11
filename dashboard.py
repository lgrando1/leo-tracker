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

# --- BUSCA DE DADOS ---
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

# --- SIDEBAR ---
st.sidebar.header("🧮 Perfil Biométrico")
st.sidebar.info(f"🧬 **Metas:**\n🔥 {p['meta_kcal']} kcal | 🥩 {p['meta_proteina']}g\n🍞 {p.get('meta_carbo', 150)}g | 🥑 {p.get('meta_gordura', 59)}g")

# --- DADOS TEMPORAIS ---
hoje = datetime.now(pytz.timezone('America/Sao_Paulo')).date()
DATA_INICIO = pd.to_datetime("2025-12-30").date()

# Query Atualizada: Agora puxa SOMA DE QUANTIDADE também
df_hoje = run_query("SELECT * FROM public.consumo WHERE data = %s", (hoje,))
df_hist = run_query("""
    SELECT data, 
           SUM(kcal) as tkcal, 
           SUM(proteina) as tprot, 
           SUM(carbo) as tcarb, 
           SUM(gordura) as tgord,
           SUM(quantidade) as tqtd
    FROM public.consumo 
    WHERE data >= %s 
    GROUP BY data 
    ORDER BY data ASC
""", (hoje - timedelta(days=30),))
df_peso = run_query("SELECT * FROM public.peso ORDER BY data ASC")

st.markdown(f"# 🦁 Leo's Performance | {hoje.strftime('%d/%m')}")

# KPI PRINCIPAIS
k_act, p_act, q_act = (df_hoje['kcal'].sum(), df_hoje['proteina'].sum(), df_hoje['quantidade'].sum()) if not df_hoje.empty else (0,0,0)
c1, c2, c3, c4 = st.columns(4)
c1.metric("🔥 Calorias", f"{int(k_act)}", f"Meta: {p['meta_kcal']}")
c2.metric("🥩 Proteína", f"{int(p_act)}g", f"Meta: {p['meta_proteina']}g")

# KPI Pressão
last_sys, last_dia, last_pulse = "--", "--", "--"
if not df_bp.empty:
    last_bp = df_bp.iloc[-1]
    last_sys, last_dia, last_pulse = last_bp['systolic'], last_bp['diastolic'], last_bp['pulse']

c3.metric("❤️ Pressão", f"{last_sys} x {last_dia}", "Normal" if isinstance(last_sys, int) and last_sys < 130 else "Atenção")
c4.metric("⚖️ Peso Atual", f"{PESO_ATUAL} kg")

st.divider()

# --- NOVA LÓGICA: CÁLCULO DE ATRASO/ADIANTAMENTO DO PESO ---
st.subheader("⚖️ Análise de Progresso (Meta vs Real)")

peso_inicial = 144.9 # Fixo conforme seu histórico inicial
ritmo_semanal = float(p.get('ritmo_semanal', 0.8))
ritmo_diario = ritmo_semanal / 7.0

# 1. Quanto peso já foi perdido?
peso_perdido = peso_inicial - PESO_ATUAL

# 2. Quantos dias seriam necessários para perder isso no ritmo da meta?
dias_esperados = peso_perdido / ritmo_diario if ritmo_diario > 0 else 0

# 3. Qual seria a data esperada para estar com o peso de hoje?
data_esperada_para_peso_atual = DATA_INICIO + timedelta(days=int(dias_esperados))
diferenca_dias = (hoje - data_esperada_para_peso_atual).days

# Lógica de exibição
col_a, col_b = st.columns([1, 2])

with col_a:
    st.write("") # Espaço
    if diferenca_dias < 0:
        # Hoje é ANTES da data esperada -> ADIANTADO
        st.success(f"🚀 **ADIANTADO: {abs(diferenca_dias)} dias**")
        st.caption(f"Com {PESO_ATUAL}kg, você atingiu hoje uma meta que estava prevista apenas para **{data_esperada_para_peso_atual.strftime('%d/%m')}**.")
    elif diferenca_dias > 0:
        # Hoje é DEPOIS da data esperada -> ATRASADO
        st.warning(f"⚠️ **ATRASADO: {diferenca_dias} dias**")
        st.caption(f"Pelo plano ({ritmo_semanal}kg/sem), você deveria ter atingido {PESO_ATUAL}kg em **{data_esperada_para_peso_atual.strftime('%d/%m')}**.")
    else:
        st.info("🎯 **EXATAMENTE NO PLANO**")
        st.caption("Você está seguindo o ritmo planejado milimetricamente.")

    st.metric("Volume Ingerido Hoje", f"{int(q_act)} g", "Densidade Nutricional")


with col_b:
    if not df_peso.empty:
        d_total = (hoje + timedelta(days=60) - DATA_INICIO).days
        dates_m = [DATA_INICIO + timedelta(days=i) for i in range(d_total + 1)]
        vals_m = [max(float(p['meta_peso_alvo']), peso_inicial - (i * (ritmo_semanal/7))) for i in range(len(dates_m))]
        
        fig_combo = go.Figure()
        fig_combo.add_trace(go.Scatter(x=dates_m, y=vals_m, name="Meta Planejada", mode='lines', line=dict(color='gray', dash='dot')))
        fig_combo.add_trace(go.Scatter(x=df_peso['data'], y=df_peso['peso_kg'], name="Peso Real", mode='lines+markers', line=dict(color='#1f77b4', width=4)))
        
        # Marcador do dia esperado
        fig_combo.add_trace(go.Scatter(
            x=[data_esperada_para_peso_atual], y=[PESO_ATUAL],
            mode='markers', marker=dict(color='purple', size=12, symbol='star'),
            name="Data Esperada (Teórica)"
        ))

        fig_combo.update_layout(height=300, margin=dict(l=10,r=10,t=10,b=10), hovermode="x unified")
        st.plotly_chart(fig_combo, use_container_width=True)

st.divider()

# --- NOVO GRÁFICO: DENSIDADE CALÓRICA (KCAL + GRAMAS) ---
st.subheader("🍽️ Volume (g) vs Calorias (kcal)")

if not df_hist.empty:
    # Cria gráfico com 2 eixos Y
    fig_dens = make_subplots(specs=[[{"secondary_y": True}]])

    # Barras: Quantidade (Gramas)
    fig_dens.add_trace(
        go.Bar(x=df_hist['data'], y=df_hist['tqtd'], name="Volume (g)", marker_color='rgba(52, 152, 219, 0.6)'),
        secondary_y=False
    )

    # Linha: Calorias
    fig_dens.add_trace(
        go.Scatter(x=df_hist['data'], y=df_hist['tkcal'], name="Calorias", mode='lines+markers', line=dict(color='#e74c3c', width=3)),
        secondary_y=True
    )
    
    # Linha de Meta de Calorias
    fig_dens.add_trace(
        go.Scatter(x=df_hist['data'], y=[p['meta_kcal']]*len(df_hist), name="Meta Kcal", mode='lines', line=dict(color='gray', dash='dot')),
        secondary_y=True
    )

    fig_dens.update_layout(
        title="Relação: O quanto você comeu (g) vs Quanto valeu (kcal)",
        height=350,
        margin=dict(l=10,r=10,t=40,b=10),
        legend=dict(orientation="h", y=1.1)
    )
    
    # Config dos Eixos
    fig_dens.update_yaxes(title_text="Quantidade (g)", secondary_y=False)
    fig_dens.update_yaxes(title_text="Calorias (kcal)", secondary_y=True)

    st.plotly_chart(fig_dens, use_container_width=True)

else:
    st.info("Registre alimentos para ver a análise de densidade calórica.")

st.divider()

# --- ANÁLISE CORPORAL (Medidas e Pressão) ---
st.subheader("🧬 Análise Corporal")

col_med, col_press = st.columns(2)

with col_med:
    st.write("**Composição (Gordura/Cintura)**")
    if not df_medidas.empty:
        last_m = df_medidas.iloc[-1]
        bf_atual = last_m['body_fat_est']
        
        # Gráfico BF
        fig_bf = go.Figure()
        fig_bf.add_trace(go.Scatter(x=df_medidas['log_date'], y=df_medidas['body_fat_est'], mode='lines+markers', name='% Gordura', line=dict(color='#e67e22')))
        fig_bf.update_layout(height=250, margin=dict(l=10,r=10,t=10,b=10), title=f"BF Atual: {bf_atual:.1f}%")
        st.plotly_chart(fig_bf, use_container_width=True)
    else: st.info("Sem medidas.")

with col_press:
    st.write("**Pressão Arterial**")
    if not df_bp.empty:
        fig_bp = go.Figure()
        fig_bp.add_hline(y=120, line_dash="dot", line_color="green")
        fig_bp.add_trace(go.Scatter(x=df_bp['measurement_time'], y=df_bp['systolic'], name="Alta", line=dict(color='red')))
        fig_bp.add_trace(go.Scatter(x=df_bp['measurement_time'], y=df_bp['diastolic'], name="Baixa", line=dict(color='blue')))
        fig_bp.update_layout(height=250, margin=dict(l=10,r=10,t=10,b=10), title="Histórico PA")
        st.plotly_chart(fig_bp, use_container_width=True)
    else: st.info("Sem pressão.")
