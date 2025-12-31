import streamlit as st
import pandas as pd
import psycopg2
from datetime import datetime
import plotly.express as px
import json
from contextlib import contextmanager

# 1. CONFIGURAÇÃO DA PÁGINA
st.set_page_config(page_title="Leo Tracker Pro", page_icon="🦁", layout="wide")

# --- SISTEMA DE LOGIN ---
def check_password():
    if "password_correct" not in st.session_state:
        st.session_state["password_correct"] = False
    if st.session_state["password_correct"]: return True
    st.title("🦁 Leo Tracker Login")
    password = st.text_input("Senha de acesso:", type="password")
    if st.button("Entrar"):
        if password == st.secrets["PASSWORD"]:
            st.session_state["password_correct"] = True
            st.rerun()
        else: st.error("Senha incorreta!")
    return False

if not check_password(): st.stop()

# 2. GERENCIAMENTO DE CONEXÃO (BIOHACKER AUTO-RECONNECT)
@st.cache_resource
def init_connection():
    return psycopg2.connect(st.secrets["DATABASE_URL"])

def get_connection():
    """Garante que a conexão com o Neon esteja sempre viva."""
    try:
        conn = init_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
        return conn
    except:
        st.cache_resource.clear()
        return init_connection()

@contextmanager
def get_cursor():
    conn = get_connection()
    cur = conn.cursor()
    try:
        yield cur
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cur.close()

# 3. METAS DO PLANO (Leonardo Grando - Dezembro/25)
META_KCAL = 2000 
META_PROT = 160  

