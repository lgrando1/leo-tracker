import streamlit as st
import pandas as pd
import psycopg2
from datetime import datetime, timedelta
import plotly.express as px

# 1. CONFIGURAÇÃO DA PÁGINA
st.set_page_config(page_title="Leo Tracker Pro", page_icon="🦁", layout="wide")

# 2. CONEXÃO NEON (Lendo dos Secrets)
@st.cache_resource
def init_connection():
    return psycopg2.connect(st.secrets["DATABASE_URL"])

try:
    conn = init_connection()
except Exception as e:
    st.error("Erro ao conectar ao Banco de Dados. Verifique os Secrets.")
    st.stop()

# 3. FUNÇÕES DE BANCO DE DADOS (CRIAÇÃO E POPULAÇÃO)
def inicializar_banco():
    with conn.cursor() as cur:
        # Tabela TACO
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tabela_taco (
                id SERIAL PRIMARY KEY,
                alimento TEXT,
                kcal REAL,
                proteina REAL,
                carbo REAL,
                gordura REAL
            );
        """)
        # Tabela Consumo
        cur.execute("""
            CREATE TABLE IF NOT EXISTS consumo (
                id SERIAL PRIMARY KEY, 
                data DATE, 
                alimento TEXT, 
                quantidade REAL, 
                kcal REAL, 
                proteina REAL, 
                carbo REAL, 
                gordura REAL
            );
        """)
        # Tabela Peso
        cur.execute("""
            CREATE TABLE IF NOT EXISTS peso (
                id SERIAL PRIMARY KEY, 
                data DATE, 
                peso_kg REAL
            );
        """)
        
        # Popular TACO se estiver vazia
        cur.execute("SELECT COUNT(*) FROM tabela_taco")
        if cur.fetchone()[0] == 0:
            dados = [
                ('Arroz Branco Cozido', 128, 2.5, 28.1, 0.2),
                ('Feijão Carioca Cozido', 76, 4.8, 13.6, 0.5),
                ('Peito de Frango Grelhado', 159, 32.0, 0.0, 2.5),
                ('Patinho Grelhado', 219, 35.9, 0.0, 7.3),
                ('Ovo Cozido', 146, 13.3, 0.6, 9.5),
                ('Batata Doce Cozida', 77, 0.6, 18.4, 0.1),
                ('Mandioca Cozida', 125, 0.6, 30.1, 0.3),
                ('Banana Prata', 98, 1.3, 26.0, 0.1),
                ('Whey Protein', 400, 80.0, 5.0, 2.0)
            ]
            cur.executemany("INSERT INTO tabela_taco (alimento, kcal, proteina, carbo, gordura) VALUES (%s, %s, %s, %s, %s)", dados)
        
        conn.commit()

# Funções de Leitura Segura
def buscar_alimento(termo):
    if not termo: return pd.DataFrame()
    return pd.read_sql("SELECT * FROM tabela_taco WHERE alimento ILIKE %s LIMIT 15", conn, params=(f'%{termo}%',))

def ler_dados_periodo(dias=30):
    data_inicio = (datetime.now() - timedelta(days=dias)).date()
    try:
        return pd.read_sql("SELECT * FROM consumo WHERE data >= %s ORDER BY data DESC", conn, params=(data_inicio,))
    except:
        return pd.DataFrame()

def ler_peso():
    try:
        return pd.read_sql("SELECT * FROM peso ORDER BY data ASC", conn)
    except:
        return pd.DataFrame()

# 4. INICIALIZAÇÃO
inicializar_banco()

# 5. ESTIMADOR DE MEDIDAS
MEDIDAS_CASEIRAS = {
    "arroz": {"unidade": "Colher de Sopa Cheia", "g": 25},
    "feijão": {"unidade": "Concha Média", "g": 86},
    "frango": {"unidade": "Filé Médio", "g": 100},
    "carne": {"unidade": "Bife Médio", "g": 100},
    "carne moida": {"unidade": "Colher de Sopa", "g": 30},
    "batata doce": {"unidade": "Fatia Média/Rodela", "g": 40},
    "mandioca": {"unidade": "Pedaço Médio", "g": 50},
    "aveia": {"unidade": "Colher de Sopa", "g": 15},
    "azeite": {"unidade": "Fio / Colher Sobremesa", "g": 8},
    "whey": {"unidade": "Dosador (Scoop)", "g": 30},
    "banana": {"unidade": "Unidade Média", "g": 60},
    "ovo": {"unidade": "Unidade", "g": 50}
}

# --- INTERFACE ---
st.title("🦁 Leo Tracker Pro")
tab_prato, tab_dash, tab_peso = st.tabs(["🍽️ Montar Prato", "📊 Dashboard", "⚖️ Peso"])

with tab_prato:
    st.subheader("O que comeu hoje?")
    termo = st.text_input("🔍 Pesquisar alimento:")
    if termo:
        df_res = buscar_alimento(termo)
        if not df_res.empty:
            escolha = st.selectbox("Selecione:", df_res["alimento"])
            dados = df_res[df_res["alimento"] == escolha].iloc[0]
            
            tipo = st.radio("Medir por:", ["Medida Caseira", "Gramas"], horizontal=True)
            if tipo == "Gramas":
                qtd = st.number_input("Peso (g):", 0, 1000, 100)
            else:
                med = next((v for k, v in MEDIDAS_CASEIRAS.items() if k in escolha.lower()), {"unidade": "Grama", "g": 1})
                unid = st.number_input(f"Quantas {med['unidade']}?", 0.0, 10.0, 1.0)
                qtd = unid * med['g']
            
            fator = qtd / 100
            macros = {'k': round(dados['kcal']*fator), 'p': round(dados['proteina']*fator,1), 'c': round(dados['carbo']*fator,1), 'g': round(dados['gordura']*fator,1)}
            
            st.info(f"🥘 **Resumo:** {macros['k']} kcal | P: {macros['p']}g | C: {macros['c']}g")
            if st.button("Confirmar Refeição"):
                with conn.cursor() as cur:
                    cur.execute("INSERT INTO consumo (data, alimento, quantidade, kcal, proteina, carbo, gorduara) VALUES (%s,%s,%s,%s,%s,%s,%s)", 
                                (datetime.now().date(), escolha, qtd, macros['k'], macros['p'], macros['c'], macros['g']))
                    conn.commit()
                st.success("Salvo!")
                st.rerun()

with tab_dash:
    df_dados = ler_dados_periodo(30)
    if not df_dados.empty:
        df_dados['data'] = pd.to_datetime(df_dados['data'])
        df_dia = df_dados.groupby('data')[['kcal', 'proteina']].sum().reset_index()
        fig = px.bar(df_dia, x='data', y='kcal', color='kcal', title="Calorias Diárias")
        st.plotly_chart(fig, use_container_width=True)
        st.dataframe(df_dados)
    else:
        st.info("Registe a sua primeira refeição para ver o gráfico!")

with tab_peso:
    p_input = st.number_input("Peso (kg):", 50.0, 200.0, 146.0)
    if st.button("Gravar Peso"):
        with conn.cursor() as cur:
            cur.execute("INSERT INTO peso (data, peso_kg) VALUES (%s, %s)", (datetime.now().date(), p_input))
            conn.commit()
        st.success("Peso gravado!")
        st.rerun()
    
    df_p = ler_peso()
    if not df_p.empty:
        st.line_chart(df_p, x='data', y='peso_kg')
