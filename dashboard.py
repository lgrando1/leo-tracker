import streamlit as st
import pandas as pd
import psycopg2
from datetime import datetime, timedelta
import pytz
import plotly.express as px
import plotly.graph_objects as go

# 1. CONFIGURAÇÃO VISUAL
st.set_page_config(page_title="Leo's Nutrition Dash", page_icon="🦁", layout="wide", initial_sidebar_state="collapsed")

# CSS para interface limpa (App-like)
st.markdown("""
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    .block-container {padding-top: 1rem; padding-bottom: 2rem;}
    /* Cards métricos estilizados */
    div[data-testid="stMetric"] {
        background-color: #f0f2f6;
        padding: 15px;
        border-radius: 10px;
        border: 1px solid #e0e0e0;
    }
    /* Modo escuro compatível */
    @media (prefers-color-scheme: dark) {
        div[data-testid="stMetric"] {
            background-color: #262730;
            border: 1px solid #464b5c;
        }
    }
    </style>
    """, unsafe_allow_html=True)

# --- 2. METAS DA NUTRICIONISTA ---
# Ajuste estes valores conforme seu PDF ou necessidade exata
META_KCAL = 1600
META_PROTEINA = 150  # 150g * 4kcal = 600kcal
META_CARBO = 130     # 130g * 4kcal = 520kcal (Low/Med Carb)
META_GORDURA = 53    # 53g * 9kcal = 477kcal (Restante)
META_PESO = 120.0
PERDA_SEMANAL_KG = 0.8

# --- 3. CONEXÃO E DADOS ---
@st.cache_resource(ttl=300)
def get_connection():
    return psycopg2.connect(st.secrets["DATABASE_URL"])

def get_now_br():
    return datetime.now(pytz.timezone('America/Sao_Paulo'))

def run_query(query, params=None):
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute("SET timezone TO 'America/Sao_Paulo';")
            if params: return pd.read_sql(query, conn, params=params)
            else: return pd.read_sql(query, conn)
    except Exception as e:
        st.error(f"Erro DB: {e}"); return pd.DataFrame()

# Carga de Dados
hoje = get_now_br().date()
# Token de segurança opcional via URL
if st.query_params.get("token") != st.secrets.get("DASH_ACCESS_TOKEN", st.query_params.get("token")): 
    pass # Se não tiver token configurado, deixa passar (ou ative a segurança se quiser)

df_hoje = run_query("SELECT * FROM public.consumo WHERE data = %s", (hoje,))
df_hist = run_query("""
    SELECT data, 
           SUM(kcal) as tkcal, SUM(proteina) as tprot, 
           SUM(carbo) as tcarb, SUM(gordura) as tgord 
    FROM public.consumo 
    WHERE data >= %s 
    GROUP BY data ORDER BY data ASC
""", (hoje - timedelta(days=30),))
df_peso = run_query("SELECT * FROM public.peso ORDER BY data ASC")

# --- 4. INDICADOR DE GLÚTEN (CORRIGIDO) ---
tem_gluten = False
itens_gluten = []
if not df_hoje.empty:
    col_gluten = df_hoje['gluten'].astype(str).str.lower()
    filtro = df_hoje[
        (col_gluten.str.contains('contém', na=False) & ~col_gluten.str.contains('não', na=False)) | 
        (col_gluten == 'sim')
    ]
    if not filtro.empty:
        tem_gluten = True
        itens_gluten = filtro['alimento'].unique().tolist()

# --- 5. INTERFACE DO DASHBOARD ---

# Header
c1, c2 = st.columns([3, 1])
c1.markdown("# 🦁 Leo's Nutrition")
c2.markdown(f"### {hoje.strftime('%d/%m')}")

# Alerta Glúten
if tem_gluten:
    st.error(f"⚠️ **GLÚTEN DETECTADO:** {', '.join(itens_gluten)}")
else:
    st.success("✅ **Dieta Limpa (Glúten-Free)**")

st.markdown("---")

# --- SEÇÃO 1: KPI MACROS (COMPARATIVO) ---
# Somas de hoje
k_act = df_hoje['kcal'].sum() if not df_hoje.empty else 0
p_act = df_hoje['proteina'].sum() if not df_hoje.empty else 0
c_act = df_hoje['carbo'].sum() if not df_hoje.empty else 0
g_act = df_hoje['gordura'].sum() if not df_hoje.empty else 0

# Colunas de Métricas
cols = st.columns(4)

