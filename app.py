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
    if "password_correct" not in st.session_state:
        st.session_state["password_correct"] = False
    if st.session_state["password_correct"]:
        return True
    st.title("🦁 Leo Tracker Login")
    password = st.text_input("Senha de acesso:", type="password")
    if st.button("Entrar"):
        if password == st.secrets["PASSWORD"]:
            st.session_state["password_correct"] = True
            st.rerun()
        else:
            st.error("Senha incorreta!")
    return False

if not check_password():
    st.stop()

# 2. CONEXÃO NEON
@st.cache_resource
def init_connection():
    return psycopg2.connect(st.secrets["DATABASE_URL"])

try:
    conn = init_connection()
except:
    st.error("Erro de conexão.")
    st.stop()

# 3. METAS DA DIETA (AJUSTÁVEIS)
META_KCAL = 1600
META_PROTEINA = 150 # Foco em manter massa muscular

# 4. FUNÇÕES DE BANCO
def inicializar_banco():
    with conn.cursor() as cur:
        conn.rollback()
        cur.execute("SET search_path TO public")
        cur.execute("CREATE TABLE IF NOT EXISTS tabela_taco (id SERIAL PRIMARY KEY, alimento TEXT, kcal REAL, proteina REAL, carbo REAL, gordura REAL);")
        cur.execute("CREATE TABLE IF NOT EXISTS consumo (id SERIAL PRIMARY KEY, data DATE, alimento TEXT, quantidade REAL, kcal REAL, proteina REAL, carbo REAL, gordura REAL);")
        cur.execute("CREATE TABLE IF NOT EXISTS peso (id SERIAL PRIMARY KEY, data DATE, peso_kg REAL);")
        conn.commit()

def buscar_alimento(termo):
    if not termo: return pd.DataFrame()
    return pd.read_sql("SELECT * FROM public.tabela_taco WHERE alimento ILIKE %s ORDER BY alimento ASC LIMIT 50", conn, params=(f'%{termo}%',))

def ler_dados_periodo(dias=30):
    data_inicio = (datetime.now() - timedelta(days=dias)).date()
    return pd.read_sql("SELECT * FROM public.consumo WHERE data >= %s ORDER BY data DESC", conn, params=(data_inicio,))

# 5. INTERFACE
inicializar_banco()
st.title("🦁 Leo Tracker Pro")

tab_prato, tab_plano, tab_dash, tab_peso, tab_admin = st.tabs(["🍽️ Registro", "📝 Meu Plano", "📊 Evolução", "⚖️ Peso", "⚙️ Config"])

with tab_prato:
    # Barra de Progresso do Dia
    df_hoje = ler_dados_periodo(0)
    kcal_hoje = df_hoje['kcal'].sum() if not df_hoje.empty else 0
    prot_hoje = df_hoje['proteina'].sum() if not df_hoje.empty else 0
    
    col_m1, col_m2 = st.columns(2)
    col_m1.metric("Calorias", f"{int(kcal_hoje)} / {META_KCAL} kcal", f"{int(META_KCAL - kcal_hoje)} restando")
    col_m2.metric("Proteína", f"{int(prot_hoje)} / {META_PROTEINA}g", f"{int(META_PROTEINA - prot_hoje)} restando")
    
    st.progress(min(kcal_hoje/META_KCAL, 1.0))
    
    st.divider()
    termo = st.text_input("🔍 O que você comeu?")
    if termo:
        df_res = buscar_alimento(termo)
        if not df_res.empty:
            escolha = st.selectbox("Selecione:", df_res["alimento"])
            dados = df_res[df_res["alimento"] == escolha].iloc[0]
            qtd = st.number_input("Gramas:", 0, 2000, 100)
            fator = float(qtd) / 100.0
            k, p, c = float(round(dados['kcal']*fator)), float(round(dados['proteina']*fator,1)), float(round(dados['carbo']*fator,1))
            
            if st.button("Confirmar Refeição"):
                with conn.cursor() as cur:
                    conn.rollback()
                    cur.execute("INSERT INTO public.consumo (data, alimento, quantidade, kcal, proteina, carbo, gordura) VALUES (%s,%s,%s,%s,%s,%s,%s)", 
                                (datetime.now().date(), escolha, float(qtd), k, p, c, float(round(dados['gordura']*fator,1))))
                    conn.commit()
                st.success("Salvo!")
                st.rerun()

with tab_plano:
    st.subheader("📋 Sugestão de Rotina (Foco: Perda de Peso)")
    
    with st.expander("🌅 Café da Manhã (07:00 - 08:30)"):
        st.write("**Sugestão:** Ovos mexidos (2 a 3 unidades) + 1 fatia de mamão ou 1 dose de Whey Protein.")
        st.caption("Foco: Proteína e Gordura boa para saciedade matinal.")
        
    with st.expander("🍲 Almoço (12:00 - 13:30)"):
        st.write("**Sugestão:** 100g de Arroz integral + 1 concha de feijão + 150g de proteína magra (Frango/Patinho) + Vegetais verdes à vontade.")
        st.caption("Foco: Carboidrato complexo para energia no treino/trabalho.")

    with st.expander("🍎 Lanche da Tarde (16:00 - 17:00)"):
        st.write("**Sugestão:** 1 iogurte natural ou uma fruta com aveia ou 30g de castanhas.")
        st.caption("Foco: Evitar o pico de fome no final do dia.")

    with st.expander("🌙 Jantar (19:30 - 20:30)"):
        st.write("**Sugestão:** Proteína (Peixe ou Frango) + Salada caprichada + Batata doce (opcional).")
        st.caption("Foco: Baixo carboidrato para facilitar a queima de gordura no sono.")

with tab_dash:
    df_dados = ler_dados_periodo(30)
    if not df_dados.empty:
        df_dados['data'] = pd.to_datetime(df_dados['data'])
        fig = px.line(df_dados.groupby('data')['kcal'].sum().reset_index(), x='data', y='kcal', title="Histórico de Calorias")
        st.plotly_chart(fig, use_container_width=True)
        st.dataframe(df_dados)

with tab_peso:
    col_p1, col_p2 = st.columns([1, 2])
    with col_p1:
        p_in = st.number_input("Peso (kg):", 40.0, 250.0, 145.0)
        if st.button("Gravar"):
            with conn.cursor() as cur:
                conn.rollback()
                cur.execute("INSERT INTO public.peso (data, peso_kg) VALUES (%s, %s)", (datetime.now().date(), float(p_in)))
                conn.commit()
            st.success("Gravado!")
            st.rerun()
    with col_p2:
        df_p = pd.read_sql("SELECT data, peso_kg FROM public.peso ORDER BY data DESC", conn)
        if not df_p.empty:
            st.line_chart(df_p.set_index('data'))

with tab_admin:
    if st.button("🚀 Sincronizar Base TACO"):
        # Código de sincronização do CSV...
        pass
