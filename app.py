import streamlit as st
import pandas as pd
import psycopg2
from datetime import datetime, timedelta
import plotly.express as px
import os
import unicodedata

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

# 3. FUNÇÕES AUXILIARES DE LIMPEZA
def remover_acentos(texto):
    if not isinstance(texto, str): return str(texto)
    # Normaliza para remover acentos e caracteres especiais
    nfkd_form = unicodedata.normalize('NFKD', texto)
    return "".join([c for c in nfkd_form if not unicodedata.combining(c)]).lower().strip()

def limpar_valor_taco(valor):
    if pd.isna(valor) or str(valor).strip().upper() in ['NA', 'TR', '', '-']:
        return 0.0
    try:
        # Converte padrão brasileiro (70,1) para americano (70.1)
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
            st.error("❌ Arquivo 'alimentos.csv' não encontrado no repositório.")
            return False

        # Tenta ler o CSV com encoding Latin-1 (comum em arquivos brasileiros)
        df = pd.read_csv('alimentos.csv', encoding='latin-1', sep=';')
        
        # Cria um mapa: { 'nome_limpo': 'Nome Original Da Coluna No CSV' }
        mapa_colunas = {remover_acentos(c): c for c in df.columns}
        colunas_limpas = mapa_colunas.keys()

        # Procura as colunas necessárias usando termos parciais e sem acentos
        c_nome = next((mapa_colunas[c] for c in colunas_limpas if 'descricao' in c), None)
        c_kcal = next((mapa_colunas[c] for c in colunas_limpas if 'kcal' in c), None)
        c_prot = next((mapa_colunas[c] for c in colunas_limpas if 'proteina' in c), None)
        c_carb = next((mapa_colunas[c] for c in colunas_limpas if 'carboidrato' in c), None)
        c_gord = next((mapa_colunas[c] for c in colunas_limpas if 'lipideos' in c or 'gordura' in c), None)

        if not all([c_nome, c_kcal, c_prot, c_carb, c_gord]):
            st.error("❌ Não foi possível identificar as colunas obrigatórias no CSV.")
            st.write("Colunas detectadas:", list(df.columns))
            return False

        tabela_preparada = []
        for _, row in df.iterrows():
            tabela_preparada.append((
                str(row[c_nome]),
                limpar_valor_taco(row[c_kcal]),
                limpar_valor_taco(row[c_prot]),
                limpar_valor_taco(row[c_carb]),
                limpar_valor_taco(row[c_gord])
            ))

        with conn.cursor() as cur:
            cur.execute("TRUNCATE TABLE tabela_taco")
            cur.executemany(
                "INSERT INTO tabela_taco (alimento, kcal, proteina, carbo, gordura) VALUES (%s, %s, %s, %s, %s)", 
                tabela_preparada
            )
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

# 5. INICIALIZAÇÃO
inicializar_banco()

# 6. INTERFACE
st.title("🦁 Leo Tracker Pro")
tab_prato, tab_dash, tab_peso, tab_admin = st.tabs(["🍽️ Montar Prato", "📊 Dashboard", "⚖️ Peso", "⚙️ Admin"])

with tab_prato:
    st.subheader("O que comeu hoje?")
    termo = st.text_input("🔍 Pesquisar alimento (ex: arroz, peito, ovo):")
    if termo:
        df_res = buscar_alimento(termo)
        if not df_res.empty:
            escolha = st.selectbox("Selecione:", df_res["alimento"])
            dados = df_res[df_res["alimento"] == escolha].iloc[0]
            qtd = st.number_input("Peso (g):", 0, 1000, 100)
            fator = qtd / 100
            k, p, c, g = round(dados['kcal']*fator), round(dados['proteina']*fator,1), round(dados['carbo']*fator,1), round(dados['gordura']*fator,1)
            st.info(f"🥘 {k} kcal | P: {p}g | C: {c}g | G: {g}g")
            if st.button("Salvar Refeição"):
                with conn.cursor() as cur:
                    cur.execute("INSERT INTO consumo (data, alimento, quantidade, kcal, proteina, carbo, gordura) VALUES (%s,%s,%s,%s,%s,%s,%s)", 
                                (datetime.now().date(), escolha, qtd, k, p, c, g))
                    conn.commit()
                st.success("Registrado!")

with tab_dash:
    df_dados = ler_dados_periodo(30)
    if not df_dados.empty:
        df_dados['data'] = pd.to_datetime(df_dados['data'])
        fig = px.bar(df_dados.groupby('data')['kcal'].sum().reset_index(), x='data', y='kcal', color='kcal', title="Calorias Diárias")
        st.plotly_chart(fig, use_container_width=True)
        st.dataframe(df_dados)

with tab_peso:
    p_in = st.number_input("Peso Atual (kg):", 50.0, 200.0, 145.0)
    if st.button("Gravar Peso"):
        with conn.cursor() as cur:
            cur.execute("INSERT INTO peso (data, peso_kg) VALUES (%s, %s)", (datetime.now().date(), p_in))
            conn.commit()
        st.success("Peso gravado!")

with tab_admin:
    st.subheader("⚙️ Administração")
    if st.button("🚀 Sincronizar Alimentos (alimentos.csv -> Neon)"):
        with st.spinner("Processando..."):
            if carregar_csv_completo():
                st.success("Base de dados TACO sincronizada com sucesso!")
                st.rerun()
