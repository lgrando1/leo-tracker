import streamlit as st
import pandas as pd
import psycopg2
from datetime import datetime, timedelta
import pytz
import plotly.express as px
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

# --- CONEXÃO E DADOS INICIAIS ---
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
        if conn:
            conn.rollback() # <--- ISSO RESOLVE O ERRO DE TRANSACTION ABORTED
        st.error(f"Erro DB: {e}")
        return pd.DataFrame() if is_select else False

# --- CONTROLE DE ACESSO VIA URL ---
token_url = st.query_params.get("token")
token_esperado = st.secrets.get("DASH_ACCESS_TOKEN")

if token_url != token_esperado:
    st.error("🔒 Acesso Negado. Token inválido ou ausente.")
    st.stop() 

# --- INICIALIZAÇÃO DA TABELA DE PERFIL ---
run_query("""
    CREATE TABLE IF NOT EXISTS public.perfil (
        id INTEGER PRIMARY KEY, genero TEXT, idade INTEGER, altura_cm INTEGER, 
        atividade TEXT, fase_dieta TEXT, ritmo_semanal REAL,
        meta_kcal INTEGER, meta_proteina INTEGER, meta_carbo INTEGER, 
        meta_gordura INTEGER, meta_peso_alvo REAL
    );
""", is_select=False)

# --- BUSCA DE DADOS SALVOS ---
df_perfil = run_query("SELECT * FROM public.perfil WHERE id = 1")
df_peso_last = run_query("SELECT peso_kg FROM public.peso ORDER BY data DESC LIMIT 1")

# Dados iniciais se o banco estiver vazio
if not df_perfil.empty:
    p_db = df_perfil.iloc[0]
else:
    p_db = {'genero': 'Masculino', 'idade': 41, 'altura_cm': 185, 'atividade': 'Sedentário (1.2)', 
            'fase_dieta': 'Perder Peso (Moderado)', 'ritmo_semanal': 0.8, 'meta_kcal': 1650, 
            'meta_proteina': 110, 'meta_carbo': 150, 'meta_gordura': 50, 'meta_peso_alvo': 120.0}

PESO_ATUAL_DB = float(df_peso_last.iloc[0]['peso_kg']) if not df_peso_last.empty else 141.9

# --- 2. BARRA LATERAL (CALCULADORA + SALVAMENTO) ---
st.sidebar.header("🧮 Perfil Biométrico")
with st.sidebar.form("form_perfil"):
    genero = st.radio("Gênero:", ["Masculino", "Feminino"], index=0 if p_db['genero'] == "Masculino" else 1, horizontal=True)
    idade = st.number_input("Idade:", value=int(p_db['idade']))
    altura_cm = st.number_input("Altura (cm):", value=int(p_db['altura_cm']))
    peso_calc = st.number_input("Peso para Cálculo (kg):", value=PESO_ATUAL_DB)

    st.sidebar.subheader("🏃‍♂️ Nível de Atividade")
    atividade_opcoes = {"Sedentário (1.2)": 1.2, "Leve (1.375)": 1.375, "Moderado (1.55)": 1.55, "Alto (1.725)": 1.725}
    ativ_selecao = st.selectbox("Fator de Movimento:", list(atividade_opcoes.keys()), index=list(atividade_opcoes.keys()).index(p_db['atividade']))
    
    # CÁLCULO CIENTÍFICO (Sugestão)
    tmb = (10 * peso_calc) + (6.25 * altura_cm) - (5 * idade) + (5 if genero == "Masculino" else -161)
    get_total = tmb * atividade_opcoes[ativ_selecao]
    
    st.divider()
    META_KCAL = st.number_input("Meta Kcal:", value=int(p_db['meta_kcal']))
    META_PROTEINA = st.number_input("Meta Proteína (g):", value=int(p_db['meta_proteina']))
    META_CARBO = st.number_input("Meta Carbo (g):", value=int(p_db['meta_carbo']))
    META_GORDURA = st.number_input("Meta Gordura (g):", value=int(p_db['meta_gordura']))
    META_PESO = st.number_input("Peso Alvo (kg):", value=float(p_db['meta_peso_alvo']))
    PERDA_SEMANAL_KG = st.slider("Ritmo (kg/sem):", 0.1, 2.0, float(p_db['ritmo_semanal']))
    
    if st.form_submit_button("💾 SALVAR CONFIGURAÇÕES"):
        run_query("""
            INSERT INTO public.perfil (id, genero, idade, altura_cm, atividade, ritmo_semanal, meta_kcal, meta_proteina, meta_carbo, meta_gordura, meta_peso_alvo)
            VALUES (1, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET genero=EXCLUDED.genero, idade=EXCLUDED.idade, altura_cm=EXCLUDED.altura_cm, atividade=EXCLUDED.atividade, ritmo_semanal=EXCLUDED.ritmo_semanal, meta_kcal=EXCLUDED.meta_kcal, meta_proteina=EXCLUDED.meta_proteina, meta_carbo=EXCLUDED.meta_carbo, meta_gordura=EXCLUDED.meta_gordura, meta_peso_alvo=EXCLUDED.meta_peso_alvo;
        """, (genero, idade, altura_cm, ativ_selecao, PERDA_SEMANAL_KG, META_KCAL, META_PROTEINA, META_CARBO, META_GORDURA, META_PESO), is_select=False)
        st.rerun()

# --- PROCESSAMENTO ---
def get_now_br(): return datetime.now(pytz.timezone('America/Sao_Paulo'))
hoje = get_now_br().date()
DATA_INICIO_REGIME = pd.to_datetime("2025-12-30").date()

