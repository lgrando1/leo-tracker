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

# --- BUSCA DE DADOS INICIAIS ---
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
META_AGUA = round((PESO_ATUAL * 35) / 1000, 1)

# --- DADOS TEMPORAIS ---
hoje = datetime.now(pytz.timezone('America/Sao_Paulo')).date()
DATA_INICIO = pd.to_datetime("2025-12-30").date()

df_hoje = run_query("SELECT * FROM public.consumo WHERE data = %s", (hoje,))
df_hist = run_query("""
    SELECT data, SUM(kcal) as tkcal, SUM(proteina) as tprot, SUM(carbo) as tcarb, 
           SUM(gordura) as tgord, SUM(quantidade) as tqtd
    FROM public.consumo 
    WHERE data >= %s GROUP BY data ORDER BY data ASC
""", (DATA_INICIO,))
df_peso = run_query("SELECT * FROM public.peso ORDER BY data ASC")

# --- RESOLUÇÃO DO PROBLEMA LAST_SYS ---
last_sys, last_dia = "--", "--"
if not df_bp.empty:
    last_bp = df_bp.iloc[-1]
    last_sys, last_dia = last_bp['systolic'], last_bp['diastolic']

# --- INTERFACE ---
st.markdown(f"# 🦁 Leo's Performance | {hoje.strftime('%d/%m')}")

# KPI PRINCIPAIS
k_act, p_act = (df_hoje['kcal'].sum(), df_hoje['proteina'].sum()) if not df_hoje.empty else (0,0)

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("🔥 Calorias", f"{int(k_act)}", f"Meta: {p['meta_kcal']}")
c2.metric("🥩 Proteína", f"{int(p_act)}g", f"Meta: {p['meta_proteina']}g")
c3.metric("💧 Água", f"{META_AGUA}L", "Meta Mínima")
c4.metric("❤️ Pressão", f"{last_sys}x{last_dia}", "Última")
c5.metric("⚖️ Peso", f"{PESO_ATUAL}kg", f"Alvo: {p['meta_peso_alvo']}")

st.divider()

# O restante do código de Analytics e Gráficos continua igual...
