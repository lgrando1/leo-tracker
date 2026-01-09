import streamlit as st
import pandas as pd
import psycopg2
from datetime import datetime, timedelta
import json
import pytz 
from groq import Groq 
import io
from fpdf import FPDF
import math

# 1. CONFIGURAÇÃO E ACESSO
st.set_page_config(page_title="Leo Tracker Pro", page_icon="🦁", layout="wide")

def get_now_br():
    return datetime.now(pytz.timezone('America/Sao_Paulo'))

def check_password():
    if "password_correct" not in st.session_state:
        st.session_state["password_correct"] = False
    if st.session_state["password_correct"]: return True
    st.title("🦁 Leo Tracker Pro")
    password = st.text_input("Senha de Acesso:", type="password")
    if st.button("Entrar"):
        if password == st.secrets.get("PASSWORD", "admin"): 
            st.session_state["password_correct"] = True
            st.rerun()
        else: st.error("Senha incorreta!")
    return False

if not check_password(): st.stop()

# 2. CONEXÃO E BANCO DE DADOS
@st.cache_resource(ttl=600)
def get_connection():
    return psycopg2.connect(st.secrets["DATABASE_URL"])

def executar_sql(sql, params=None, is_select=False):
    conn = None
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute("SET timezone TO 'America/Sao_Paulo';")
            if is_select:
                df = pd.read_sql(sql, conn, params=params)
                if 'data' in df.columns: df['data'] = pd.to_datetime(df['data'])
                if 'log_date' in df.columns: df['log_date'] = pd.to_datetime(df['log_date'])
                return df
            else:
                cur.execute(sql, params)
                conn.commit()
                return True
    except Exception as e:
        if conn: conn.rollback()
        st.error(f"Erro no Banco: {e}")
        return pd.DataFrame() if is_select else False

# 3. SINCRONIZAÇÃO
def inicializar_banco():
    executar_sql("CREATE TABLE IF NOT EXISTS public.consumo (id SERIAL PRIMARY KEY, data DATE, alimento TEXT, quantidade REAL, kcal REAL, proteina REAL, carbo REAL, gordura REAL, gluten TEXT DEFAULT 'Não informado');")
    executar_sql("CREATE TABLE IF NOT EXISTS public.peso (id SERIAL PRIMARY KEY, data DATE, peso_kg REAL);")
    executar_sql("CREATE TABLE IF NOT EXISTS public.perfil (id SERIAL PRIMARY KEY, genero TEXT, idade INT, altura_cm INT, atividade TEXT, objetivo TEXT, ritmo_semanal REAL, meta_kcal REAL, meta_proteina REAL, meta_carbo REAL, meta_gordura REAL, meta_peso_alvo REAL);")
    executar_sql("CREATE TABLE IF NOT EXISTS public.body_measurements (id SERIAL PRIMARY KEY, log_date DATE NOT NULL, weight_kg REAL, waist_cm REAL, neck_cm REAL, hip_cm REAL, body_fat_est REAL, notes TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);")

def get_metas_do_banco():
    try:
        df = executar_sql("SELECT * FROM public.perfil WHERE id = 1", is_select=True)
        if not df.empty:
            row = df.iloc[0]
            return {
                "kcal": int(row['meta_kcal']),
                "prot": int(row['meta_proteina']),
                "carb": int(row.get('meta_carbo', 164)),
                "gord": int(row.get('meta_gordura', 67)),
                "altura": int(row.get('altura_cm', 178))
            }
    except: pass
    return {"kcal": 1683, "prot": 108, "carb": 164, "gord": 67, "altura": 178}

inicializar_banco()
METAS = get_metas_do_banco()

def calculate_body_fat(waist, neck, height):
    if waist <= 0 or neck <= 0 or height <= 0: return 0.0
    try: return 495 / (1.0324 - 0.19077 * math.log10(waist - neck) + 0.15456 * math.log10(height)) - 450
    except: return 0.0

# (Funções de Relatório e IA omitidas aqui para brevidade, mas devem permanecer no seu arquivo)
# ... [mantenha gerar_excel, gerar_pdf e processar_texto_ia do seu código] ...

# 6. INTERFACE LIMPA
st.title("🦁 Leo Tracker Pro")

data_hoje = get_now_br().date()
df_hoje = executar_sql("SELECT * FROM public.consumo WHERE data = %s", (data_hoje,), is_select=True)

k_hoje = float(df_hoje['kcal'].sum()) if not df_hoje.empty else 0.0
p_hoje = float(df_hoje['proteina'].sum()) if not df_hoje.empty else 0.0
c_hoje = float(df_hoje['carbo'].sum()) if not df_hoje.empty else 0.0
g_hoje = float(df_hoje['gordura'].sum()) if not df_hoje.empty else 0.0

# KPIs LIMPOS (Removi os "f-strings" poluídos)
c1, c2, c3, c4 = st.columns(4)
c1.metric("🔥 Calorias", f"{int(k_hoje)}", f"Meta {METAS['kcal']}")
c2.metric("🥩 Proteína", f"{int(p_hoje)}g", f"Meta {METAS['prot']}g")
c3.metric("🍞 Carbo", f"{int(c_hoje)}g", f"Meta {METAS['carb']}g")
c4.metric("🥑 Gordura", f"{int(g_hoje)}g", f"Meta {METAS['gord']}g")
st.progress(min(k_hoje/METAS['kcal'], 1.0))

# ABAS ORGANIZADAS
tab_add, tab_hist, tab_medidas, tab_rel, tab_admin = st.tabs(["➕ Inserir", "📜 Diário", "📏 Corpo", "📄 Relatórios", "⚙️ Metas"])

with tab_add:
    st.write("### O que você comeu?")
    texto_input = st.text_area("", height=100, placeholder="Ex: 2 ovos e 1 banana", label_visibility="collapsed")
    if st.button("🚀 Processar com IA", type="primary", use_container_width=True):
        # ... [sua lógica de IA aqui] ...
        pass

with tab_hist:
    if not df_hoje.empty:
        for i, row in df_hoje.iterrows():
            with st.container():
                cc1, cc2, cc3 = st.columns([3, 2, 0.5])
                cc1.markdown(f"**{row['alimento']}**")
                cc2.caption(f"{int(row['kcal'])} kcal | P:{int(row['proteina'])} C:{int(row['carbo'])} G:{int(row['gordura'])}")
                if cc3.button("❌", key=f"del_{row['id']}"):
                    executar_sql("DELETE FROM public.consumo WHERE id = %s", (row['id'],)); st.rerun()
    else: st.info("Nada registrado hoje.")

# ... [Mantenha as abas tab_medidas, tab_rel e tab_admin exatamente como estão no seu código] ...