# 4. INICIALIZAÇÃO DO BANCO
def inicializar_banco():
    with get_cursor() as cur:
        cur.execute("SET search_path TO public")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tabela_taco (
                id SERIAL PRIMARY KEY, alimento TEXT, kcal REAL, proteina REAL, carbo REAL, gordura REAL
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS consumo (
                id SERIAL PRIMARY KEY, 
                data_hora TIMESTAMP DEFAULT CURRENT_TIMESTAMP, 
                alimento TEXT, quantidade REAL, kcal REAL, proteina REAL, carbo REAL, gordura REAL, 
                gluten TEXT DEFAULT 'Não informado'
            );
        """)
        cur.execute("CREATE TABLE IF NOT EXISTS peso (id SERIAL PRIMARY KEY, data DATE UNIQUE, peso_kg REAL);")

def limpar_valor_taco(valor):
    if pd.isna(valor) or str(valor).strip() in ['NA', 'TR', '', '*', '-']: return 0.0
    try: return float(str(valor).replace(',', '.'))
    except: return 0.0

try:
    inicializar_banco()
except Exception as e:
    st.error(f"Erro ao despertar o banco de dados: {e}")
    st.stop()

# 5. INTERFACE PRINCIPAL
st.title("🦁 Leo Tracker Pro")
tabs = st.tabs(["🍽️ Registro", "🤖 IA Nutricional", "📈 Progresso", "📋 Plano & Sugestões", "⚖️ Peso & Admin"])

with tabs[0]:
    st.subheader("Busca Manual (TACO)")
    termo = st.text_input("🔍 Pesquisar alimento:")
    if termo:
        conn = get_connection() # Usando a função segura aqui
        df_res = pd.read_sql("SELECT * FROM public.tabela_taco WHERE alimento ILIKE %s LIMIT 50", conn, params=(f'%{termo}%',))
        if not df_res.empty:
            escolha = st.selectbox("Selecione:", df_res["alimento"])
            dados = df_res[df_res["alimento"] == escolha].iloc[0]
            qtd = st.number_input("Gramas:", 0, 2000, 100)
            f = float(qtd) / 100.0
            if st.button("Salvar Alimento"):
                with get_cursor() as cur:
                    cur.execute("""INSERT INTO consumo (alimento, quantidade, kcal, proteina, carbo, gordura) 
                                   VALUES (%s,%s,%s,%s,%s,%s)""", 
                                (escolha, float(qtd), dados['kcal']*f, dados['proteina']*f, dados['carbo']*f, dados['gordura']*f))
                st.success("Registrado!")
                st.rerun()

with tabs[1]:
    st.subheader("🤖 Importar via IA")
    json_in = st.text_area("Cole o JSON da IA aqui:", height=150)
    if st.button("Processar e Salvar"):
        try:
            clean_json = json_in.replace('```json', '').replace('```', '').strip()
            dados = json.loads(clean_json)
            with get_cursor() as cur:
                for i in dados:
                    cur.execute("""INSERT INTO consumo (alimento, quantidade, kcal, proteina, carbo, gordura, gluten) 
                                   VALUES (%s,1,%s,%s,%s,%s,%s)""", 
                                (i['alimento'], i['kcal'], i['p'], i['c'], i['g'], i.get('gluten','Não informado')))
            st.success("Refeição importada!")
            st.rerun()
        except Exception as e: st.error(f"Erro no JSON: {e}")

with tabs[2]:
    st.subheader("📊 Progresso do Dia")
    conn = get_connection() # Usando a função segura aqui
    df_hoje = pd.read_sql("SELECT * FROM consumo WHERE data_hora::date = CURRENT_DATE", conn)
    if not df_hoje.empty:
        c1, c2 = st.columns(2)
        cons_kcal, cons_prot = df_hoje['kcal'].sum(), df_hoje['proteina'].sum()
        c1.metric("Energia", f"{int(cons_kcal)} / {META_KCAL} kcal", f"{int(cons_kcal - META_KCAL)} kcal", delta_color="inverse")
        c2.metric("Proteína", f"{int(cons_prot)}g / {META_PROT}g", f"{int(cons_prot - META_PROT)}g")
        
        st.divider()
        for _, row in df_hoje.iterrows():
            col_h1, col_h2, col_h3 = st.columns([1, 4, 1])
            col_h1.write(pd.to_datetime(row['data_hora']).strftime('%H:%M'))
            col_h2.write(f"**{row['alimento']}** - {int(row['kcal'])} kcal")
            if col_h3.button("🗑️", key=f"del_{row['id']}"):
                with get_cursor() as cur:
                    cur.execute("DELETE FROM consumo WHERE id = %s", (row['id'],))
                st.rerun()
    else: st.info("Nenhum registro hoje.")

with tabs[3]:
    st.subheader("📋 Orientações & Sugestões Econômicas")
    col_orig, col_econ = st.columns(2)
    with col_orig:
        st.info("🎯 Plano Original")
        st.markdown("* **Almoço:** Salmão (120g), Mandioca (100g).\n* **Jantar:** Contra-filé (80g), Batata Sauté (200g).\n* **Ceia:** Iogurte + Mel.")
    with col_econ:
        st.success("💰 Opções Baratas")
        st.markdown("* **Proteína:** Ovos, Sobrecoxa de Frango, Fígado.\n* **Carbo:** Arroz e Feijão, Batata Doce.\n* **Fibras:** Farelo de Aveia.")

with tabs[4]:
    st.subheader("⚖️ Controle de Peso")
    p_val = st.number_input("Peso hoje (kg):", 40.0, 250.0, 145.0)
    if st.button("Gravar Peso"):
        with get_cursor() as cur:
            cur.execute("""INSERT INTO peso (data, peso_kg) VALUES (%s, %s) 
                           ON CONFLICT (data) DO UPDATE SET peso_kg = EXCLUDED.peso_kg""", 
                        (datetime.now().date(), float(p_val)))
        st.success("Peso registrado!")
    
    st.divider()
    if st.button("🚀 Sincronizar alimentos.csv"):
        try:
            df_csv = pd.read_csv('alimentos.csv', sep=';', encoding='latin-1')
            preparada = [(str(r.iloc[2]), limpar_valor_taco(r.iloc[4]), limpar_valor_taco(r.iloc[6]), 
                          limpar_valor_taco(r.iloc[9]), limpar_valor_taco(r.iloc[7])) for _, r in df_csv.iterrows()]
            with get_cursor() as cur:
                cur.execute("TRUNCATE TABLE tabela_taco")
                cur.executemany("INSERT INTO tabela_taco (alimento, kcal, proteina, carbo, gordura) VALUES (%s,%s,%s,%s,%s)", preparada)
            st.success("TACO Sincronizada!")
        except Exception as e: st.error(f"Erro: {e}")
