import streamlit as st
import pandas as pd
import psycopg2
from datetime import datetime, timedelta
import json

# 1. CONFIGURAÇÃO DA PÁGINA
st.set_page_config(page_title="Leo Tracker Pro", page_icon="🦁", layout="wide")

# --- SISTEMA DE LOGIN ---
def check_password():
    if "password_correct" not in st.session_state:
        st.session_state["password_correct"] = False
    if st.session_state["password_correct"]: return True
    st.title("🦁 Leo Tracker Login")
    password = st.text_input("Senha:", type="password")
    if st.button("Entrar"):
        if password == st.secrets["PASSWORD"]:
            st.session_state["password_correct"] = True
            st.rerun()
        else: st.error("Incorreta!")
    return False

if not check_password(): st.stop()

# 2. CONEXÃO NEON
@st.cache_resource
def init_connection():
    return psycopg2.connect(st.secrets["DATABASE_URL"])

try:
    conn = init_connection()
except:
    st.error("Erro de conexão com o banco de dados.")
    st.stop()

# 3. FUNÇÕES DE BANCO (Garantindo o esquema public)
def inicializar_banco():
    with conn.cursor() as cur:
        conn.rollback()
        cur.execute("SET search_path TO public")
        # Tabela de consumo com coluna gluten
        cur.execute("""
            CREATE TABLE IF NOT EXISTS public.consumo (
                id SERIAL PRIMARY KEY, 
                data DATE, 
                alimento TEXT, 
                quantidade REAL, 
                kcal REAL, 
                proteina REAL, 
                carbo REAL, 
                gordura REAL,
                gluten TEXT DEFAULT 'Não informado'
            );
        """)
        # Verificação extra para coluna gluten em tabelas antigas
        cur.execute("""
            DO $$ 
            BEGIN 
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='consumo' AND column_name='gluten') THEN
                    ALTER TABLE public.consumo ADD COLUMN gluten TEXT DEFAULT 'Não informado';
                END IF;
            END $$;
        """)
        # Tabela de peso
        cur.execute("""
            CREATE TABLE IF NOT EXISTS public.peso (
                id SERIAL PRIMARY KEY, 
                data DATE, 
                peso_kg REAL
            );
        """)
        conn.commit()

def salvar_refeicao(nome, kcal, p, c, g, gluten):
    try:
        with conn.cursor() as cur:
            conn.rollback()
            cur.execute("SET search_path TO public")
            cur.execute("""
                INSERT INTO public.consumo (data, alimento, quantidade, kcal, proteina, carbo, gordura, gluten) 
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            """, (datetime.now().date(), str(nome), 1.0, float(kcal), float(p), float(c), float(g), str(gluten)))
            conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        st.error(f"Erro no banco: {e}")
        return False

# 4. INTERFACE
inicializar_banco()
st.title("🦁 Leo Tracker Pro")
t_ia, t_hist, t_peso = st.tabs(["🤖 Importar da IA", "📊 Histórico Diário", "⚖️ Controle de Peso"])

with t_ia:
    st.subheader("🤖 Assistente de Importação")
    st.markdown("""
    **Como usar:**
    1. Peça para a IA (Gemini/GPT) analisar sua refeição.
    2. Use o prompt: *'Gere o JSON: [{"alimento": "...", "kcal": 0, "p": 0, "c": 0, "g": 0, "gluten": "Contém/Não contém"}]'*
    3. Cole o resultado abaixo.
    """)
    
    json_input = st.text_area("Cole o código JSON aqui:", height=150)
    
    if st.button("Processar e Salvar no Banco ✅"):
        if json_input:
            try:
                # Limpeza de markdown caso o usuário cole com as aspas do chat
                limpo = json_input.replace('```json', '').replace('```', '').strip()
                dados = json.loads(limpo)
                
                for item in dados:
                    g_status = item.get('gluten', 'Não informado')
                    if salvar_refeicao(item['alimento'], item['kcal'], item['p'], item['c'], item['g'], g_status):
                        if g_status == "Contém":
                            st.warning(f"Salvo: {item['alimento']} (⚠️ Contém Glúten)")
                        else:
                            st.success(f"Salvo: {item['alimento']} (✅ Sem Glúten)")
                st.rerun()
            except Exception as e:
                st.error(f"Erro ao ler JSON: {e}")

with t_hist:
    st.subheader("Refeições de Hoje")
    try:
        df = pd.read_sql("SELECT * FROM public.consumo WHERE data = %s ORDER BY id DESC", conn, params=(datetime.now().date(),))
        if not df.empty:
            for i, row in df.iterrows():
                c1, c2, c3 = st.columns([3, 2, 0.5])
                c1.write(f"**{row['alimento']}**")
                
                g_icon = "🚫" if row['gluten'] == "Contém" else "🍃"
                c2.write(f"{int(row['kcal'])} kcal | {g_icon} {row['gluten']}")
                
                if c3.button("🗑️", key=f"del_{row['id']}"):
                    with conn.cursor() as cur:
                        conn.rollback()
                        cur.execute("DELETE FROM public.consumo WHERE id = %s", (row['id'],))
                        conn.commit()
                    st.rerun()
        else:
            st.info("Nenhuma refeição registrada hoje.")
    except:
        conn.rollback()

with t_peso:
    st.subheader("Controle de Peso")
    p_val = st.number_input("Peso Atual (kg):", 40.0, 250.0, 145.0)
    if st.button("Registrar Peso"):
        try:
            with conn.cursor() as cur:
                conn.rollback()
                cur.execute("INSERT INTO public.peso (data, peso_kg) VALUES (%s, %s)", (datetime.now().date(), float(p_val)))
                conn.commit()
            st.success("Peso registrado!")
            st.rerun()
        except:
            conn.rollback()
    
    st.divider()
    df_p = pd.read_sql("SELECT data, peso_kg FROM public.peso ORDER BY data DESC LIMIT 10", conn)
    if not df_p.empty:
        st.line_chart(df_p.set_index('data'))
        st.table(df_p)
