import streamlit as st
import pandas as pd
import psycopg2
from datetime import datetime
import plotly.express as px
import json
from contextlib import contextmanager

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

# 2. GERENCIAMENTO DE CONEXÃO (MODO PRO)
@st.cache_resource
def get_connection_purer():
    return psycopg2.connect(st.secrets["DATABASE_URL"])

@contextmanager
def get_cursor():
    conn = get_connection_purer()
    cur = conn.cursor()
    try:
        yield cur
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cur.close()

# 3. METAS
META_KCAL = 2000
META_PROT = 160

# 4. INICIALIZAÇÃO E MIGRAÇÃO
def inicializar_banco():
    with get_cursor() as cur:
        cur.execute("SET search_path TO public")
        # Tabela TACO
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tabela_taco (
                id SERIAL PRIMARY KEY, alimento TEXT, kcal REAL, proteina REAL, carbo REAL, gordura REAL
            );
        """)
        # Tabela Consumo
        cur.execute("""
            CREATE TABLE IF NOT EXISTS consumo (
                id SERIAL PRIMARY KEY, 
                data_hora TIMESTAMP DEFAULT CURRENT_TIMESTAMP, 
                alimento TEXT, quantidade REAL, kcal REAL, proteina REAL, carbo REAL, gordura REAL, 
                gluten TEXT DEFAULT 'Não informado'
            );
        """)
        # Migração segura
        cur.execute("""
            DO $$ 
            BEGIN 
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='consumo' AND column_name='data_hora') THEN
                    ALTER TABLE consumo ADD COLUMN data_hora TIMESTAMP DEFAULT CURRENT_TIMESTAMP;
                END IF;
            END $$;
        """)
        cur.execute("CREATE TABLE IF NOT EXISTS peso (id SERIAL PRIMARY KEY, data DATE UNIQUE, peso_kg REAL);")

def limpar_valor_taco(valor):
    if pd.isna(valor) or str(valor).strip() in ['NA', 'TR', '', '*', '-']: return 0.0
    try: return float(str(valor).replace(',', '.'))
    except: return 0.0

# 5. EXECUÇÃO INICIAL
try:
    inicializar_banco()
except Exception as e:
    st.error(f"Erro de Banco: {e}")
    st.stop()

# 6. INTERFACE
st.title("🦁 Leo Tracker Pro")
tabs = st.tabs(["🍽️ Registro", "🤖 IA", "📈 Dieta vs Meta", "⚖️ Peso", "⚙️ Admin"])

with tabs[0]:
    st.subheader("Registro Manual (Busca TACO)")
    termo = st.text_input("🔍 Pesquisar alimento:")
    if termo:
        conn = get_connection_purer()
        df_res = pd.read_sql("SELECT * FROM public.tabela_taco WHERE alimento ILIKE %s LIMIT 50", conn, params=(f'%{termo}%',))
        if not df_res.empty:
            escolha = st.selectbox("Selecione:", df_res["alimento"])
            dados = df_res[df_res["alimento"] == escolha].iloc[0]
            qtd = st.number_input("Gramas:", 0, 2000, 100)
            f = float(qtd) / 100.0
            if st.button("Salvar Alimento"):
                with get_cursor() as cur:
                    cur.execute("""INSERT INTO consumo (alimento, quantidade, kcal, proteina, carbo, gordura) 
                                   VALUES (%s,%s,%s,%s,%s,%s)""", 
                                (escolha, float(qtd), dados['kcal']*f, dados['proteina']*f, dados['carbo']*f, dados['gordura']*f))
                st.success("Registrado!")
                st.rerun()

with tabs[1]:
    st.subheader("🤖 Importar via IA")
    json_in = st.text_area("Cole o JSON da IA aqui:", height=200)
    if st.button("Processar e Salvar"):
        try:
            # Limpeza de Markdown
            clean_json = json_in.replace('```json', '').replace('```', '').strip()
            dados = json.loads(clean_json)
            with get_cursor() as cur:
                for i in dados:
                    cur.execute("""INSERT INTO consumo (alimento, quantidade, kcal, proteina, carbo, gordura, gluten) 
                                   VALUES (%s,1,%s,%s,%s,%s,%s)""", 
                                (i['alimento'], i['kcal'], i['p'], i['c'], i['g'], i.get('gluten','Não informado')))
            st.success("Importado com sucesso!")
            st.rerun()
        except Exception as e: st.error(f"Erro no processamento: {e}")

with tabs[2]:
    st.subheader("📊 Progresso Diário")
    conn = get_connection_purer()
    df_hoje = pd.read_sql("SELECT * FROM consumo WHERE data_hora::date = CURRENT_DATE", conn)
    
    if not df_hoje.empty:
        c1, c2 = st.columns(2)
        cons_kcal, cons_prot = df_hoje['kcal'].sum(), df_hoje['proteina'].sum()
        
        c1.metric("Energia", f"{int(cons_kcal)} / {META_KCAL} kcal", f"{int(cons_kcal - META_KCAL)} kcal", delta_color="inverse")
        c2.metric("Proteína", f"{int(cons_prot)}g / {META_PROT}g", f"{int(cons_prot - META_PROT)}g")
        
        fig = px.bar(x=['Calorias', 'Proteína'], y=[cons_kcal/META_KCAL, cons_prot/META_PROT], 
                     range_y=[0, 1.2], title="Aproveitamento da Meta (%)")
        st.plotly_chart(fig, use_container_width=True)
        
        st.divider()
        for _, row in df_hoje.iterrows():
            col_h1, col_h2, col_h3 = st.columns([1, 4, 1])
            col_h1.write(pd.to_datetime(row['data_hora']).strftime('%H:%M'))
            col_h2.write(f"**{row['alimento']}** - {int(row['kcal'])} kcal")
            if col_h3.button("🗑️", key=f"del_{row['id']}"):
                with get_cursor() as cur:
                    cur.execute("DELETE FROM consumo WHERE id = %s", (row['id'],))
                st.rerun()
    else: st.info("Nada registrado hoje.")

with tabs[3]:
    st.subheader("⚖️ Controle de Peso")
    p_val = st.number_input("Peso hoje (kg):", 40.0, 250.0, 145.0, step=0.1)
    if st.button("Gravar Peso"):
        with get_cursor() as cur:
            cur.execute("""INSERT INTO peso (data, peso_kg) VALUES (%s, %s) 
                           ON CONFLICT (data) DO UPDATE SET peso_kg = EXCLUDED.peso_kg""", 
                        (datetime.now().date(), float(p_val)))
        st.success("Peso atualizado!")

with tabs[4]:
    st.subheader("⚙️ Admin")
    if st.button("🚀 Sincronizar alimentos.csv"):
        try:
            df_csv = pd.read_csv('alimentos.csv', sep=';', encoding='latin-1')
            preparada = [(str(r.iloc[2]), limpar_valor_taco(r.iloc[4]), limpar_valor_taco(r.iloc[6]), 
                          limpar_valor_taco(r.iloc[9]), limpar_valor_taco(r.iloc[7])) for _, r in df_csv.iterrows()]
            with get_cursor() as cur:
                cur.execute("TRUNCATE TABLE tabela_taco")
                cur.executemany("INSERT INTO tabela_taco (alimento, kcal, proteina, carbo, gordura) VALUES (%s,%s,%s,%s,%s)", preparada)
            st.success(f"{len(preparada)} alimentos sincronizados!")
        except Exception as e: st.error(f"Erro: {e}")
