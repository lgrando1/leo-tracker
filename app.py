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

# 3. METAS DA NUTRICIONISTA
META_KCAL = 2000
META_PROT = 160

# 4. FUNÇÕES DE BANCO DE DADOS E MIGRAÇÃO
def inicializar_banco():
    try:
        with conn.cursor() as cur:
            conn.rollback() # Limpa transações falhas
            cur.execute("SET search_path TO public")
            
            # Tabela de referência
            cur.execute("""
                CREATE TABLE IF NOT EXISTS public.tabela_taco (
                    id SERIAL PRIMARY KEY, alimento TEXT, kcal REAL, proteina REAL, carbo REAL, gordura REAL
                );
            """)
            
            # Tabela de consumo com a nova coluna de tempo
            cur.execute("""
                CREATE TABLE IF NOT EXISTS public.consumo (
                    id SERIAL PRIMARY KEY, 
                    data_hora TIMESTAMP DEFAULT CURRENT_TIMESTAMP, 
                    alimento TEXT, quantidade REAL, kcal REAL, proteina REAL, carbo REAL, gordura REAL, 
                    gluten TEXT DEFAULT 'Não informado'
                );
            """)
            
            # MIGRAÇÃO: Se a coluna data_hora não existir, nós adicionamos ela
            cur.execute("""
                DO $$ 
                BEGIN 
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='consumo' AND column_name='data_hora') THEN
                        ALTER TABLE public.consumo ADD COLUMN data_hora TIMESTAMP DEFAULT CURRENT_TIMESTAMP;
                    END IF;
                END $$;
            """)
            
            cur.execute("CREATE TABLE IF NOT EXISTS public.peso (id SERIAL PRIMARY KEY, data DATE, peso_kg REAL);")
            conn.commit()
    except Exception as e:
        conn.rollback()
        st.error(f"Erro na inicialização: {e}")

def limpar_valor_taco(valor):
    if pd.isna(valor) or str(valor).strip() in ['NA', 'TR', '', '*', '-']: return 0.0
    try:
        return float(str(valor).replace(',', '.'))
    except: return 0.0

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
tabs = st.tabs(["🍽️ Registro", "🤖 IA", "📈 Dieta vs Meta", "⚖️ Peso", "⚙️ Admin"])

with tabs[0]:
    st.subheader("Registro Manual (Busca TACO)")
    termo = st.text_input("🔍 Pesquisar alimento:")
    if termo:
        try:
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
                    st.rerun()
        except: conn.rollback()

with tabs[1]:
    st.subheader("🤖 Importar via IA")
    st.markdown("""
    **Como pedir para a IA:**
    > *Analise a refeição: [DESCREVA O QUE COMEU]. Retorne apenas o JSON: [{"alimento": "nome", "kcal": 0, "p": 0, "c": 0, "g": 0, "gluten": "Contém/Não contém"}]*
    """)
    json_in = st.text_area("Cole o JSON da IA aqui:")
    if st.button("Processar e Salvar"):
        try:
            dados = json.loads(json_in.replace('```json', '').replace('```', '').strip())
            with conn.cursor() as cur:
                conn.rollback()
                for i in dados:
                    cur.execute("""INSERT INTO public.consumo (alimento, quantidade, kcal, proteina, carbo, gordura, gluten) 
                                   VALUES (%s,1,%s,%s,%s,%s,%s)""", (i['alimento'], i['kcal'], i['p'], i['c'], i['g'], i.get('gluten','Não informado')))
                conn.commit()
            st.success("Importado com sucesso!")
            st.rerun()
        except Exception as e: st.error(f"Erro no JSON: {e}")

with tabs[2]:
    st.subheader("📊 Progresso Diário")
    try:
        df_hoje = pd.read_sql("SELECT * FROM public.consumo WHERE data_hora::date = CURRENT_DATE", conn)
        
        if not df_hoje.empty:
            c1, c2 = st.columns(2)
            cons_kcal = df_hoje['kcal'].sum()
            cons_prot = df_hoje['proteina'].sum()
            
            c1.metric("Energia", f"{int(cons_kcal)} / {META_KCAL} kcal", f"{int(cons_kcal - META_KCAL)} kcal")
            c2.metric("Proteína", f"{int(cons_prot)}g / {META_PROT}g", f"{int(cons_prot - META_PROT)}g")
            
            # Gráfico Comparativo
            df_plot = pd.DataFrame({
                'Métrica': ['Calorias', 'Proteína'],
                'Consumido': [cons_kcal, cons_prot],
                'Meta': [META_KCAL, META_PROT]
            })
            fig = px.bar(df_plot, x='Métrica', y=['Consumido', 'Meta'], barmode='group', color_discrete_map={'Consumido': '#FF4B4B', 'Meta': '#31333F'})
            st.plotly_chart(fig, use_container_width=True)
            
            st.subheader("🕒 Histórico de Hoje")
            df_hoje['hora'] = pd.to_datetime(df_hoje['data_hora']).dt.strftime('%H:%M')
            # Exibe com botão de deletar
            for i, row in df_hoje.iterrows():
                col_h1, col_h2, col_h3 = st.columns([1, 4, 1])
                col_h1.write(row['hora'])
                col_h2.write(f"**{row['alimento']}** - {int(row['kcal'])} kcal ({row['gluten']})")
                if col_h3.button("🗑️", key=f"del_{row['id']}"):
                    if deletar_registro("consumo", row['id']): st.rerun()
        else:
            st.info("Nenhuma refeição registrada hoje.")
    except: conn.rollback()

with tabs[3]:
    st.subheader("⚖️ Controle de Peso")
    # Lógica de peso simplificada
    p_val = st.number_input("Peso hoje (kg):", 40.0, 250.0, 145.0)
    if st.button("Gravar Peso"):
        with conn.cursor() as cur:
            conn.rollback()
            cur.execute("INSERT INTO public.peso (data, peso_kg) VALUES (%s, %s)", (datetime.now().date(), float(p_val)))
            conn.commit()
        st.success("Gravado!")
        st.rerun()

with tabs[4]:
    st.subheader("⚙️ Admin")
    with st.expander("➕ Inserir Alimento Manual"):
        n_m = st.text_input("Nome:")
        k_m = st.number_input("Kcal/100g")
        p_m = st.number_input("Prot/100g")
        if st.button("Cadastrar"):
            with conn.cursor() as cur:
                conn.rollback()
                cur.execute("INSERT INTO public.tabela_taco (alimento, kcal, proteina, carbo, gordura) VALUES (%s,%s,%s,0,0)", (n_m, k_m, p_m))
                conn.commit()
            st.success("Salvo na base!")

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
            st.success("CSV Sincronizado!")
        except Exception as e: st.error(f"Erro: {e}")
