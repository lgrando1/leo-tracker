import streamlit as st
import pandas as pd
import psycopg2
from datetime import datetime, timedelta
import pytz
import plotly.express as px
import plotly.graph_objects as go

# Bloqueio simples via URL
query_params = st.query_params
if query_params.get("token") != st.secrets.get("DASH_ACCESS_TOKEN", "123"):
    st.error("Acesso negado. Link inválido.")
    st.stop()

# 1. CONFIGURAÇÃO (Modo Leitura / Wide)
st.set_page_config(page_title="Leo's Dashboard", page_icon="🦁", layout="wide", initial_sidebar_state="collapsed")

# CSS para limpar a interface
st.markdown("""
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    .block-container {padding-top: 1rem;}
    </style>
    """, unsafe_allow_html=True)

# --- CONFIGURAÇÕES ---
META_KCAL = 1600
META_PROTEINA = 150
META_PESO = 120.0
PERDA_SEMANAL_KG = 0.8

# --- CONEXÃO ---
@st.cache_resource(ttl=300)
def get_connection():
    return psycopg2.connect(st.secrets["DATABASE_URL"])

def get_now_br():
    return datetime.now(pytz.timezone('America/Sao_Paulo'))

def run_query(query, params=None):
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute("SET timezone TO 'America/Sao_Paulo';")
            if params:
                return pd.read_sql(query, conn, params=params)
            else:
                return pd.read_sql(query, conn)
    except Exception as e:
        st.error(f"Erro: {e}")
        return pd.DataFrame()

# --- DADOS ---
hoje = get_now_br().date()
df_hoje = run_query("SELECT * FROM public.consumo WHERE data = %s", (hoje,))
df_hist = run_query("SELECT data, SUM(kcal) as total_kcal FROM public.consumo WHERE data >= %s GROUP BY data ORDER BY data ASC", (hoje - timedelta(days=30),))
df_peso = run_query("SELECT * FROM public.peso ORDER BY data ASC")

# --- INDICADOR DE GLÚTEN (CORRIGIDO) ---
tem_gluten = False
itens_gluten = []

if not df_hoje.empty:
    # Normaliza o texto para evitar problemas com maiúsculas/minúsculas
    coluna_gluten = df_hoje['gluten'].astype(str).str.lower()
    
    # Lógica de Filtro:
    # 1. Deve conter a palavra "contém"
    # 2. E NÃO deve conter a palavra "não"
    # 3. OU deve conter "sim"
    filtro_gluten = df_hoje[
        (coluna_gluten.str.contains('contém', na=False) & ~coluna_gluten.str.contains('não', na=False)) | 
        (coluna_gluten == 'sim') |
        (coluna_gluten == 'contem')
    ]
    
    if not filtro_gluten.empty:
        tem_gluten = True
        itens_gluten = filtro_gluten['alimento'].tolist()

# --- CABEÇALHO ---
c1, c2 = st.columns([3, 1])
c1.markdown("# 🦁 Leo's Performance")
c2.markdown(f"### {hoje.strftime('%d/%m/%Y')}")

# ALERTA VISUAL DE GLÚTEN
if tem_gluten:
    st.error(f"⚠️ **ALERTA DE GLÚTEN DETECTADO HOJE!** ({', '.join(itens_gluten)})")
else:
    st.success("✅ **Dieta Limpa:** Nenhum glúten detectado hoje.")

st.divider()

# --- KPI DO DIA ---
kcal_atual = df_hoje['kcal'].sum() if not df_hoje.empty else 0
prot_atual = df_hoje['proteina'].sum() if not df_hoje.empty else 0

k1, k2, k3 = st.columns(3)
k1.metric("🔥 Calorias", f"{int(kcal_atual)}", f"{int(META_KCAL - kcal_atual)} resta", delta_color="inverse")
k2.metric("🥩 Proteína", f"{int(prot_atual)}g", f"Meta: {META_PROTEINA}g")

# Peso atual (último registrado)
peso_atual = df_peso.iloc[-1]['peso_kg'] if not df_peso.empty else 0
k3.metric("⚖️ Peso Atual", f"{peso_atual}kg", f"Meta: {META_PESO}kg")

st.progress(min(kcal_atual / META_KCAL, 1.0))

st.divider()

# --- GRÁFICOS ---
c_g1, c_g2 = st.columns(2)

with c_g1:
    st.subheader("📅 Calorias (30 Dias)")
    if not df_hist.empty:
        fig = px.bar(df_hist, x='data', y='total_kcal', color_discrete_sequence=['#4CAF50'])
        fig.add_hline(y=META_KCAL, line_dash="dot", annotation_text="Meta", line_color="red")
        st.plotly_chart(fig, use_container_width=True)

with c_g2:
    st.subheader("⚖️ Curva de Peso")
    if not df_peso.empty:
        df_peso['data'] = pd.to_datetime(df_peso['data'])
        fig_p = px.line(df_peso, x='data', y='peso_kg', markers=True)
        st.plotly_chart(fig_p, use_container_width=True)
    else:
        st.info("Registre o peso no app principal.")