df_hoje = run_query("SELECT * FROM public.consumo WHERE data = %s", (hoje,))
df_hist = run_query("SELECT data, SUM(kcal) as tkcal, SUM(proteina) as tprot, SUM(carbo) as tcarb, SUM(gordura) as tgord FROM public.consumo WHERE data >= %s GROUP BY data ORDER BY data ASC", (hoje - timedelta(days=30),))
df_peso = run_query("SELECT * FROM public.peso ORDER BY data ASC")

# --- INDICADOR GLÚTEN ---
tem_gluten = False
if not df_hoje.empty:
    col_g = df_hoje['gluten'].astype(str).str.lower()
    if not df_hoje[(col_g.str.contains('contém', na=False) & ~col_g.str.contains('não', na=False)) | (col_g == 'sim')].empty:
        tem_gluten = True

# --- INTERFACE PRINCIPAL ---
st.markdown(f"# 🦁 Leo's Performance | {hoje.strftime('%d/%m')}")
if tem_gluten: st.error("⚠️ **GLÚTEN DETECTADO NO DIÁRIO!**")
else: st.success("✅ **Dieta Limpa (Glúten-Free)**")

st.markdown("---")

# KPIs
k_act, p_act, c_act, g_act = (df_hoje['kcal'].sum(), df_hoje['proteina'].sum(), df_hoje['carbo'].sum(), df_hoje['gordura'].sum()) if not df_hoje.empty else (0,0,0,0)
cols = st.columns(4)
def metric_card(col, label, actual, target, suffix=""):
    col.metric(label, f"{int(actual)}{suffix}", f"Meta: {target}{suffix}", delta_color="off")
    col.progress(min(actual / target, 1.0) if target > 0 else 0)

metric_card(cols[0], "🔥 Calorias", k_act, META_KCAL)
metric_card(cols[1], "🥩 Proteína", p_act, META_PROTEINA, "g")
metric_card(cols[2], "🍞 Carbo", c_act, META_CARBO, "g")
metric_card(cols[3], "🥑 Gordura", g_act, META_GORDURA, "g")

st.markdown("---")

# Gráficos de Calorias e Pizza
g1, g2 = st.columns([2, 1])
with g1:
    st.subheader("📊 Calorias vs Meta (30 dias)")
    if not df_hist.empty:
        fig = go.Figure()
        fig.add_trace(go.Bar(x=df_hist['data'], y=df_hist['tkcal'], name='Kcal', marker_color='#4CAF50'))
        fig.add_trace(go.Scatter(x=df_hist['data'], y=[META_KCAL]*len(df_hist), mode='lines', name='Meta', line=dict(color='red', width=3, dash='dot')))
        fig.update_layout(height=320, margin=dict(l=20, r=20, t=20, b=20), legend=dict(orientation="h", y=1.1))
        st.plotly_chart(fig, use_container_width=True)

with g2:
    st.subheader("🎯 Distribuição Hoje")
    if k_act > 0:
        fig_pie = go.Figure(data=[go.Pie(labels=['Prot', 'Carbo', 'Gord'], values=[p_act*4, c_act*4, g_act*9], hole=.5, marker=dict(colors=['#3366CC', '#FF9900', '#DC3912']))])
        fig_pie.update_layout(height=320, margin=dict(l=20, r=20, t=20, b=20))
        st.plotly_chart(fig_pie, use_container_width=True)

# Mini Gráficos de Macros
st.subheader("🔍 Controle Semanal de Macros")
if not df_hist.empty:
    m1, m2, m3 = st.columns(3)
    def create_small(df, col, meta, title, color):
        fig = go.Figure()
        fig.add_trace(go.Bar(x=df['data'], y=df[col], marker_color=color))
        fig.add_trace(go.Scatter(x=df['data'], y=[meta]*len(df), mode='lines', line=dict(color='gray', dash='dash')))
        fig.update_layout(title=title, height=250, margin=dict(l=10, r=10, t=40, b=20), showlegend=False)
        return fig
    m1.plotly_chart(create_small(df_hist, 'tprot', META_PROTEINA, "🥩 Proteína", "#3366CC"), use_container_width=True)
    m2.plotly_chart(create_small(df_hist, 'tcarb', META_CARBO, "🍞 Carbo", "#FF9900"), use_container_width=True)
    m3.plotly_chart(create_small(df_hist, 'tgord', META_GORDURA, "🥑 Gordura", "#DC3912"), use_container_width=True)

st.markdown("---")
# Gráfico de Peso
st.subheader("⚖️ Rumo ao Peso Ideal")
if not df_peso.empty:
    df_peso['data'] = pd.to_datetime(df_peso['data'])
    peso_start_plano = 141.9
    ultimo_dia = hoje + timedelta(days=45)
    dias_p = (ultimo_dia - DATA_INICIO_REGIME).days
    dates_p = [DATA_INICIO_REGIME + timedelta(days=i) for i in range(dias_p + 1)]
    vals_p = [max(META_PESO, peso_start_plano - (i * (PERDA_SEMANAL_KG/7))) for i in range(dias_p + 1)]
    
    fig_p = go.Figure()
    fig_p.add_trace(go.Scatter(x=dates_p, y=vals_p, name='Plano Saudável', mode='lines', line=dict(color='gray', dash='dot')))
    fig_p.add_trace(go.Scatter(x=df_peso['data'], y=df_peso['peso_kg'], name='Peso Real', mode='lines+markers', line=dict(color='blue', width=4)))
    fig_p.update_layout(height=400, margin=dict(l=20, r=20, t=20, b=20))
    st.plotly_chart(fig_p, use_container_width=True)
