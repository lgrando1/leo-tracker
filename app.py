import streamlit as st
import pandas as pd
import psycopg2
from datetime import datetime, timedelta
import plotly.express as px
import os

# 1. CONFIGURAÇÃO DA PÁGINA
st.set_page_config(page_title="Leo Tracker Pro", page_icon="🦁", layout="wide")

# --- SISTEMA DE LOGIN ---
def check_password():
    """Retorna True se o usuário inseriu a senha correta."""
    if "password_correct" not in st.session_state:
        st.session_state["password_correct"] = False

    if st.session_state["password_correct"]:
        return True

    st.title("🦁 Leo Tracker Login")
    password = st.text_input("Insira a senha para acessar seu painel:", type="password")
    
    if st.button("Entrar"):
        if password == st.secrets["PASSWORD"]:
            st.session_state["password_correct"] = True
            st.rerun()
        else:
            st.error("Senha incorreta!")
    return False

if not check_password():
    st.stop()  # Interrompe a execução aqui se não estiver logado

# 2. CONEXÃO NEON
@st.cache_resource
def init_connection():
    return psycopg2.connect(st.secrets["DATABASE_URL"])

try:
    conn = init_connection()
except Exception as e:
    st.error("Erro ao conectar ao Banco de Dados.")
    st.stop()

