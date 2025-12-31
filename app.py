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

        # Tenta ler o CSV com diferentes encodings
        df = None
        for enc in ['latin-1', 'utf-8', 'iso-8859-1']:
            try:
                df = pd.read_csv('alimentos.csv', encoding=enc, sep=';')
                if len(df.columns) > 1: break
            except:
                continue

        if df is None or len(df.columns) <= 1:
            st.error("❌ Não foi possível ler o arquivo CSV. Verifique o separador (;) e o formato.")
            return False

        # BUSCA ROBUSTA DE COLUNAS (Ignora acentos, espaços e caracteres especiais)
        def encontrar_coluna(df_cols, palavras_chave):
            for col in df_cols:
                # Normalização extrema: remove tudo que não é letra/número
                col_normalizada = "".join(filter(str.isalnum, str(col))).lower()
                for p in palavras_chave:
                    if p in col_normalizada:
                        return col
            return None

        c_nome = encontrar_coluna(df.columns, ['descri', 'alimento'])
        c_kcal = encontrar_coluna(df.columns, ['kcal', 'energi'])
        c_prot = encontrar_coluna(df.columns, ['prote'])
        c_carb = encontrar_coluna(df.columns, ['carbo'])
        c_gord = encontrar_coluna(df.columns, ['lipid', 'gordur'])

        if not all([c_nome, c_kcal, c_prot, c_carb, c_gord]):
            st.error("❌ Não foi possível identificar as colunas obrigatórias.")
            st.write("Colunas detectadas no arquivo:", list(df.columns))
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
        st.error(f"Erro crítico no processamento: {e}")
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
    "batata doce": {"unidade": "Fatia Média/Rodela", "g": 40},
    "mandioca": {"unidade": "Pedaço Médio", "g": 50},
    "aveia": {"unidade": "Colher de Sopa", "g": 15},
    "azeite": {"unidade": "Fio / Colher Sobremesa", "g": 8},
    "whey": {"unidade": "Dosador (Scoop)", "g": 30},
    "banana": {"unidade": "Unidade Média", "g": 60},
    "ovo": {"unidade": "Unidade", "g": 50}
}

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
            
            tipo = st.radio("Medir por:", ["Medida Caseira", "Gramas"], horizontal=True)
            if tipo == "Gramas":
                qtd = st.number_input("Peso (g):", 0, 1000, 100)
            else:
                med = next((v for k, v in MEDIDAS_CASEIRAS.items() if k in escolha.lower()), {"unidade": "Grama", "g": 1})
                unid = st.number_input(f"Quantas {med['unidade']}?", 0.0, 10.0, 1.0)
                qtd = unid * med['g']
            
            fator = qtd / 100
            macros = {
                'k': round(dados['kcal']*fator), 
                'p': round(dados['proteina']*fator,1), 
                'c': round(dados['carbo']*fator,1), 
                'g': round(dados['gordura']*fator,1)
            }
            
            st.info(f"🥘 **Resumo:** {macros['k']} kcal | P: {macros['p']}g | C: {macros['c']}g")
            if st.button("Confirmar Refeição"):
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO consumo (data, alimento, quantidade, kcal, proteina, carbo, gordura) VALUES (%s,%s,%s,%s,%s,%s,%s)", 
                        (datetime.now().date(), escolha, qtd, macros['k'], macros['p'], macros['c'], macros['g'])
                    )
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
        st.info("Registre a sua primeira refeição para ver o gráfico!")

with tab_peso:
    p_input = st.number_input("Peso Atual (kg):", 50.0, 200.0, 145.0)
    if st.button("Gravar Peso"):
        with conn.cursor() as cur:
            cur.execute("INSERT INTO peso (data, peso_kg) VALUES (%s, %s)", (datetime.now().date(), p_input))
            conn.commit()
        st.success("Peso gravado!")
        st.rerun()
    
    df_p = ler_peso()
    if not df_p.empty:
        st.line_chart(df_p, x='data', y='peso_kg')

with tab_admin:
    st.subheader("⚙️ Administração")
    if st.button("🚀 Sincronizar Alimentos (CSV -> Banco)"):
        with st.spinner("Processando..."):
            if carregar_csv_completo():
                st.success("Sincronização concluída com sucesso!")
                st.rerun()
