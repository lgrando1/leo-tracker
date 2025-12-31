import streamlit as st
import pandas as pd
import psycopg2
from datetime import datetime, timedelta
import plotly.express as px
import os
import json

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

# 2. CONEXÃO NEON
@st.cache_resource
def init_connection():
    return psycopg2.connect(st.secrets["DATABASE_URL"])

try:
    conn = init_connection()
except:
    st.error("Erro ao conectar ao banco de dados.")
    st.stop()

# 3. METAS DA NUTRICIONISTA (Exemplo de Configuração)
META_KCAL = 2000
META_PROT = 160
META_CARB = 200
META_GORD = 70

# 4. FUNÇÕES DE BANCO DE DADOS
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
                    id SERIAL PRIMARY KEY, data_hora TIMESTAMP DEFAULT CURRENT_TIMESTAMP, 
                    alimento TEXT, quantidade REAL, kcal REAL, proteina REAL, carbo REAL, gordura REAL, 
                    gluten TEXT DEFAULT 'Não informado'
                );
            """)
            cur.execute("CREATE TABLE IF NOT EXISTS public.peso (id SERIAL PRIMARY KEY, data DATE, peso_kg REAL);")
            conn.commit()
    except: conn.rollback()

def limpar_valor_taco(valor):
    if pd.isna(valor) or str(valor).strip() in ['NA', 'TR', '', '*', '-']: return 0.0
    try:
        return float(str(valor).replace(',', '.'))
    except: return 0.0

# 5. INICIALIZAÇÃO
inicializar_banco()

# 6. INTERFACE
st.title("🦁 Leo Tracker Pro")
tabs = st.tabs(["🍽️ Registro", "🤖 IA", "📈 Dieta vs Meta", "⚖️ Peso", "⚙️ Admin"])

with tabs[0]:
    st.subheader("Registro Manual (TACO)")
    termo = st.text_input("🔍 Pesquisar alimento:")
    if termo:
        df_res = pd.read_sql("SELECT * FROM public.tabela_taco WHERE alimento ILIKE %s LIMIT 50", conn, params=(f'%{termo}%',))
        if not df_res.empty:
            escolha = st.selectbox("Selecione:", df_res["alimento"])
            dados = df_res[df_res["alimento"] == escolha].iloc[0]
            qtd = st.number_input("Gramas:", 0, 2000, 100)
            f = float(qtd) / 100.0
            if st.button("Salvar Alimento"):
                with conn.cursor() as cur:
                    conn.rollback()
                    cur.execute("""INSERT INTO public.consumo (alimento, quantidade, kcal, proteina, carbo, gordura) 
                                   VALUES (%s,%s,%s,%s,%s,%s)""", 
                                (escolha, float(qtd), dados['kcal']*f, dados['proteina']*f, dados['carbo']*f, dados['gordura']*f))
                    conn.commit()
                st.success("Registrado!")

with tabs[1]:
    st.subheader("🤖 Importar via IA")
    st.markdown("""
    **Como usar:** Vá ao chat da IA e use o prompt:
    > *Analise a refeição: [DESCREVA AQUI]. Retorne apenas um JSON: [{"alimento": "nome", "kcal": 0, "p": 0, "c": 0, "g": 0, "gluten": "Contém/Não contém"}]*
    """)
    json_in = st.text_area("Cole o JSON aqui:")
    if st.button("Processar IA"):
        try:
            dados = json.loads(json_in.replace('```json', '').replace('```', '').strip())
            with conn.cursor() as cur:
                conn.rollback()
                for i in dados:
                    cur.execute("""INSERT INTO public.consumo (alimento, quantidade, kcal, proteina, carbo, gordura, gluten) 
                                   VALUES (%s,1,%s,%s,%s,%s,%s)""", (i['alimento'], i['kcal'], i['p'], i['c'], i['g'], i.get('gluten','-')))
                conn.commit()
            st.success("Importado!")
            st.rerun()
        except: st.error("Erro no JSON.")

with tabs[2]:
    st.subheader("📊 Comparativo Diário")
    df_hoje = pd.read_sql("SELECT * FROM public.consumo WHERE data_hora::date = CURRENT_DATE", conn)
    
    if not df_hoje.empty:
        c1, c2, c3 = st.columns(3)
        cons_kcal = df_hoje['kcal'].sum()
        cons_prot = df_hoje['proteina'].sum()
        
        c1.metric("Kcal", f"{int(cons_kcal)} / {META_KCAL}", f"{int(cons_kcal - META_KCAL)}")
        c2.metric("Proteína", f"{int(cons_prot)}g / {META_PROT}g")
        
        # Gráfico de barras meta vs consumido
        df_meta = pd.DataFrame({
            'Categoria': ['Calorias', 'Proteína'],
            'Consumido': [cons_kcal, cons_prot],
            'Meta': [META_KCAL, META_PROT]
        })
        fig = px.bar(df_meta, x='Categoria', y=['Consumido', 'Meta'], barmode='group', title="Progresso do Dia")
        st.plotly_chart(fig)
        
        st.subheader("🕒 Histórico com Horário")
        df_hoje['hora'] = pd.to_datetime(df_hoje['data_hora']).dt.strftime('%H:%M')
        st.dataframe(df_hoje[['hora', 'alimento', 'kcal', 'proteina', 'gluten']], use_container_width=True)
    else:
        st.info("Nenhum dado hoje.")

with tabs[3]:
    st.subheader("⚖️ Controle de Peso")
    # Mesma lógica anterior de peso...

with tabs[4]:
    st.subheader("⚙️ Painel Admin")
    
    with st.expander("➕ Inserir Alimento Manual na TACO"):
        n = st.text_input("Nome Alimento:")
        col_a, col_b = st.columns(2)
        k_n = col_a.number_input("Kcal/100g")
        p_n = col_b.number_input("Prot/100g")
        if st.button("Cadastrar Alimento"):
            with conn.cursor() as cur:
                conn.rollback()
                cur.execute("INSERT INTO public.tabela_taco (alimento, kcal, proteina, carbo, gordura) VALUES (%s,%s,%s,0,0)", (n, k_n, p_n))
                conn.commit()
            st.success("Adicionado!")

    if st.button("🚀 Sincronizar alimentos.csv"):
        try:
            df_csv = pd.read_csv('alimentos.csv', sep=';', encoding='latin-1')
            preparada = []
            for _, row in df_csv.iterrows():
                preparada.append((str(row.iloc[2]), limpar_valor_taco(row.iloc[4]), limpar_valor_taco(row.iloc[6]), limpar_valor_taco(row.iloc[9]), limpar_valor_taco(row.iloc[7])))
            with conn.cursor() as cur:
                conn.rollback()
                cur.execute("TRUNCATE TABLE public.tabela_taco")
                cur.executemany("INSERT INTO public.tabela_taco (alimento, kcal, proteina, carbo, gordura) VALUES (%s,%s,%s,%s,%s)", preparada)
                conn.commit()
            st.success("Sincronizado!")
        except Exception as e: st.error(f"Erro: {e}")
