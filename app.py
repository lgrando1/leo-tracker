import streamlit as st
import pandas as pd
import psycopg2
from datetime import datetime, timedelta
import json
import os

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

# 3. METAS
META_KCAL = 1600
META_PROTEINA = 150

# 4. FUNÇÕES DE BANCO (COM CORREÇÃO DE ESQUEMA PUBLIC)
def inicializar_banco():
    with conn.cursor() as cur:
        conn.rollback()
        cur.execute("SET search_path TO public")
        
        # Tabela TACO (Alimentos base)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS public.tabela_taco (
                id SERIAL PRIMARY KEY, alimento TEXT, kcal REAL, proteina REAL, carbo REAL, gordura REAL
            );
        """)
        
        # Tabela Consumo (Seus registros)
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
        
        # Garante que a coluna gluten existe
        cur.execute("""
            DO $$ 
            BEGIN 
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='consumo' AND column_name='gluten') THEN
                    ALTER TABLE public.consumo ADD COLUMN gluten TEXT DEFAULT 'Não informado';
                END IF;
            END $$;
        """)
        
        # Tabela Peso
        cur.execute("""
            CREATE TABLE IF NOT EXISTS public.peso (
                id SERIAL PRIMARY KEY, data DATE, peso_kg REAL
            );
        """)
        conn.commit()

def limpar_valor_taco(valor):
    if pd.isna(valor) or str(valor).strip().upper() in ['NA', 'TR', '', '-']: return 0.0
    try: return float(str(valor).replace(',', '.'))
    except: return 0.0

def carregar_csv_completo():
    try:
        if not os.path.exists('alimentos.csv'): return False
        df = pd.read_csv('alimentos.csv', sep=';', encoding='latin-1')
        tabela_preparada = []
        for _, row in df.iterrows():
            tabela_preparada.append((
                str(row.iloc[2]), float(limpar_valor_taco(row.iloc[4])),  
                float(limpar_valor_taco(row.iloc[6])), float(limpar_valor_taco(row.iloc[9])), float(limpar_valor_taco(row.iloc[7]))   
            ))
        with conn.cursor() as cur:
            conn.rollback()
            cur.execute("SET search_path TO public")
            cur.execute("TRUNCATE TABLE public.tabela_taco")
            cur.executemany("INSERT INTO public.tabela_taco (alimento, kcal, proteina, carbo, gordura) VALUES (%s, %s, %s, %s, %s)", tabela_preparada)
            conn.commit()
        return True
    except:
        conn.rollback()
        return False

def deletar_registro(tabela, id_registro):
    try:
        with conn.cursor() as cur:
            conn.rollback()
            cur.execute(f"DELETE FROM public.{tabela} WHERE id = %s", (id_registro,))
            conn.commit()
        return True
    except: return False

def buscar_alimento(termo):
    if not termo: return pd.DataFrame()
    return pd.read_sql("SELECT * FROM public.tabela_taco WHERE alimento ILIKE %s ORDER BY alimento ASC LIMIT 50", conn, params=(f'%{termo}%',))

def ler_dados_periodo(dias=30):
    data_inicio = (datetime.now() - timedelta(days=dias)).date()
    return pd.read_sql("SELECT * FROM public.consumo WHERE data >= %s ORDER BY data DESC, id DESC", conn, params=(data_inicio,))

# 5. INICIALIZAÇÃO
inicializar_banco()

# 6. INTERFACE
st.title("🦁 Leo Tracker Pro")
tab_prato, tab_ia, tab_hist, tab_peso, tab_admin = st.tabs(["🍽️ Buscar (TACO)", "🤖 Importar JSON", "📊 Histórico", "⚖️ Peso", "⚙️ Admin"])

# --- ABA 1: BUSCA MANUAL NA TACO (Banana, Arroz, etc) ---
with tab_prato:
    st.subheader("O que comeu hoje?")
    
    # Métricas do Dia
    df_hoje = ler_dados_periodo(0)
    kcal_hoje = float(df_hoje['kcal'].sum()) if not df_hoje.empty else 0.0
    prot_hoje = float(df_hoje['proteina'].sum()) if not df_hoje.empty else 0.0
    
    c1, c2 = st.columns(2)
    c1.metric("Kcal", f"{int(kcal_hoje)} / {META_KCAL}", f"Resta: {int(META_KCAL - kcal_hoje)}")
    c2.metric("Proteína", f"{int(prot_hoje)} / {META_PROTEINA}g", f"Resta: {int(META_PROTEINA - prot_hoje)}")
    st.progress(min(kcal_hoje/META_KCAL, 1.0))
    st.divider()

    # Busca
    termo = st.text_input("🔍 Pesquisar alimento (ex: banana, arroz):")
    if termo:
        df_res = buscar_alimento(termo)
        if not df_res.empty:
            escolha = st.selectbox("Selecione:", df_res["alimento"])
            dados = df_res[df_res["alimento"] == escolha].iloc[0]
            
            qtd = st.number_input("Peso (g):", 0, 2000, 100)
            fator = float(qtd) / 100.0
            
            # Conversão SEGURA para float python (evita erro numpy/schema)
            k = float(round(float(dados['kcal']) * fator))
            p = float(round(float(dados['proteina']) * fator, 1))
            c = float(round(float(dados['carbo']) * fator, 1))
            g = float(round(float(dados['gordura']) * fator, 1))
            
            st.info(f"🥘 {k} kcal | P: {p}g | C: {c}g | G: {g}g")
            
            if st.button("Confirmar Refeição"):
                try:
                    with conn.cursor() as cur:
                        conn.rollback()
                        cur.execute("SET search_path TO public")
                        cur.execute("""
                            INSERT INTO public.consumo (data, alimento, quantidade, kcal, proteina, carbo, gordura, gluten) 
                            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                        """, (datetime.now().date(), str(escolha), float(qtd), k, p, c, g, "Não informado"))
                        conn.commit()
                    st.success("Registrado!")
                    st.rerun()
                except Exception as e:
                    conn.rollback()
                    st.error(f"Erro ao salvar: {e}")

# --- ABA 2: IMPORTAR DA IA (Parmegiana, Trufa, etc) ---
with tab_ia:
    st.subheader("Importar JSON da IA")
    st.info("Cole o JSON gerado pelo Gemini/GPT aqui.")
    json_input = st.text_area("JSON:", height=150)
    
    if st.button("Processar JSON"):
        if json_input:
            try:
                limpo = json_input.replace('```json', '').replace('```', '').strip()
                dados_ia = json.loads(limpo)
                for item in dados_ia:
                    gluten_status = item.get('gluten', 'Não informado')
                    with conn.cursor() as cur:
                        conn.rollback()
                        cur.execute("SET search_path TO public")
                        cur.execute("""
                            INSERT INTO public.consumo (data, alimento, quantidade, kcal, proteina, carbo, gordura, gluten) 
                            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                        """, (datetime.now().date(), item['alimento'], 1.0, float(item['kcal']), float(item['p']), float(item['c']), float(item['g']), gluten_status))
                        conn.commit()
                    st.success(f"Salvo: {item['alimento']}")
                st.rerun()
            except Exception as e:
                st.error(f"Erro: {e}")

# --- ABA 3: HISTÓRICO ---
with tab_hist:
    st.subheader("Registros Recentes")
    df_hist = ler_dados_periodo(7)
    if not df_hist.empty:
        for i, row in df_hist.iterrows():
            c1, c2, c3 = st.columns([3, 2, 0.5])
            c1.write(f"**{row['alimento']}**")
            gl_tag = "🚫" if row['gluten'] == "Contém" else ""
            c2.write(f"{int(row['kcal'])} kcal {gl_tag}")
            if c3.button("🗑️", key=f"d_{row['id']}"):
                deletar_registro("consumo", row['id'])
                st.rerun()

# --- ABA 4: PESO ---
with tab_peso:
    c1, c2 = st.columns([1,2])
    with c1:
        p_val = st.number_input("Peso (kg):", 40.0, 200.0, 145.0)
        if st.button("Gravar Peso"):
            with conn.cursor() as cur:
                conn.rollback()
                cur.execute("SET search_path TO public")
                cur.execute("INSERT INTO public.peso (data, peso_kg) VALUES (%s, %s)", (datetime.now().date(), float(p_val)))
                conn.commit()
            st.rerun()
    with c2:
        df_p = pd.read_sql("SELECT * FROM public.peso ORDER BY data DESC", conn)
        if not df_p.empty:
            st.line_chart(df_p.set_index('data'))
            st.dataframe(df_p)

# --- ABA 5: ADMIN ---
with tab_admin:
    if st.button("🚀 Sincronizar TACO (CSV)"):
        if carregar_csv_completo():
            st.success("Tabela TACO atualizada!")
            st.rerun()
