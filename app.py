import streamlit as st
import pandas as pd
import psycopg2
from datetime import datetime, timedelta
import plotly.express as px
import os
import unicodedata

# 1. CONFIGURAÇÃO DA PÁGINA
st.set_page_config(page_title="Leo Tracker Pro", page_icon="🦁", layout="wide")

# 2. CONEXÃO NEON
@st.cache_resource
def init_connection():
    return psycopg2.connect(st.secrets["DATABASE_URL"])

try:
    conn = init_connection()
except Exception as e:
    st.error("Erro ao conectar ao Banco de Dados. Verifique os Secrets.")
    st.stop()

# 3. FUNÇÕES AUXILIARES
def remover_acentos(texto):
    if not isinstance(texto, str): return str(texto)
    return "".join(c for c in unicodedata.normalize('NFD', texto) if unicodedata.category(c) != 'Mn').lower()

def limpar_valor_taco(valor):
    if pd.isna(valor) or str(valor).strip().upper() in ['NA', 'TR', '', '-']:
        return 0.0
    try:
        return float(str(valor).replace(',', '.'))
    except:
        return 0.0

# 4. FUNÇÕES DE BANCO DE DADOS
def inicializar_banco():
    with conn.cursor() as cur:
        cur.execute("CREATE TABLE IF NOT EXISTS tabela_taco (id SERIAL PRIMARY KEY, alimento TEXT, kcal REAL, proteina REAL, carbo REAL, gordura REAL);")
        cur.execute("CREATE TABLE IF NOT EXISTS consumo (id SERIAL PRIMARY KEY, data DATE, alimento TEXT, quantidade REAL, kcal REAL, proteina REAL, carbo REAL, gordura REAL);")
        cur.execute("CREATE TABLE IF NOT EXISTS peso (id SERIAL PRIMARY KEY, data DATE, peso_kg REAL);")
        conn.commit()

def carregar_csv_completo():
    try:
        if not os.path.exists('alimentos.csv'):
            st.error("❌ Arquivo 'alimentos.csv' não encontrado.")
            return False

        # Tenta ler o CSV
        df = pd.read_csv('alimentos.csv', encoding='latin-1', sep=';')
        
        # LIMPEZA RADICAL DAS COLUNAS
        # Transforma "Descrição dos alimentos" em "descricao dos alimentos"
        # Transforma "Proteína (g)" em "proteina (g)"
        mapeamento_original = {c: remover_acentos(c) for c in df.columns}
        colunas_limpas = list(mapeamento_original.values())

        # Procura as colunas pelos nomes simplificados
        col_nome_limpa = next((c for c in colunas_limpas if 'descricao' in c), None)
        col_kcal_limpa = next((c for c in colunas_limpas if 'kcal' in c), None)
        col_prot_limpa = next((c for c in colunas_limpas if 'proteina' in c), None)
        col_carb_limpa = next((c for c in colunas_limpas if 'carboidrato' in c), None)
        col_gord_limpa = next((c for c in colunas_limpas if 'lipideos' in c or 'gordura' in c), None)

        # Recupera o nome original para acessar o dataframe
        def get_original(limpo):
            return [k for k, v in mapeamento_original.items() if v == limpo][0]

        if not all([col_nome_limpa, col_kcal_limpa, col_prot_limpa, col_carb_limpa, col_gord_limpa]):
            st.error(f"Colunas detectadas: {colunas_limpas}")
            return False

        tabela_limpa = []
        for _, row in df.iterrows():
            tabela_limpa.append((
                str(row[get_original(col_nome_limpa)]),
                limpar_valor_taco(row[get_original(col_kcal_limpa)]),
                limpar_valor_taco(row[get_original(col_prot_limpa)]),
                limpar_valor_taco(row[get_original(col_carb_limpa)]),
                limpar_valor_taco(row[get_original(col_gord_limpa)])
            ))

        with conn.cursor() as cur:
            cur.execute("TRUNCATE TABLE tabela_taco")
            cur.executemany("INSERT INTO tabela_taco (alimento, kcal, proteina, carbo, gordura) VALUES (%s, %s, %s, %s, %s)", tabela_limpa)
            conn.commit()
        return True
    except Exception as e:
        st.error(f"Erro ao processar: {e}")
        return False

def buscar_alimento(termo):
    if not termo: return pd.DataFrame()
    return pd.read_sql("SELECT * FROM tabela_taco WHERE alimento ILIKE %s LIMIT 20", conn, params=(f'%{termo}%',))

def ler_dados_periodo(dias=30):
    data_inicio = (datetime.now() - timedelta(days=dias)).date()
    try:
        return pd.read_sql("SELECT * FROM consumo WHERE data >= %s ORDER BY data DESC", conn, params=(data_inicio,))
    except:
        return pd.DataFrame()

# 5. INICIALIZAÇÃO E INTERFACE
inicializar_banco()

st.title("🦁 Leo Tracker Pro")
tab_prato, tab_dash, tab_peso, tab_admin = st.tabs(["🍽️ Montar Prato", "📊 Dashboard", "⚖️ Peso", "⚙️ Admin"])

with tab_prato:
    termo = st.text_input("🔍 Pesquisar alimento:")
    if termo:
        df_res = buscar_alimento(termo)
        if not df_res.empty:
            escolha = st.selectbox("Selecione:", df_res["alimento"])
            dados = df_res[df_res["alimento"] == escolha].iloc[0]
            qtd = st.number_input("Peso (g):", 0, 1000, 100)
            fator = qtd / 100
            k, p, c = round(dados['kcal']*fator), round(dados['proteina']*fator,1), round(dados['carbo']*fator,1)
            st.info(f"🥘 {k} kcal | P: {p}g | C: {c}g")
            if st.button("Salvar"):
                with conn.cursor() as cur:
                    cur.execute("INSERT INTO consumo (data, alimento, quantidade, kcal, proteina, carbo, gordura) VALUES (%s,%s,%s,%s,%s,%s,%s)", 
                                (datetime.now().date(), escolha, qtd, k, p, c, round(dados['gordura']*fator,1)))
                    conn.commit()
                st.success("Registado!")

with tab_dash:
    df_dados = ler_dados_periodo(30)
    if not df_dados.empty:
        df_dados['data'] = pd.to_datetime(df_dados['data'])
        fig = px.bar(df_dados.groupby('data')['kcal'].sum().reset_index(), x='data', y='kcal', title="Calorias Diárias")
        st.plotly_chart(fig, use_container_width=True)
        st.dataframe(df_dados)

with tab_peso:
    p_in = st.number_input("Peso (kg):", 50.0, 200.0, 145.0)
    if st.button("Gravar Peso"):
        with conn.cursor() as cur:
            cur.execute("INSERT INTO peso (data, peso_kg) VALUES (%s, %s)", (datetime.now().date(), p_in))
            conn.commit()
        st.success("Peso gravado!")

with tab_admin:
    if st.button("🚀 Sincronizar Base de Dados (alimentos.csv)"):
        if carregar_csv_completo():
            st.success("Base de dados TACO carregada com sucesso!")
