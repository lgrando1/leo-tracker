import streamlit as st
import pandas as pd
import psycopg2
from datetime import datetime, timedelta
import pytz
import plotly.express as px # Vamos usar Plotly para gráficos mais bonitos
import plotly.graph_objects as go

# 1. CONFIGURAÇÃO (Modo Leitura / Wide)
st.set_page_config(page_title="Leo's Dashboard", page_icon="📈", layout="wide", initial_sidebar_state="collapsed")

# CSS para esconder menus e deixar limpo (Parece um app nativo)
st.markdown("""
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    .block-container {padding-top: 1rem; padding-bottom: 0rem;}
    </style>
    """, unsafe_allow_html=True)

# --- CONFIGURAÇÕES E METAS ---
META_KCAL = 1600
META_PROTEINA = 150
META_PESO = 120.0
PERDA_SEMANAL_KG = 0.8

# --- CONEXÃO AO BANCO (MESMA DO OUTRO APP) ---
@st.cache_resource(ttl=300) # Cache de 5 min para não gastar conexões à toa
def get_connection():
    return psycopg2.connect(st.secrets["DATABASE_URL"])

def get_now_br():
    return datetime.now(pytz.timezone('America/Sao_Paulo'))

def run_query(query, params=None):
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute("SET timezone TO 'America/Sao_Paulo';")
            if params:
                return pd.read_sql(query, conn, params=params)
            else:
                return pd.read_sql(query, conn)
    except Exception as e:
        st.error(f"Erro de conexão: {e}")
        return pd.DataFrame()

# --- CARREGAMENTO DE DADOS ---
hoje = get_now_br().date()
inicio_mes = hoje.replace(day=1)
inicio_semana = hoje - timedelta(days=7)

# 1. Dados de Hoje
df_hoje = run_query("SELECT * FROM public.consumo WHERE data = %s", (hoje,))

# 2. Histórico (Últimos 30 dias)
df_hist = run_query("""
    SELECT data, SUM(kcal) as total_kcal, SUM(proteina) as total_prot 
    FROM public.consumo 
    WHERE data >= %s 
    GROUP BY data 
    ORDER BY data ASC
""", (hoje - timedelta(days=30),))

# 3. Peso
df_peso = run_query("SELECT * FROM public.peso ORDER BY data ASC")

# --- VISUALIZAÇÃO ---

# HEADER
col_title, col_date = st.columns([3, 1])
col_title.markdown("# 🦁 Leo's Performance")
col_date.markdown(f"### {hoje.strftime('%d/%m/%Y')}")

st.divider()

# --- SEÇÃO 1: KPI DO DIA ---
# Cálculos
kcal_atual = df_hoje['kcal'].sum() if not df_hoje.empty else 0
prot_atual = df_hoje['proteina'].sum() if not df_hoje.empty else 0
gord_atual = df_hoje['gordura'].sum() if not df_hoje.empty else 0
carb_atual = df_hoje['carbo'].sum() if not df_hoje.empty else 0

kpi1, kpi2, kpi3, kpi4 = st.columns(4)

# Lógica de cor para calorias (Verde se ok, Vermelho se estourou muito)
delta_kcal = META_KCAL - kcal_atual
cor_kcal = "normal" if delta_kcal >= 0 else "inverse"

kpi1.metric("🔥 Calorias Hoje", f"{int(kcal_atual)}", f"{int(delta_kcal)} restantes", delta_color=cor_kcal)
kpi2.metric("🥩 Proteína Hoje", f"{int(prot_atual)}g", f"{int(prot_atual - META_PROTEINA)}g da meta")
kpi3.metric("🍞 Carbo Hoje", f"{int(carb_atual)}g")
kpi4.metric("🥑 Gordura Hoje", f"{int(gord_atual)}g")

# Barra de progresso visual
st.caption("Progresso da Meta Calórica:")
st.progress(min(kcal_atual / META_KCAL, 1.0))

st.divider()

# --- SEÇÃO 2: GRÁFICOS DE TENDÊNCIA ---

c_graf1, c_graf2 = st.columns(2)

with c_graf1:
    st.subheader("📅 Consumo Calórico (30 dias)")
    if not df_hist.empty:
        # Gráfico Combinado (Barra + Linha de Meta)
        fig_cal = go.Figure()
        
        # Barras de consumo
        fig_cal.add_trace(go.Bar(
            x=df_hist['data'], 
            y=df_hist['total_kcal'], 
            name='Consumido',
            marker_color='#4CAF50'
        ))
        
        # Linha de Meta
        fig_cal.add_trace(go.Scatter(
            x=df_hist['data'], 
            y=[META_KCAL]*len(df_hist), 
            mode='lines', 
            name='Meta (1600)', 
            line=dict(color='red', width=2, dash='dash')
        ))
        
        fig_cal.update_layout(height=350, margin=dict(l=20, r=20, t=20, b=20), showlegend=False)
        st.plotly_chart(fig_cal, use_container_width=True)
    else:
        st.info("Sem dados suficientes.")

with c_graf2:
    st.subheader("⚖️ Projeção de Peso")
    if not df_peso.empty and len(df_peso) > 1:
        df_peso['data'] = pd.to_datetime(df_peso['data'])
        
        # Criação da linha de tendência ideal (igual ao app principal)
        primeira_data = df_peso.iloc[0]['data']
        primeiro_peso = df_peso.iloc[0]['peso_kg']
        ultimo_dia = df_peso.iloc[-1]['data']
        dias_totais = (ultimo_dia - primeira_data).days + 45 # Projeção de 45 dias
        
        datas_meta = [primeira_data + timedelta(days=x) for x in range(dias_totais)]
        pesos_meta = [max(META_PESO, primeiro_peso - (x * (PERDA_SEMANAL_KG/7))) for x in range(dias_totais)]
        
        fig_peso = go.Figure()
        
        # Linha Ideal
        fig_peso.add_trace(go.Scatter(
            x=datas_meta, y=pesos_meta, mode='lines', name='Meta Saudável',
            line=dict(color='gray', dash='dot')
        ))
        
        # Linha Real
        fig_peso.add_trace(go.Scatter(
            x=df_peso['data'], y=df_peso['peso_kg'], mode='lines+markers', name='Real',
            line=dict(color='blue', width=3)
        ))
        
        fig_peso.update_layout(height=350, margin=dict(l=20, r=20, t=20, b=20))
        st.plotly_chart(fig_peso, use_container_width=True)
    else:
        st.warning("Adicione pelo menos 2 registros de peso.")

# --- SEÇÃO 3: O QUE COMI HOJE? ---
st.subheader("🍽️ Refeições de Hoje")
if not df_hoje.empty:
    # Tabela simples e limpa
    df_display = df_hoje[['alimento', 'kcal', 'proteina']].copy()
    df_display.columns = ['Alimento', 'Kcal', 'Proteína (g)']
    st.dataframe(df_display, use_container_width=True, hide_index=True)
else:
    st.info("Nenhum registro hoje. Vá ao Leo Tracker para adicionar.")
