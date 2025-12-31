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

# 2. GERENCIAMENTO DE CONEXÃO
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

# 3. METAS DO PLANO (Leonardo Grando - Dezembro/25)
META_KCAL = 2000 
META_PROT = 160  

# 4. INICIALIZAÇÃO DO BANCO
def inicializar_banco():
    with get_cursor() as cur:
        cur.execute("SET search_path TO public")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tabela_taco (
                id SERIAL PRIMARY KEY, alimento TEXT, kcal REAL, proteina REAL, carbo REAL, gordura REAL
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS consumo (
                id SERIAL PRIMARY KEY, 
                data_hora TIMESTAMP DEFAULT CURRENT_TIMESTAMP, 
                alimento TEXT, quantidade REAL, kcal REAL, proteina REAL, carbo REAL, gordura REAL, 
                gluten TEXT DEFAULT 'Não informado'
            );
        """)
        cur.execute("CREATE TABLE IF NOT EXISTS peso (id SERIAL PRIMARY KEY, data DATE UNIQUE, peso_kg REAL);")

def limpar_valor_taco(valor):
    if pd.isna(valor) or str(valor).strip() in ['NA', 'TR', '', '*', '-']: return 0.0
    try: return float(str(valor).replace(',', '.'))
    except: return 0.0

try:
    inicializar_banco()
except Exception as e:
    st.error(f"Erro de Banco: {e}")
    st.stop()

# 5. INTERFACE PRINCIPAL
st.title("🦁 Leo Tracker Pro")
tabs = st.tabs(["🍽️ Registro", "🤖 IA Nutricional", "📈 Progresso", "📋 Plano & Sugestões", "⚖️ Peso & Admin"])

with tabs[0]:
    st.subheader("Busca Manual (TACO)")
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
    st.markdown("**Copie o JSON gerado pelo Gemini e cole abaixo:**")
    json_in = st.text_area("Área de colagem:", height=150)
    if st.button("Processar e Salvar"):
        try:
            clean_json = json_in.replace('```json', '').replace('```', '').strip()
            dados = json.loads(clean_json)
            with get_cursor() as cur:
                for i in dados:
                    cur.execute("""INSERT INTO consumo (alimento, quantidade, kcal, proteina, carbo, gordura, gluten) 
                                   VALUES (%s,1,%s,%s,%s,%s,%s)""", 
                                (i['alimento'], i['kcal'], i['p'], i['c'], i['g'], i.get('gluten','Não informado')))
            st.success("Refeição importada com sucesso!")
            st.rerun()
        except Exception as e: st.error(f"Erro no formato do JSON: {e}")

with tabs[2]:
    st.subheader("📊 Progresso do Dia")
    conn = get_connection_purer()
    df_hoje = pd.read_sql("SELECT * FROM consumo WHERE data_hora::date = CURRENT_DATE", conn)
    if not df_hoje.empty:
        c1, c2 = st.columns(2)
        cons_kcal, cons_prot = df_hoje['kcal'].sum(), df_hoje['proteina'].sum()
        c1.metric("Energia", f"{int(cons_kcal)} / {META_KCAL} kcal", f"{int(cons_kcal - META_KCAL)} kcal", delta_color="inverse")
        c2.metric("Proteína", f"{int(cons_prot)}g / {META_PROT}g", f"{int(cons_prot - META_PROT)}g")
        
        st.divider()
        st.write("🕒 Histórico:")
        for _, row in df_hoje.iterrows():
            col_h1, col_h2, col_h3 = st.columns([1, 4, 1])
            col_h1.write(pd.to_datetime(row['data_hora']).strftime('%H:%M'))
            col_h2.write(f"**{row['alimento']}** - {int(row['kcal'])} kcal")
            if col_h3.button("🗑️", key=f"del_{row['id']}"):
                with get_cursor() as cur:
                    cur.execute("DELETE FROM consumo WHERE id = %s", (row['id'],))
                st.rerun()
    else: st.info("Nenhum registro para hoje.")

with tabs[3]:
    st.subheader("📋 Orientações Nutricionais (Dez/25)")
    col_orig, col_econ = st.columns(2)
    
    with col_orig:
        st.info("🎯 Opções do Plano Original")
        st.markdown("""
        * **Café:** Shake com Whey (17g) [cite: 18], Leite Desnatado [cite: 14] e Frutas (Morango/Mamão)[cite: 7, 8].
        * **Almoço:** Salmão (120g) [cite: 36] ou Sardinha [cite: 37], Mandioca (100g) [cite: 40] ou Quinoa[cite: 42].
        * **Jantar:** Contra-filé (80g) [cite: 63] ou Patinho [cite: 65], Batata Sauté (200g)[cite: 66].
        * **Ceia:** Iogurte Natural (170ml) [cite: 75] e Mel (15g)[cite: 79].
        """)
        
    with col_econ:
        st.success("💰 Sugestões Mais Baratas (Mesmos Macros)")
        st.markdown("""
        * **Substituir Whey:** Ovos cozidos ou claras (ótimo custo-benefício).
        * **Substituir Salmão/Carne:** Peito de Frango, Sobrecoxa sem pele ou Fígado bovino.
        * **Substituir Quinoa/Mandioca:** Arroz branco com Feijão ou Batata Doce.
        * **Substituir Sementes Caras:** Farelo de Aveia (fonte barata de fibras).
        * **Substituir Morango:** Banana prata ou Nanica (sempre mais barata).
        """)

with tabs[4]:
    st.subheader("⚖️ Controle de Peso")
    p_val = st.number_input("Peso hoje (kg):", 40.0, 250.0, 145.0)
    if st.button("Gravar Peso"):
        with get_cursor() as cur:
            cur.execute("""INSERT INTO peso (data, peso_kg) VALUES (%s, %s) 
                           ON CONFLICT (data) DO UPDATE SET peso_kg = EXCLUDED.peso_kg""", 
                        (datetime.now().date(), float(p_val)))
        st.success("Peso registrado!")
    
    st.divider()
    st.subheader("⚙️ Administração")
    if st.button("🚀 Sincronizar alimentos.csv (TACO)"):
        try:
            df_csv = pd.read_csv('alimentos.csv', sep=';', encoding='latin-1')
            preparada = [(str(r.iloc[2]), limpar_valor_taco(r.iloc[4]), limpar_valor_taco(r.iloc[6]), 
                          limpar_valor_taco(r.iloc[9]), limpar_valor_taco(r.iloc[7])) for _, r in df_csv.iterrows()]
            with get_cursor() as cur:
                cur.execute("TRUNCATE TABLE tabela_taco")
                cur.executemany("INSERT INTO tabela_taco (alimento, kcal, proteina, carbo, gordura) VALUES (%s,%s,%s,%s,%s)", preparada)
            st.success("Base de dados sincronizada!")
        except Exception as e: st.error(f"Erro ao ler CSV: {e}")