# 3. FUNÇÕES DE BANCO DE DADOS
def inicializar_banco():
    try:
        with conn.cursor() as cur:
            conn.rollback() 
            cur.execute("SET search_path TO public")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS public.tabela_taco (
                    id SERIAL PRIMARY KEY, alimento TEXT, kcal REAL, proteina REAL, carbo REAL, gordura REAL
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS public.consumo (
                    id SERIAL PRIMARY KEY, data DATE, alimento TEXT, quantidade REAL, kcal REAL, proteina REAL, carbo REAL, gordura REAL
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS public.peso (
                    id SERIAL PRIMARY KEY, data DATE, peso_kg REAL
                );
            """)
            conn.commit()
    except Exception as e:
        conn.rollback()

def limpar_valor_taco(valor):
    if pd.isna(valor) or str(valor).strip().upper() in ['NA', 'TR', '', '-']:
        return 0.0
    try:
        return float(str(valor).replace(',', '.'))
    except:
        return 0.0

def carregar_csv_completo():
    try:
        if not os.path.exists('alimentos.csv'): return False
        df = pd.read_csv('alimentos.csv', sep=';', encoding='latin-1')
        tabela_preparada = []
        for _, row in df.iterrows():
            tabela_preparada.append((
                str(row.iloc[2]), float(limpar_valor_taco(row.iloc[4])),  
                float(limpar_valor_taco(row.iloc[6])), float(limpar_valor_taco(row.iloc[9])), float(limpar_valor_taco(row.iloc[7]))   
            ))
        with conn.cursor() as cur:
            conn.rollback()
            cur.execute("SET search_path TO public")
            cur.execute("TRUNCATE TABLE public.tabela_taco")
            cur.executemany("INSERT INTO public.tabela_taco (alimento, kcal, proteina, carbo, gordura) VALUES (%s, %s, %s, %s, %s)", tabela_preparada)
            conn.commit()
        return True
    except:
        conn.rollback()
        return False

def buscar_alimento(termo):
    if not termo: return pd.DataFrame()
    try:
        return pd.read_sql("SELECT * FROM public.tabela_taco WHERE alimento ILIKE %s ORDER BY alimento ASC LIMIT 50", conn, params=(f'%{termo}%',))
    except:
        conn.rollback()
        return pd.DataFrame()

def ler_dados_periodo(dias=30):
    data_inicio = (datetime.now() - timedelta(days=dias)).date()
    try:
        return pd.read_sql("SELECT * FROM public.consumo WHERE data >= %s ORDER BY data DESC", conn, params=(data_inicio,))
    except:
        conn.rollback()
        return pd.DataFrame()

def ler_peso():
    try:
        return pd.read_sql("SELECT data, peso_kg FROM public.peso ORDER BY data DESC", conn)
    except:
        conn.rollback()
        return pd.DataFrame()

# 4. INICIALIZAÇÃO
inicializar_banco()

# 5. INTERFACE PRINCIPAL
st.title("🦁 Leo Tracker Pro")
tab_prato, tab_dash, tab_peso, tab_admin = st.tabs(["🍽️ Montar Prato", "📊 Dashboard", "⚖️ Peso", "⚙️ Admin"])

with tab_prato:
    st.subheader("O que comeu hoje?")
    termo = st.text_input("🔍 Pesquisar alimento:")
    if termo:
        df_res = buscar_alimento(termo)
        if not df_res.empty:
            escolha = st.selectbox("Selecione:", df_res["alimento"])
            dados = df_res[df_res["alimento"] == escolha].iloc[0]
            qtd = st.number_input("Peso (g):", 0, 2000, 100)
            fator = float(qtd) / 100.0
            k, p, c, g = float(round(float(dados['kcal']) * fator)), float(round(float(dados['proteina']) * fator, 1)), float(round(float(dados['carbo']) * fator, 1)), float(round(float(dados['gordura']) * fator, 1))
            st.info(f"🥘 {k} kcal | P: {p}g | C: {c}g | G: {g}g")
            if st.button("Confirmar e Salvar"):
                try:
                    with conn.cursor() as cur:
                        conn.rollback()
                        cur.execute("SET search_path TO public")
                        cur.execute("INSERT INTO public.consumo (data, alimento, quantidade, kcal, proteina, carbo, gordura) VALUES (%s,%s,%s,%s,%s,%s,%s)", (datetime.now().date(), str(escolha), float(qtd), k, p, c, g))
                        conn.commit()
                    st.success("Salvo!")
                    st.rerun()
                except Exception as e:
                    conn.rollback()
                    st.error(f"Erro ao salvar: {e}")

with tab_dash:
    df_dados = ler_dados_periodo(30)
    if not df_dados.empty:
        df_dados['data'] = pd.to_datetime(df_dados['data'])
        fig = px.bar(df_dados.groupby('data')['kcal'].sum().reset_index(), x='data', y='kcal', title="Consumo Diário", color_discrete_sequence=['#FF4B4B'])
        st.plotly_chart(fig, use_container_width=True)
        st.dataframe(df_dados, use_container_width=True)

with tab_peso:
    col1, col2 = st.columns([1, 2])
    with col1:
        st.subheader("Novo Registro")
        p_in = st.number_input("Peso (kg):", 40.0, 250.0, 145.0)
        data_p = st.date_input("Data:", datetime.now())
        if st.button("Gravar Peso"):
            try:
                with conn.cursor() as cur:
                    conn.rollback()
                    cur.execute("SET search_path TO public")
                    cur.execute("INSERT INTO public.peso (data, peso_kg) VALUES (%s, %s)", (data_p, float(p_in)))
                    conn.commit()
                st.success("Gravado!")
                st.rerun()
            except:
                conn.rollback()
    with col2:
        df_p = ler_peso()
        if not df_p.empty:
            st.line_chart(df_p.set_index('data')['peso_kg'])
            st.dataframe(df_p, use_container_width=True)

with tab_admin:
    st.subheader("🔧 Admin")
    with st.expander("➕ Cadastrar Manualmente"):
        n = st.text_input("Nome:")
        kcal = st.number_input("Kcal/100g", 0.0)
        if st.button("Adicionar"):
            with conn.cursor() as cur:
                conn.rollback()
                cur.execute("INSERT INTO public.tabela_taco (alimento, kcal, proteina, carbo, gordura) VALUES (%s,%s,0,0,0)", (n, kcal))
                conn.commit()
            st.success("Adicionado!")
    if st.button("🚀 Sincronizar CSV"):
        if carregar_csv_completo():
            st.success("Sincronizado!")
            st.rerun()
