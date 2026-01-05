import streamlit as st
import pandas as pd
import psycopg2
from datetime import datetime, timedelta
import pytz
import plotly.graph_objects as go

# 1. CONFIGURAÇÃO VISUAL
st.set_page_config(page_title="Leo's Nutrition Dash", page_icon="🦁", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
    <style>
    #MainMenu {visibility: hidden;} footer {visibility: hidden;} header {visibility: hidden;}
    .block-container {padding-top: 1rem; padding-bottom: 2rem;}
    div[data-testid="stMetric"] { background-color: #f0f2f6; padding: 10px; border-radius: 10px; border: 1px solid #e0e0e0; }
    @media (prefers-color-scheme: dark) { div[data-testid="stMetric"] { background-color: #262730; border: 1px solid #464b5c; } }
    </style>
    """, unsafe_allow_html=True)

# --- CONEXÃO COM TRATAMENTO DE ERRO DE TRANSAÇÃO ---
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
                return pd.read_sql(query, conn, params=params)
            else:
                cur.execute(query, params)
                conn.commit()
                return True
    except Exception as e:
        if conn: conn.rollback() # Crucial para evitar o erro de transação abortada
        st.error(f"Erro DB: {e}")
        return pd.DataFrame() if is_select else False

# --- TRAVA DE SEGURANÇA ---
token_url = st.query_params.get("token")
if token_url != st.secrets.get("DASH_ACCESS_TOKEN"):
    st.error("🔒 Acesso Negado."); st.stop()

# --- INICIALIZAÇÃO DA TABELA DE PERFIL ---
run_query("""
    CREATE TABLE IF NOT EXISTS public.perfil (
        id INTEGER PRIMARY KEY, genero TEXT, idade INTEGER, altura_cm INTEGER, 
        atividade TEXT, ritmo_semanal REAL, meta_kcal INTEGER, 
        meta_proteina INTEGER, meta_carbo INTEGER, meta_gordura INTEGER, meta_peso_alvo REAL
    );
""", is_select=False)

# --- BUSCA DE DADOS (SQL) ---
df_perfil = run_query("SELECT * FROM public.perfil WHERE id = 1")
df_peso_last = run_query("SELECT peso_kg FROM public.peso ORDER BY data DESC, id DESC LIMIT 1")

# Dados Iniciais Automáticos
if not df_perfil.empty:
    p = df_perfil.iloc[0]
else:
    p = {'genero': 'Masculino', 'idade': 41, 'altura_cm': 185, 'atividade': 'Sedentário (1.2)', 
         'ritmo_semanal': 0.8, 'meta_kcal': 1650, 'meta_proteina': 130, 'meta_carbo': 150, 'meta_gordura': 58, 'meta_peso_alvo': 120.0}

PESO_ATUAL = float(df_peso_last.iloc[0]['peso_kg']) if not df_peso_last.empty else 141.9

# --- 2. BARRA LATERAL (CÁLCULO DINÂMICO + SALVAR) ---
st.sidebar.header("🧮 Perfil Biométrico")

# Campos fora do formulário para cálculo instantâneo
gen = st.sidebar.radio("Gênero:", ["Masculino", "Feminino"], index=0 if p['genero'] == "Masculino" else 1)
idade = st.sidebar.number_input("Idade:", value=int(p['idade']))
alt = st.sidebar.number_input("Altura (cm):", value=int(p['altura_cm']))
peso_ref = st.sidebar.number_input("Peso para Cálculo (kg):", value=PESO_ATUAL)

ativ_ops = {"Sedentário (1.2)": 1.2, "Leve (1.375)": 1.375, "Moderado (1.55)": 1.55, "Alto (1.725)": 1.725}
ativ_sel = st.sidebar.selectbox("Atividade:", list(ativ_ops.keys()), index=list(ativ_ops.keys()).index(p['atividade']))

# Cálculo Mifflin-St Jeor Instantâneo
tmb = (10 * peso_ref) + (6.25 * alt) - (5 * idade) + (5 if gen == "Masculino" else -161)
get_total = tmb * ativ_ops[ativ_sel]

st.sidebar.info(f"🧬 **Ciência (GET): {int(get_total)} kcal**")

with st.sidebar.form("form_persist"):
    st.write("### Ajuste Final de Metas")
    mkcal = st.number_input("Meta Kcal:", value=int(p['meta_kcal']))
    mprot = st.number_input("Proteína (g):", value=int(p['meta_proteina']))
    mcarb = st.number_input("Carbo (g):", value=int(p['meta_carbo']))
    mgord = st.number_input("Gordura (g):", value=int(p['meta_gordura']))
    palvo = st.number_input("Peso Alvo (kg):", value=float(p['meta_peso_alvo']))
    ritmo = st.slider("Ritmo (kg/sem):", 0.1, 2.0, float(p['ritmo_semanal']))
    
    if st.form_submit_button("💾 SALVAR CONFIGURAÇÕES"):
        run_query("""
            INSERT INTO public.perfil (id, genero, idade, altura_cm, atividade, ritmo_semanal, meta_kcal, meta_proteina, meta_carbo, meta_gordura, meta_peso_alvo)
            VALUES (1, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET genero=EXCLUDED.genero, idade=EXCLUDED.idade, altura_cm=EXCLUDED.altura_cm, atividade=EXCLUDED.atividade, ritmo_semanal=EXCLUDED.ritmo_semanal, meta_kcal=EXCLUDED.meta_kcal, meta_proteina=EXCLUDED.meta_proteina, meta_carbo=EXCLUDED.meta_carbo, meta_gordura=EXCLUDED.meta_gordura, meta_peso_alvo=EXCLUDED.meta_peso_alvo;
        """, (gen, idade, alt, ativ_sel, ritmo, mkcal, mprot, mcarb, mgord, palvo), is_select=False)
        st.rerun()

# --- 3. PROCESSAMENTO E INTERFACE ---
hoje = datetime.now(pytz.timezone('America/Sao_Paulo')).date()
DATA_INICIO_PLANO = pd.to_datetime("2025-12-30").date()

df_hoje = run_query("SELECT * FROM public.consumo WHERE data = %s", (hoje,))
df_hist = run_query("SELECT data, SUM(kcal) as tkcal, SUM(proteina) as tprot, SUM(carbo) as tcarb, SUM(gordura) as tgord FROM public.consumo WHERE data >= %s GROUP BY data ORDER BY data ASC", (hoje - timedelta(days=30),))
df_peso_hist = run_query("SELECT * FROM public.peso ORDER BY data ASC")

st.markdown(f"# 🦁 Leo's Performance | {hoje.strftime('%d/%m')}")

# KPIs
k_act, p_act, c_act, g_act = (df_hoje['kcal'].sum(), df_hoje['proteina'].sum(), df_hoje['carbo'].sum(), df_hoje['gordura'].sum()) if not df_hoje.empty else (0,0,0,0)
cols = st.columns(4)
cols[0].metric("🔥 Calorias", f"{int(k_act)}", f"Meta: {mkcal}")
cols[1].metric("🥩 Proteína", f"{int(p_act)}g", f"Meta: {mprot}g")
cols[2].metric("⚖️ Peso Atual", f"{PESO_ATUAL}kg")
cols[3].metric("📉 Ritmo", f"{ritmo}kg/sem")

st.divider()

# Gráficos
g1, g2 = st.columns([2, 1])
with g1:
    st.subheader("📊 Calorias vs Meta")
    if not df_hist.empty:
        fig = go.Figure()
        fig.add_trace(go.Bar(x=df_hist['data'], y=df_hist['tkcal'], marker_color='#4CAF50', name='Real'))
        fig.add_trace(go.Scatter(x=df_hist['data'], y=[mkcal]*len(df_hist), mode='lines', name='Meta', line=dict(color='red', dash='dot')))
        st.plotly_chart(fig, use_container_width=True)

with g2:
    st.subheader("🎯 Distribuição")
    if k_act > 0:
        fig_pie = go.Figure(data=[go.Pie(labels=['P','C','G'], values=[p_act*4, c_act*4, g_act*9], hole=.5)])
        st.plotly_chart(fig_pie, use_container_width=True)

# Controle Semanal de Macros
st.subheader("🔍 Controle Semanal de Macros")
if not df_hist.empty:
    m1, m2, m3 = st.columns(3)
    def make_small(df, col, meta, title, color):
        f = go.Figure()
        f.add_trace(go.Bar(x=df['data'], y=df[col], marker_color=color))
        f.add_trace(go.Scatter(x=df['data'], y=[meta]*len(df), mode='lines', line=dict(color='gray', dash='dash')))
        f.update_layout(title=title, height=220, margin=dict(l=5,r=5,t=30,b=5), showlegend=False)
        return f
    m1.plotly_chart(make_small(df_hist, 'tprot', mprot, "Proteína", "#3366CC"), use_container_width=True)
    m2.plotly_chart(make_small(df_hist, 'tcarb', mcarb, "Carbo", "#FF9900"), use_container_width=True)
    m3.plotly_chart(make_small(df_hist, 'tgord', mgord, "Gordura", "#DC3912"), use_container_width=True)

st.divider()

# Peso
st.subheader("⚖️ Rumo ao Peso Ideal")
if not df_peso_hist.empty:
    df_p = df_peso_hist.copy()
    df_p['data'] = pd.to_datetime(df_p['data'])
    p_start = 141.9
    d_total = (hoje + timedelta(days=45) - DATA_INICIO_PLANO).days
    d_p = [DATA_INICIO_PLANO + timedelta(days=i) for i in range(d_total+1)]
    v_p = [max(palvo, p_start - (i * (ritmo/7))) for i in range(d_total+1)]
    
    fig_p = go.Figure()
    fig_p.add_trace(go.Scatter(x=d_p, y=v_p, name='Plano', mode='lines', line=dict(color='gray', dash='dot')))
    fig_p.add_trace(go.Scatter(x=df_p['data'], y=df_p['peso_kg'], name='Real', mode='lines+markers', line=dict(color='blue')))
    st.plotly_chart(fig_p, use_container_width=True)
