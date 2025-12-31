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

# 3. METAS
META_KCAL = 1600
META_PROTEINA = 150

# 4. FUNÇÕES DE BANCO DE DADOS
def inicializar_banco():
    try:
        with conn.cursor() as cur:
            conn.rollback()
            cur.execute("SET search_path TO public")
            # Tabela de Alimentos (TACO + Manuais)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS public.tabela_taco (
                    id SERIAL PRIMARY KEY, alimento TEXT, kcal REAL, proteina REAL, carbo REAL, gordura REAL
                );
            """)
            # Tabela de Consumo Diário (com coluna de Glúten)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS public.consumo (
                    id SERIAL PRIMARY KEY, data DATE, alimento TEXT, quantidade REAL, 
                    kcal REAL, proteina REAL, carbo REAL, gordura REAL, gluten TEXT DEFAULT 'Não informado'
                );
            """)
            # Tabela de Peso
            cur.execute("""
                CREATE TABLE IF NOT EXISTS public.peso (
                    id SERIAL PRIMARY KEY, data DATE, peso_kg REAL
                );
            """)
            # Garantir coluna gluten existe
            cur.execute("""
                DO $$ BEGIN 
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='consumo' AND column_name='gluten') 
                THEN ALTER TABLE public.consumo ADD COLUMN gluten TEXT DEFAULT 'Não informado'; 
                END IF; END $$;
            """)
            conn.commit()
    except: conn.rollback()

def buscar_alimento(termo):
    if not termo: return pd.DataFrame()
    try:
        return pd.read_sql("SELECT * FROM public.tabela_taco WHERE alimento ILIKE %s ORDER BY alimento ASC LIMIT 50", conn, params=(f'%{termo}%',))
    except: 
        conn.rollback()
        return pd.DataFrame()

def deletar_registro(tabela, id_reg):
    try:
        with conn.cursor() as cur:
            conn.rollback()
            cur.execute(f"DELETE FROM public.{tabela} WHERE id = %s", (id_reg,))
            conn.commit()
        return True
    except: return False

# 5. INICIALIZAÇÃO
inicializar_banco()

# 6. INTERFACE
st.title("🦁 Leo Tracker Pro")
tab_reg, tab_ia, tab_hist, tab_peso, tab_admin = st.tabs(["🍽️ Registro", "🤖 Importar IA", "📊 Histórico", "⚖️ Peso", "⚙️ Admin"])

with tab_reg:
    st.subheader("Busca na Tabela TACO")
    termo = st.text_input("🔍 Pesquisar alimento:")
    if termo:
        df_res = buscar_alimento(termo)
        if not df_res.empty:
            escolha = st.selectbox("Selecione:", df_res["alimento"])
            dados = df_res[df_res["alimento"] == escolha].iloc[0]
            qtd = st.number_input("Gramas:", 0, 2000, 100)
            fator = float(qtd) / 100.0
            k, p, c, g = round(dados['kcal']*fator), round(dados['proteina']*fator,1), round(dados['carbo']*fator,1), round(dados['gordura']*fator,1)
            st.info(f"🥘 {k} kcal | P: {p}g | C: {c}g")
            if st.button("Salvar Registro"):
                with conn.cursor() as cur:
                    conn.rollback()
                    cur.execute("""INSERT INTO public.consumo (data, alimento, quantidade, kcal, proteina, carbo, gordura, gluten) 
                                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""", 
                                (datetime.now().date(), escolha, float(qtd), k, p, c, g, "Não informado"))
                    conn.commit()
                st.success("Salvo!")

with tab_ia:
    st.subheader("🤖 Importar do Gemini (com Glúten)")
    st.info("Cole o JSON gerado pela IA abaixo para registrar pratos complexos.")
    json_input = st.text_area("Cole o código JSON aqui:", height=150)
    if st.button("Processar JSON ✅"):
        try:
            dados = json.loads(json_input.replace('```json', '').replace('```', '').strip())
            for item in dados:
                with conn.cursor() as cur:
                    conn.rollback()
                    cur.execute("""INSERT INTO public.consumo (data, alimento, quantidade, kcal, proteina, carbo, gordura, gluten) 
                                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""", 
                                (datetime.now().date(), item['alimento'], 1.0, item['kcal'], item['p'], item['c'], item['g'], item.get('gluten', 'Não informado')))
                    conn.commit()
            st.success("Dados da IA importados!")
            st.rerun()
        except Exception as e: st.error(f"Erro no JSON: {e}")

with tab_hist:
    st.subheader("Refeições de Hoje")
    df_h = pd.read_sql("SELECT * FROM public.consumo WHERE data = %s ORDER BY id DESC", conn, params=(datetime.now().date(),))
    if not df_h.empty:
        for _, row in df_h.iterrows():
            c1, c2, c3 = st.columns([3, 1.5, 0.5])
            gluten_tag = "🚫" if row['gluten'] == "Contém" else "🍃"
            c1.write(f"**{row['alimento']}**")
            c2.write(f"{row['kcal']} kcal | {gluten_tag}")
            if c3.button("🗑️", key=f"del_c_{row['id']}"):
                if deletar_registro("consumo", row['id']): st.rerun()
    else: st.info("Nada registrado hoje.")

with tab_peso:
    cp1, cp2 = st.columns([1, 2])
    with cp1:
        p_val = st.number_input("Peso (kg):", 40.0, 250.0, 145.0)
        if st.button("Gravar Peso"):
            with conn.cursor() as cur:
                conn.rollback()
                cur.execute("INSERT INTO public.peso (data, peso_kg) VALUES (%s, %s)", (datetime.now().date(), float(p_val)))
                conn.commit()
            st.rerun()
    with cp2:
        df_p = pd.read_sql("SELECT * FROM public.peso ORDER BY data DESC", conn)
        if not df_p.empty:
            st.line_chart(df_p.set_index('data')['peso_kg'])
            for _, r in df_p.iterrows():
                cc1, cc2, cc3 = st.columns([2, 2, 1])
                cc1.write(r['data'])
                cc2.write(f"{r['peso_kg']} kg")
                if cc3.button("🗑️", key=f"del_p_{r['id']}"):
                    if deletar_registro("peso", r['id']): st.rerun()

with tab_admin:
    st.subheader("⚙️ Configurações")
    if st.button("🚀 Sincronizar alimentos.csv"):
        # (Lógica de sincronização por índice 2, 4, 6, 9, 7 que já funcionou)
        try:
            df_csv = pd.read_csv('alimentos.csv', sep=';', encoding='latin-1')
            preparada = []
            for _, row in df_csv.iterrows():
                # Função interna rápida de limpeza
                def _limp(v): 
                    if pd.isna(v) or str(v).strip().upper() in ['NA','TR','']: return 0.0
                    return float(str(v).replace(',','.'))
                preparada.append((str(row.iloc[2]), _limp(row.iloc[4]), _limp(row.iloc[6]), _limp(row.iloc[9]), _limp(row.iloc[7])))
            with conn.cursor() as cur:
                conn.rollback()
                cur.execute("TRUNCATE TABLE public.tabela_taco")
                cur.executemany("INSERT INTO public.tabela_taco (alimento, kcal, proteina, carbo, gordura) VALUES (%s,%s,%s,%s,%s)", preparada)
                conn.commit()
            st.success("Sincronizado!")
        except Exception as e: st.error(e)
