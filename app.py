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

# 3. FUNÇÕES DE BANCO DE DADOS E ADMINISTRAÇÃO
def inicializar_banco():
    with conn.cursor() as cur:
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
        cur.execute("""
            CREATE TABLE IF NOT EXISTS peso (
                id SERIAL PRIMARY KEY, 
                data DATE, 
                peso_kg REAL
            );
        """)
        conn.commit()

def limpar_valor_taco(valor):
    if pd.isna(valor) or str(valor).strip().upper() in ['NA', 'TR', '']:
        return 0.0
    try:
        return float(str(valor).replace(',', '.'))
    except:
        return 0.0

def carregar_csv_completo():
    try:
        if not os.path.exists('alimentos.csv'):
            st.error("❌ Arquivo 'alimentos.csv' não encontrado na raiz do GitHub.")
            st.info(f"Arquivos detectados: {os.listdir('.')}")
            return False

        try:
            df = pd.read_csv('alimentos.csv', encoding='latin-1', sep=';')
        except:
            df = pd.read_csv('alimentos.csv', encoding='utf-8', sep=';')

        tabela_limpa = []
        for _, row in df.iterrows():
            nome_alimento = row.get('Descrição dos alimentos', 'Sem Nome')
            kcal = limpar_valor_taco(row.get('Energia (kcal)', 0))
            prot = limpar_valor_taco(row.get('Proteína (g)', 0))
            carb = limpar_valor_taco(row.get('Carboidrato (g)', 0))
            gord = limpar_valor_taco(row.get('Lipídeos (g)', 0))
            tabela_limpa.append((str(nome_alimento), kcal, prot, carb, gord))

        with conn.cursor() as cur:
            cur.execute("TRUNCATE TABLE tabela_taco")
            cur.executemany(
                "INSERT INTO tabela_taco (alimento, kcal, proteina, carbo, gordura) VALUES (%s, %s, %s, %s, %s)", 
                tabela_limpa
            )
            conn.commit()
        return True
    except Exception as e:
        st.error(f"Erro crítico no processamento: {e}")
        return False

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

with tab_admin:
    st.subheader("⚙️ Painel de Administração")
    if os.path.exists('alimentos.csv'):
        st.success("✅ Arquivo 'alimentos.csv' detectado e pronto para carga.")
    else:
        st.error("⚠️ O arquivo 'alimentos.csv' não foi detectado no repositório.")
        st.info(f"Arquivos no diretório: {os.listdir('.')}")

    if st.button("🚀 Sincronizar Alimentos do CSV"):
        with st.spinner("Processando CSV..."):
            if carregar_csv_completo():
                st.success("Tabela TACO atualizada com sucesso!")
                st.rerun()
