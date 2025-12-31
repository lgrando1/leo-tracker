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

# 3. METAS E INICIALIZAÇÃO
META_KCAL = 2000 
META_PROT = 160  

def inicializar_banco():
    with get_cursor() as cur:
        cur.execute("SET search_path TO public")
        cur.execute("CREATE TABLE IF NOT EXISTS tabela_taco (id SERIAL PRIMARY KEY, alimento TEXT, kcal REAL, proteina REAL, carbo REAL, gordura REAL);")
        cur.execute("""CREATE TABLE IF NOT EXISTS consumo (
            id SERIAL PRIMARY KEY, data_hora TIMESTAMP DEFAULT CURRENT_TIMESTAMP, 
            alimento TEXT, quantidade REAL, kcal REAL, proteina REAL, carbo REAL, gordura REAL, gluten TEXT DEFAULT 'Não informado'
        );""")
        cur.execute("CREATE TABLE IF NOT EXISTS peso (id SERIAL PRIMARY KEY, data DATE UNIQUE, peso_kg REAL);")

def limpar_valor_taco(valor):
    if pd.isna(valor) or str(valor).strip() in ['NA', 'TR', '', '*', '-']: return 0.0
    try: return float(str(valor).replace(',', '.'))
    except: return 0.0

try: inicializar_banco()
except Exception as e: st.error(f"Erro no banco: {e}"); st.stop()

# 5. INTERFACE
st.title("🦁 Leo Tracker Pro")
tabs = st.tabs(["🍽️ Registro", "🤖 IA Nutricional", "📈 Progresso", "📋 Plano & Sugestões", "⚖️ Peso & Admin"])

with tabs[0]:
    st.subheader("Busca Manual (TACO)")
    termo = st.text_input("🔍 Pesquisar alimento:")
    if termo:
        conn = get_connection()
        df_res = pd.read_sql("SELECT * FROM public.tabela_taco WHERE alimento ILIKE %s LIMIT 50", conn, params=(f'%{termo}%',))
        if not df_res.empty:
            escolha = st.selectbox("Selecione:", df_res["alimento"])
            dados = df_res[df_res["alimento"] == escolha].iloc[0]
            qtd = st.number_input("Gramas:", 0, 2000, 100)
            f = float(qtd) / 100.0
            if st.button("Salvar Alimento"):
                with get_cursor() as cur:
                    cur.execute("INSERT INTO consumo (alimento, quantidade, kcal, proteina, carbo, gordura) VALUES (%s,%s,%s,%s,%s,%s)", 
                                (escolha, float(qtd), dados['kcal']*f, dados['proteina']*f, dados['carbo']*f, dados['gordura']*f))
                st.success("Registrado!"); st.rerun()

with tabs[1]:
    st.subheader("🤖 Importar via IA")
    st.info("**Prompt:** Analise minha refeição (2000kcal/160g prot): [O QUE COMEU]. Retorne apenas o JSON: `[{\"alimento\": \"nome\", \"kcal\": 0, \"p\": 0, \"c\": 0, \"g\": 0, \"gluten\": \"...\"}]`")
    json_in = st.text_area("Cole o JSON aqui:", height=150)
    if st.button("Processar e Salvar"):
        try:
            dados = json.loads(json_in.replace('```json', '').replace('```', '').strip())
            with get_cursor() as cur:
                for i in dados:
                    cur.execute("INSERT INTO consumo (alimento, quantidade, kcal, proteina, carbo, gordura, gluten) VALUES (%s,1,%s,%s,%s,%s,%s)", 
                                (i['alimento'], i['kcal'], i['p'], i['c'], i['g'], i.get('gluten','Não informado')))
            st.success("Importado!"); st.rerun()
        except Exception as e: st.error(f"Erro: {e}")

with tabs[2]:
    st.subheader("📊 Progresso do Dia")
    df_hoje = pd.read_sql("SELECT * FROM consumo WHERE data_hora::date = CURRENT_DATE", get_connection())
    if not df_hoje.empty:
        c1, c2 = st.columns(2)
        k, p = df_hoje['kcal'].sum(), df_hoje['proteina'].sum()
        c1.metric("Energia", f"{int(k)}/{META_KCAL} kcal", f"{int(k-META_KCAL)}")
        c2.metric("Proteína", f"{int(p)}/{META_PROT}g", f"{int(p-META_PROT)}g")
        for _, r in df_hoje.iterrows():
            col_h1, col_h2, col_h3 = st.columns([1, 4, 1])
            col_h1.write(pd.to_datetime(r['data_hora']).strftime('%H:%M'))
            col_h2.write(f"**{r['alimento']}** - {int(r['kcal'])} kcal")
            if col_h3.button("🗑️", key=f"del_{r['id']}"):
                with get_cursor() as cur: cur.execute("DELETE FROM consumo WHERE id = %s", (r['id'],))
                st.rerun()

with tabs[3]:
    st.subheader("📋 Plano & Sugestões")
    c_o, c_e = st.columns(2)
    with c_o: st.info("**Original:** Salmão, Contra-filé, Quinoa, Whey.")
    with c_e: st.success("**Econômico:** Ovos, Frango, Fígado, Arroz/Feijão, Aveia.")

with tabs[4]:
    st.subheader("⚖️ Peso & Admin")
    p_v = st.number_input("Peso (kg):", 40.0, 250.0, 145.0)
    if st.button("Gravar Peso"):
        with get_cursor() as cur: cur.execute("INSERT INTO peso (data, peso_kg) VALUES (%s,%s) ON CONFLICT (data) DO UPDATE SET peso_kg=EXCLUDED.peso_kg", (datetime.now().date(), float(p_v)))
        st.success("Peso gravado!")
    
    st.divider()
    if st.button("🚀 Sincronizar TACO (Correção de Acentos)"):
        try:
            # Tenta ler com latin-1 que é comum em arquivos CSV de órgãos brasileiros (TACO)
            df_csv = pd.read_csv('alimentos.csv', sep=';', encoding='latin-1')
            preparada = []
            for _, r in df_csv.iterrows():
                # Forçamos a conversão para string e limpamos espaços
                nome_limpo = str(r.iloc[2]).strip()
                preparada.append((nome_limpo, limpar_valor_taco(r.iloc[4]), limpar_valor_taco(r.iloc[6]), limpar_valor_taco(r.iloc[9]), limpar_valor_taco(r.iloc[7])))
            
            with get_cursor() as cur:
                cur.execute("TRUNCATE TABLE tabela_taco")
                cur.executemany("INSERT INTO tabela_taco (alimento, kcal, proteina, carbo, gordura) VALUES (%s,%s,%s,%s,%s)", preparada)
            st.success("TACO Sincronizada com acentos corrigidos!")
        except Exception as e: st.error(f"Erro: {e}")
