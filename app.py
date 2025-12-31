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
    st.error("Erro de conexão com o banco de dados.")
    st.stop()

# 3. METAS E CONFIGURAÇÕES
META_KCAL = 1600
META_PROTEINA = 150

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
                    id SERIAL PRIMARY KEY, data DATE, alimento TEXT, quantidade REAL, kcal REAL, proteina REAL, carbo REAL, gordura REAL
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS public.peso (
                    id SERIAL PRIMARY KEY, data DATE, peso_kg REAL
                );
            """)
            conn.commit()
    except Exception as e:
        conn.rollback()

def limpar_valor_taco(valor):
    if pd.isna(valor) or str(valor).strip().upper() in ['NA', 'TR', '', '-']:
        return 0.0
    try:
        return float(str(valor).replace(',', '.'))
    except:
        return 0.0

def carregar_csv_completo():
    try:
        if not os.path.exists('alimentos.csv'):
            st.error("Arquivo alimentos.csv não encontrado.")
            return False
        
        df = pd.read_csv('alimentos.csv', sep=';', encoding='latin-1')
        tabela_preparada = []
        for _, row in df.iterrows():
            tabela_preparada.append((
                str(row.iloc[2]),               
                float(limpar_valor_taco(row.iloc[4])),  
                float(limpar_valor_taco(row.iloc[6])),  
                float(limpar_valor_taco(row.iloc[9])),  
                float(limpar_valor_taco(row.iloc[7]))   
            ))

        with conn.cursor() as cur:
            conn.rollback()
            cur.execute("SET search_path TO public")
            cur.execute("TRUNCATE TABLE public.tabela_taco")
            cur.executemany(
                "INSERT INTO public.tabela_taco (alimento, kcal, proteina, carbo, gordura) VALUES (%s, %s, %s, %s, %s)", 
                tabela_preparada
            )
            conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        st.error(f"Erro no CSV: {e}")
        return False

def deletar_registro(tabela, id_registro):
    try:
        with conn.cursor() as cur:
            conn.rollback()
            cur.execute(f"DELETE FROM public.{tabela} WHERE id = %s", (id_registro,))
            conn.commit()
        return True
    except:
        return False

def buscar_alimento(termo):
    if not termo: return pd.DataFrame()
    try:
        return pd.read_sql("SELECT * FROM public.tabela_taco WHERE alimento ILIKE %s ORDER BY alimento ASC LIMIT 50", conn, params=(f'%{termo}%',))
    except:
        conn.rollback()
        return pd.DataFrame()

def ler_dados_periodo(dias=30):
    data_inicio = (datetime.now() - timedelta(days=dias)).date()
    try:
        return pd.read_sql("SELECT * FROM public.consumo WHERE data >= %s ORDER BY data DESC, id DESC", conn, params=(data_inicio,))
    except:
        conn.rollback()
        return pd.DataFrame()

# 5. INICIALIZAÇÃO
inicializar_banco()

# 6. INTERFACE PRINCIPAL
st.title("🦁 Leo Tracker Pro")
tab_prato, tab_plano, tab_hist, tab_peso, tab_admin = st.tabs(["🍽️ Registro", "📝 Meu Plano", "📊 Histórico", "⚖️ Peso", "⚙️ Admin"])

with tab_prato:
    df_hoje = ler_dados_periodo(0)
    kcal_hoje = float(df_hoje['kcal'].sum()) if not df_hoje.empty else 0.0
    prot_hoje = float(df_hoje['proteina'].sum()) if not df_hoje.empty else 0.0
    
    col_m1, col_m2 = st.columns(2)
    col_m1.metric("Calorias", f"{int(kcal_hoje)} / {META_KCAL} kcal", f"{int(META_KCAL - kcal_hoje)} kcal restando")
    col_m2.metric("Proteína", f"{int(prot_hoje)} / {META_PROTEINA}g", f"{int(META_PROTEINA - prot_hoje)}g restando")
    st.progress(min(kcal_hoje/META_KCAL, 1.0))
    
    st.divider()
    termo = st.text_input("🔍 O que comeu agora?")
    if termo:
        df_res = buscar_alimento(termo)
        if not df_res.empty:
            escolha = st.selectbox("Selecione:", df_res["alimento"])
            dados = df_res[df_res["alimento"] == escolha].iloc[0]
            qtd = st.number_input("Quantidade (g):", 0, 2000, 100)
            fator = float(qtd) / 100.0
            
            k = float(round(float(dados['kcal']) * fator))
            p = float(round(float(dados['proteina']) * fator, 1))
            c = float(round(float(dados['carbo']) * fator, 1))
            g = float(round(float(dados['gordura']) * fator, 1))
            
            st.info(f"🥘 {k} kcal | P: {p}g | C: {c}g")
            
            if st.button("Confirmar Refeição"):
                try:
                    with conn.cursor() as cur:
                        conn.rollback()
                        cur.execute("SET search_path TO public")
                        cur.execute("""
                            INSERT INTO public.consumo (data, alimento, quantidade, kcal, proteina, carbo, gordura) 
                            VALUES (%s,%s,%s,%s,%s,%s,%s)
                        """, (datetime.now().date(), str(escolha), float(qtd), k, p, c, g))
                        conn.commit()
                    st.success("Registrado!")
                    st.rerun()
                except Exception as e:
                    conn.rollback()
                    st.error(f"Erro ao salvar: {e}")

with tab_plano:
    st.header("📋 Orientações da Dieta")
    st.info("Foco: Controle glicémico, saciedade e preservação de massa muscular.")
    
    col_p1, col_p2 = st.columns(2)
    with col_p1:
        st.subheader("⏰ Horários e Refeições")
        with st.expander("🌅 Café da Manhã (07:00 - 08:30)"):
            st.write("- 3 ovos (mexidos ou cozidos)")
            st.write("- 1 porção de fruta (preferência mamão ou morango)")
            st.caption("Foco: Proteína logo ao acordar.")
            
        with st.expander("🍲 Almoço (12:00 - 13:30)"):
            st.write("- 100g de Arroz integral / Batata Doce")
            st.write("- 1 concha de Feijão")
            st.write("- 150g de Proteína magra (Frango ou Patinho)")
            st.write("- Salada verde à vontade")
            
        with st.expander("🍎 Lanche (16:00 - 17:00)"):
            st.write("- Iogurte natural ou 30g de castanhas")

        with st.expander("🌙 Jantar (19:30 - 20:30)"):
            st.write("- 150g de Proteína + Vegetais")
            st.write("- Evitar carboidratos simples à noite")

    with col_p2:
        st.subheader("💡 Regras de Ouro")
        st.warning("1. Beber 3L de água por dia.")
        st.warning("2. Zero açúcar e farinha branca.")
        st.warning("3. Priorizar proteínas em todas as refeições.")

with tab_hist:
    st.subheader("📊 Histórico de Refeições (Últimos 7 dias)")
    df_hist = ler_dados_periodo(7)
    if not df_hist.empty:
        for i, row in df_hist.iterrows():
            c1, c2, c3 = st.columns([1, 4, 1])
            c1.write(f"**{row['data']}**")
            c2.write(f"{row['alimento']} ({int(row['quantidade'])}g) - {int(row['kcal'])} kcal")
            if c3.button("🗑️", key=f"del_c_{row['id']}"):
                if deletar_registro("consumo", row['id']):
                    st.rerun()
            st.divider()
    else:
        st.info("Nenhum registro encontrado.")

with tab_peso:
    cp1, cp2 = st.columns([1, 2])
    with cp1:
        st.subheader("Registrar Peso")
        p_val = st.number_input("Peso (kg):", 40.0, 250.0, 145.0)
        data_p = st.date_input("Data do registro:", datetime.now())
        if st.button("Gravar Peso"):
            with conn.cursor() as cur:
                conn.rollback()
                cur.execute("INSERT INTO public.peso (data, peso_kg) VALUES (%s, %s)", (data_p, float(p_val)))
                conn.commit()
            st.success("Gravado!")
            st.rerun()
    with cp2:
        st.subheader("Histórico de Peso")
        df_p = pd.read_sql("SELECT * FROM public.peso ORDER BY data DESC, id DESC", conn)
        if not df_p.empty:
            for i, row in df_p.iterrows():
                p_c1, p_c2, p_c3 = st.columns([2, 2, 1])
                p_c1.write(row['data'])
                p_c2.write(f"**{row['peso_kg']} kg**")
                if p_c3.button("🗑️", key=f"del_p_{row['id']}"):
                    if deletar_registro("peso", row['id']):
                        st.rerun()

with tab_admin:
    st.subheader("⚙️ Configurações de Sistema")
    
    with st.expander("➕ Cadastrar Alimento Manualmente"):
        nome_novo = st.text_input("Nome do Alimento:")
        c1, c2, c3, c4 = st.columns(4)
        kcal_n = c1.number_input("Kcal (100g)", 0.0)
        prot_n = c2.number_input("Prot (100g)", 0.0)
        carb_n = c3.number_input("Carb (100g)", 0.0)
        gord_n = c4.number_input("Gord (100g)", 0.0)
        
        if st.button("Salvar Novo Alimento"):
            if nome_novo:
                try:
                    with conn.cursor() as cur:
                        conn.rollback()
                        cur.execute("SET search_path TO public")
                        cur.execute("INSERT INTO public.tabela_taco (alimento, kcal, proteina, carbo, gordura) VALUES (%s,%s,%s,%s,%s)",
                                    (nome_novo, float(kcal_n), float(prot_n), float(carb_n), float(gord_n)))
                        conn.commit()
                    st.success(f"{nome_novo} adicionado com sucesso!")
                except Exception as e:
                    conn.rollback()
                    st.error(f"Erro ao cadastrar: {e}")
            else:
                st.warning("Por favor, insira o nome do alimento.")

    st.divider()
    if st.button("🚀 Sincronizar Alimentos (CSV -> Banco)"):
        with st.spinner("Processando base de dados..."):
            if carregar_csv_completo():
                st.success("Sincronização concluída com sucesso!")
                st.rerun()
