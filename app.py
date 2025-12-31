import streamlit as st
import pandas as pd
import psycopg2
from datetime import datetime, timedelta
import plotly.express as px # Biblioteca bonita para gráficos

st.set_page_config(page_title="Leo Tracker Pro", page_icon="🦁", layout="wide")

# --- 1. CONEXÃO NEON ---
@st.cache_resource
def init_connection():
    return psycopg2.connect(st.secrets["DATABASE_URL"])

conn = init_connection()

# --- 2. DICIONÁRIO DE MEDIDAS CASEIRAS (O "Estimador") ---
# Média padrão brasileira (base TACO/IBGE)
MEDIDAS_CASEIRAS = {
    "arroz": {"unidade": "Colher de Sopa Cheia", "g": 25},
    "feijão": {"unidade": "Concha Média", "g": 86}, # 50% caldo / 50% grão
    "frango": {"unidade": "Filé Médio", "g": 100},
    "carne": {"unidade": "Bife Médio", "g": 100},
    "carne moida": {"unidade": "Colher de Sopa", "g": 30},
    "batata doce": {"unidade": "Fatia Média/Rodela", "g": 40},
    "mandioca": {"unidade": "Pedaço Médio", "g": 50},
    "aveia": {"unidade": "Colher de Sopa", "g": 15},
    "azeite": {"unidade": "Fio / Colher Sobremesa", "g": 8},
    "whey": {"unidade": "Dosador (Scoop)", "g": 30},
    "banana": {"unidade": "Unidade Média", "g": 60},
    "ovo": {"unidade": "Unidade", "g": 50},
    "pão": {"unidade": "Fatia", "g": 25},
    "queijo": {"unidade": "Fatia", "g": 20}
}

# --- 3. FUNÇÕES SQL ---
def buscar_alimento(termo):
    if not termo: return pd.DataFrame()
    # Busca inteligente no banco
    return pd.read_sql("SELECT * FROM tabela_taco WHERE alimento ILIKE %s LIMIT 15", conn, params=(f'%{termo}%',))

def salvar_consumo(data, alimento, qtd, macros):
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO consumo (data, alimento, quantidade, kcal, proteina, carbo, gordura) 
               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (data, alimento, qtd, macros['kcal'], macros['proteina'], macros['carbo'], macros['gordura'])
        )
        conn.commit()

def ler_dados_periodo(dias=30):
    data_inicio = datetime.now() - timedelta(days=dias)
    return pd.read_sql("SELECT * FROM consumo WHERE data >= %s ORDER BY data DESC", conn, params=(data_inicio,))

def ler_peso():
    return pd.read_sql("SELECT * FROM peso ORDER BY data ASC", conn)

# --- 4. INTERFACE ---
st.title("🦁 Leo Tracker Pro")

# Criação de Abas
tab_prato, tab_dash, tab_peso = st.tabs(["🍽️ Montar Prato", "📊 Dashboard", "⚖️ Peso"])

# ==================================================
# ABA 1: ESTIMADOR DE PRATOS
# ==================================================
with tab_prato:
    st.subheader("O que vai comer?")
    
    col_busca, col_data = st.columns([3, 1])
    with col_busca:
        termo = st.text_input("🔍 Pesquise (ex: Arroz, Carne, Molho)")
    with col_data:
        data_reg = st.date_input("Data", datetime.now())

    if termo:
        df_res = buscar_alimento(termo)
        if not df_res.empty:
            escolha = st.selectbox("Selecione o alimento exato:", df_res["alimento"])
            dados_alimento = df_res[df_res["alimento"] == escolha].iloc[0]

            # --- LÓGICA DO ESTIMADOR ---
            st.markdown("---")
            st.write("📏 **Como vai medir?**")
            
            # Tenta encontrar uma medida caseira compatível pelo nome
            medida_sugerida = None
            nome_lower = escolha.lower()
            
            for chave, info in MEDIDAS_CASEIRAS.items():
                if chave in nome_lower:
                    medida_sugerida = info
                    break
            
            gramas_finais = 0
            
            c1, c2 = st.columns(2)
            with c1:
                tipo_medida = st.radio("Unidade:", ["Medida Caseira (Colher, Fatia...)", "Gramas (Balança)"], horizontal=True)
            
            with c2:
                if tipo_medida == "Gramas (Balança)":
                    gramas_finais = st.number_input("Peso em gramas:", 0, 1000, 100, step=10)
                else:
                    if medida_sugerida:
                        nome_medida = medida_sugerida['unidade']
                        peso_medida = medida_sugerida['g']
                        qtd_caseira = st.number_input(f"Quantas '{nome_medida}'?", 0.0, 20.0, 1.0, step=0.5)
                        gramas_finais = qtd_caseira * peso_medida
                        st.caption(f"ℹ️ Estimativa: {qtd_caseira} x {nome_medida} ≈ **{gramas_finais:.0f}g**")
                    else:
                        st.warning("⚠️ Não tenho medida caseira cadastrada para este item. Use gramas ou cadastre no código.")
                        gramas_finais = st.number_input("Peso em gramas:", 0, 1000, 100)

            # --- CÁLCULO E BOTÃO ---
            if gramas_finais > 0:
                fator = gramas_finais / 100
                k = round(dados_alimento['kcal'] * fator)
                p = round(dados_alimento['proteina'] * fator, 1)
                c = round(dados_alimento['carbo'] * fator, 1)
                g = round(dados_alimento['gordura'] * fator, 1)

                st.success(f"🥘 **Prato:** {k} kcal | P: {p}g | C: {c}g | G: {g}g")
                
                if st.button("✅ Confirmar e Salvar"):
                    macros = {'kcal': k, 'proteina': p, 'carbo': c, 'gordura': g}
                    salvar_consumo(data_reg, escolha, gramas_finais, macros)
                    st.toast("Refeição salva com sucesso!", icon="🎉")