# Função auxiliar para metricas com cor condicional
def metric_card(col, label, actual, target, suffix=""):
    delta = actual - target
    color = "inverse" if delta > 0 else "normal" # Vermelho se passou, Verde se falta (para kcal/gordura)
    if label == "Proteína": color = "normal" if delta >= 0 else "inverse" # Proteína é bom passar (ou chegar perto)
    
    col.metric(label, f"{int(actual)}{suffix}", f"{int(delta)}{suffix}", delta_color=color)
    # Barra de progresso customizada
    percent = min(actual / target, 1.0) if target > 0 else 0
    col.progress(percent)

metric_card(cols[0], "🔥 Calorias", k_act, META_KCAL)
metric_card(cols[1], "🥩 Proteína", p_act, META_PROTEINA, "g")
metric_card(cols[2], "🍞 Carbo", c_act, META_CARBO, "g")
metric_card(cols[3], "🥑 Gordura", g_act, META_GORDURA, "g")

st.markdown("---")

# --- SEÇÃO 2: ANÁLISE VISUAL AVANÇADA ---

g1, g2 = st.columns([2, 1])

with g1:
    st.subheader("📊 Evolução dos Macros (30 dias)")
    if not df_hist.empty:
        # Gráfico de Barras Empilhadas (Macros)
        fig_bar = go.Figure()
        fig_bar.add_trace(go.Bar(x=df_hist['data'], y=df_hist['tprot'], name='Proteína', marker_color='#3366CC'))
        fig_bar.add_trace(go.Bar(x=df_hist['data'], y=df_hist['tcarb'], name='Carbo', marker_color='#FF9900'))
        fig_bar.add_trace(go.Bar(x=df_hist['data'], y=df_hist['tgord'], name='Gordura', marker_color='#DC3912'))
        
        fig_bar.update_layout(barmode='stack', height=350, margin=dict(l=20, r=20, t=20, b=20), legend=dict(orientation="h", y=1.1))
        st.plotly_chart(fig_bar, use_container_width=True)
    else:
        st.info("Sem dados históricos.")

with g2:
    st.subheader("🎯 Distribuição de Hoje")
    if k_act > 0:
        # Gráfico de Donut (Distribuição Calórica)
        # 1g Prot = 4kcal, 1g Carb = 4kcal, 1g Fat = 9kcal
        labels = ['Proteína', 'Carbo', 'Gordura']
        values = [p_act * 4, c_act * 4, g_act * 9]
        colors = ['#3366CC', '#FF9900', '#DC3912']
        
        fig_pie = go.Figure(data=[go.Pie(labels=labels, values=values, hole=.5, marker=dict(colors=colors))])
        fig_pie.update_layout(height=350, margin=dict(l=20, r=20, t=20, b=20), showlegend=True)
        st.plotly_chart(fig_pie, use_container_width=True)
        
        # Pequeno texto de análise
        p_pct = (values[0] / sum(values)) * 100
        st.caption(f"Sua dieta hoje está **{int(p_pct)}% proteica**.")
    else:
        st.info("Registre refeições para ver a análise.")

# --- SEÇÃO 3: PESO E DETALHES ---
g3, g4 = st.columns([2, 1])

with g3:
    st.subheader("⚖️ Rumo à Meta")
    if not df_peso.empty and len(df_peso) > 1:
        df_peso['data'] = pd.to_datetime(df_peso['data'])
        # Projeção simples
        p_ini = df_peso.iloc[0]['peso_kg']; d_ini = df_peso.iloc[0]['data']
        dias = (df_peso.iloc[-1]['data'] - d_ini).days + 30
        
        dates_proj = [d_ini + timedelta(days=i) for i in range(dias)]
        vals_proj = [max(META_PESO, p_ini - (i * (PERDA_SEMANAL_KG/7))) for i in range(dias)]
        
        fig_p = go.Figure()
        fig_p.add_trace(go.Scatter(x=dates_proj, y=vals_proj, name='Meta Ideal', line=dict(color='gray', dash='dot')))
        fig_p.add_trace(go.Scatter(x=df_peso['data'], y=df_peso['peso_kg'], name='Real', mode='lines+markers', line=dict(color='blue', width=3)))
        
        fig_p.update_layout(height=300, margin=dict(l=20, r=20, t=20, b=20))
        st.plotly_chart(fig_p, use_container_width=True)
    else:
        st.warning("Faltam dados de peso.")

with g4:
    st.subheader("🍽️ Hoje")
    if not df_hoje.empty:
        # Exibição compacta
        for i, row in df_hoje.iterrows():
            st.markdown(f"**{row['alimento']}**")
            c1, c2, c3 = st.columns(3)
            c1.caption(f"🔥 {int(row['kcal'])}")
            c2.caption(f"🥩 {int(row['proteina'])}g")
            if 'contém' in str(row['gluten']).lower() and 'não' not in str(row['gluten']).lower():
                c3.error("Glúten!")
            st.divider()
    else:
        st.write("Nada registrado.")
