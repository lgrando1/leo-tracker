import streamlit as st
import pandas as pd
import psycopg2
from datetime import datetime, timedelta
import plotly.express as px
import os

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

# 3. FUNÇÕES AUXILIARES
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

        # Lendo o CSV forçando o delimitador correto
        df = pd.read_csv('alimentos.csv', sep=';', encoding='utf-8')

        # Se a leitura falhar com utf-8, tenta latin-1
        if len(df.columns) < 5:
            df = pd.read_csv('alimentos.csv', sep=';', encoding='latin-1')

        # ESTRATÉGIA POR ÍNDICE (Baseado no seu Log):
        # 2: Descrição, 4: Energia(kcal), 6: Proteína, 7: Lipídeos, 9: Carboidrato
        tabela_preparada = []
        for _, row in df.iterrows():
            tabela_preparada.append((
                str(row.iloc[2]),               # Coluna 2: Descrição
                limpar_valor_taco(row.iloc[4]),  # Coluna 4: Kcal
                limpar_valor_taco(row.iloc[6]),  # Coluna 6: Proteína
                limpar_valor_taco(row.iloc[9]),  # Coluna 9: Carboidrato
                limpar_valor_taco(row.iloc[7])   # Coluna 7: Lipídeos (Gordura)
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
    termo = st.text_input("🔍 Pesquisar alimento:")
    if termo:
        df_res = buscar_alimento(termo)
        if not df_res.empty:
            escolha = st.selectbox("Selecione:", df_res["alimento"])
            dados = df_res[df_res["alimento"] == escolha].iloc[0]
            
            qtd = st.number_input("Peso (g):", 0, 1000, 100)
            fator = qtd / 100
            
            k = round(dados['kcal']*fator)
            p = round(dados['proteina']*fator, 1)
            c = round(dados['carbo']*fator, 1)
            g = round(dados['gordura']*fator, 1)
            
            st.info(f"🥘 {k} kcal | P: {p}g | C: {c}g | G: {g}g")
            
            if st.button("Salvar Refeição"):
                with conn.cursor() as cur:
                    cur.execute("INSERT INTO consumo (data, alimento, quantidade, kcal, proteina, carbo, gordura) VALUES (%s,%s,%s,%s,%s,%s,%s)", 
                                (datetime.now().date(), escolha, qtd, k, p, c, g))
                    conn.commit()
                st.success("Registrado!")
                st.rerun()

with tab_dash:
    df_dados = ler_dados_periodo(30)
    if not df_dados.empty:
        df_dados['data'] = pd.to_datetime(df_dados['data'])
        fig = px.bar(df_dados.groupby('data')['kcal'].sum().reset_index(), x='data', y='kcal', color='kcal', title="Calorias Diárias")
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
    st.subheader("⚙️ Admin")
    if st.button("🚀 Sincronizar Alimentos (CSV -> Banco)"):
        with st.spinner("Processando..."):
            if carregar_csv_completo():
                st.success("Sincronização concluída!")
                st.rerun()