# ==================================================
# ABA 2: DASHBOARD
# ==================================================
with tab_dash:
    st.header("📊 Seu Desempenho")
    
    # Pegar dados
    df_dados = ler_dados_periodo(30) # Últimos 30 dias
    
    if not df_dados.empty:
        # Filtrar dados de hoje
        hoje_str = str(datetime.now().date())
        df_hoje = df_dados[df_dados['data'].astype(str) == hoje_str]
        
        # --- CARDS DE HOJE ---
        k_hoje = df_hoje['kcal'].sum()
        p_hoje = df_hoje['proteina'].sum()
        c_hoje = df_hoje['carbo'].sum()
        
        # Metas (Exemplo base dieta Léo)
        META_KCAL = 1500
        META_PROT = 110
        
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Calorias Hoje", f"{k_hoje:.0f}", f"{k_hoje - META_KCAL:.0f} da meta")
        col2.metric("Proteína", f"{p_hoje:.1f}g", f"{p_hoje - META_PROT:.1f}g", delta_color="normal")
        col3.metric("Carbo", f"{c_hoje:.1f}g")
        col4.metric("Gordura", f"{df_hoje['gordura'].sum():.1f}g")
        
        st.divider()

        # --- GRÁFICOS ---
        c_chart1, c_chart2 = st.columns(2)
        
        with c_chart1:
            st.subheader("📅 Evolução Diária (Kcal)")
            # Agrupar por dia
            df_dia = df_dados.groupby('data')[['kcal', 'proteina']].sum().reset_index()
            fig_bar = px.bar(df_dia, x='data', y='kcal', color='kcal', title="Calorias nos últimos 30 dias")
            # Adicionar linha de meta
            fig_bar.add_hline(y=META_KCAL, line_dash="dot", annotation_text="Meta", line_color="red")
            st.plotly_chart(fig_bar, use_container_width=True)
            
        with c_chart2:
            st.subheader("🥩 Proteína vs Meta")
            fig_line = px.line(df_dia, x='data', y='proteina', markers=True, title="Ingestão de Proteína")
            fig_line.add_hline(y=META_PROT, line_dash="dot", annotation_text="Meta Proteína", line_color="green")
            st.plotly_chart(fig_line, use_container_width=True)

        # --- ÚLTIMOS REGISTOS ---
        with st.expander("Ver Histórico Detalhado (Tabela)"):
            st.dataframe(df_dados)

    else:
        st.info("Ainda não há dados suficientes para gerar gráficos.")

# ==================================================
# ABA 3: PESO
# ==================================================
with tab_peso:
    df_p = ler_peso()
    
    col_input, col_graph = st.columns([1, 2])
    
    with col_input:
        st.subheader("Nova Pesagem")
        novo_p = st.number_input("Peso (kg):", 50.0, 200.0, step=0.1)
        if st.button("Gravar Peso"):
            with conn.cursor() as cur:
                cur.execute("INSERT INTO peso (data, peso_kg) VALUES (%s, %s)", (datetime.now(), novo_p))
                conn.commit()
            st.success("Peso salvo!")
            st.rerun()

    with col_graph:
        if not df_p.empty:
            fig_peso = px.line(df_p, x='data', y='peso_kg', markers=True, title="Evolução do Peso")
            st.plotly_chart(fig_peso, use_container_width=True)
            
            p_inicial = df_p.iloc[0]['peso_kg']
            p_atual = df_p.iloc[-1]['peso_kg']
            perda = p_inicial - p_atual
            
            if perda > 0:
                st.success(f"📉 Total Eliminado: **{perda:.1f} kg**")
            else:
                st.warning(f"Diferença: {perda:.1f} kg")
