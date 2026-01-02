import streamlit as st
import pandas as pd
import psycopg2
from datetime import datetime, timedelta
import pytz
import plotly.express as px
import plotly.graph_objects as go

# 1. CONFIGURAÇÃO VISUAL
st.set_page_config(page_title="Leo's Nutrition Dash", page_icon="🦁", layout="wide", initial_sidebar_state="collapsed")

# CSS para interface limpa
st.markdown("""
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    .block-container {padding-top: 1rem; padding-bottom: 2rem;}
    div[data-testid="stMetric"] {
        background-color: #f0f2f6;
        padding: 15px;
        border-radius: 10px;
        border: 1px solid #e0e0e0;
    }
    @media (prefers-color-scheme: dark) {
        div[data-testid="stMetric"] {
            background-color: #262730;
            border: 1px solid #464b5c;
        }
    }
    </style>
    """, unsafe_allow_html=True)

# --- 2. METAS REAIS (Baseadas no PDF Marcela Mello) ---
META_KCAL = 1650
META_PROTEINA = 110  
META_CARBO = 200     
META_GORDURA = 50    
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
if st.query_params.get("token") != st.secrets.get("DASH_ACCESS_TOKEN", st.query_params.get("token")): pass 

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

# --- 4. INDICADOR DE GLÚTEN ---
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

# --- HELPER: FUNÇÃO PARA GERAR GRÁFICOS ---
def create_macro_chart(df, date_col, val_col, meta_val, title, color):
    fig = go.Figure()
    # Barra (Realizado)
    fig.add_trace(go.Bar(
        x=df[date_col], 
        y=df[val_col], 
        name='Realizado',
        marker_color=color
    ))
    # Linha (Meta)
    fig.add_trace(go.Scatter(
        x=df[date_col], 
        y=[meta_val]*len(df), 
        mode='lines', 
        name='Meta', 
        line=dict(color='gray', width=2, dash='dash')
    ))
    fig.update_layout(
        title=dict(text=title, font=dict(size=14)),
        height=250, 
        margin=dict(l=10, r=10, t=40, b=20),
        showlegend=False,
        yaxis=dict(showgrid=True, gridcolor='rgba(128,128,128,0.2)')
    )
    return fig

# --- 5. INTERFACE DO DASHBOARD ---

# Header
c1, c2 = st.columns([3, 1])
c1.markdown("# 🦁 Leo's Performance")
c2.markdown(f"### {hoje.strftime('%d/%m')}")

if tem_gluten:
    st.error(f"⚠️ **GLÚTEN DETECTADO:** {', '.join(itens_gluten)}")
else:
    st.success("✅ **Dieta Limpa (Glúten-Free)**")

st.markdown("---")

# --- SEÇÃO 1: KPI MACROS ---
k_act = df_hoje['kcal'].sum() if not df_hoje.empty else 0
p_act = df_hoje['proteina'].sum() if not df_hoje.empty else 0
c_act = df_hoje['carbo'].sum() if not df_hoje.empty else 0
g_act = df_hoje['gordura'].sum() if not df_hoje.empty else 0

cols = st.columns(4)

def metric_card(col, label, actual, target, suffix=""):
    delta = actual - target
    color = "inverse" if (label in ["🔥 Calorias", "🥑 Gordura"] and delta > 0) else "normal"
    col.metric(label, f"{int(actual)}{suffix}", f"Meta: {target}{suffix}", delta_color="off")
    percent = min(actual / target, 1.0) if target > 0 else 0
    col.progress(percent)

metric_card(cols[0], "🔥 Calorias", k_act, META_KCAL)
metric_card(cols[1], "🥩 Proteína", p_act, META_PROTEINA, "g")
metric_card(cols[2], "🍞 Carbo", c_act, META_CARBO, "g")
metric_card(cols[3], "🥑 Gordura", g_act, META_GORDURA, "g")

st.markdown("---")

# --- SEÇÃO 2: PRINCIPAL (Calorias e Distribuição) ---
g1, g2 = st.columns([2, 1])

with g1:
    st.subheader("📊 Calorias vs Meta (30 dias)")
    if not df_hist.empty:
        fig = go.Figure()
        fig.add_trace(go.Bar(x=df_hist['data'], y=df_hist['tkcal'], name='Kcal', marker_color='#4CAF50'))
        fig.add_trace(go.Scatter(x=df_hist['data'], y=[META_KCAL]*len(df_hist), mode='lines', name='Meta', line=dict(color='red', width=3, dash='dot')))
        fig.update_layout(height=320, margin=dict(l=20, r=20, t=20, b=20), legend=dict(orientation="h", y=1.1))
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Sem dados históricos.")

with g2:
    st.subheader("🎯 Distribuição Hoje")
    if k_act > 0:
        labels = ['Proteína', 'Carbo', 'Gordura']
        values = [p_act * 4, c_act * 4, g_act * 9]
        colors = ['#3366CC', '#FF9900', '#DC3912']
        fig_pie = go.Figure(data=[go.Pie(labels=labels, values=values, hole=.5, marker=dict(colors=colors))])
        fig_pie.update_layout(height=320, margin=dict(l=20, r=20, t=20, b=20), showlegend=True)
        st.plotly_chart(fig_pie, use_container_width=True)
    else:
        st.info("Registre para ver.")

# --- SEÇÃO 3: CONTROLE DE MACROS (NOVOS GRÁFICOS) ---
st.subheader("🔍 Controle Semanal de Macros")
if not df_hist.empty:
    m1, m2, m3 = st.columns(3)
    
    with m1:
        fig_p = create_macro_chart(df_hist, 'data', 'tprot', META_PROTEINA, "🥩 Proteína (Meta: 110g)", "#3366CC")
        st.plotly_chart(fig_p, use_container_width=True)
        
    with m2:
        fig_c = create_macro_chart(df_hist, 'data', 'tcarb', META_CARBO, "🍞 Carbo (Meta: 200g)", "#FF9900")
        st.plotly_chart(fig_c, use_container_width=True)
        
    with m3:
        fig_g = create_macro_chart(df_hist, 'data', 'tgord', META_GORDURA, "🥑 Gordura (Meta: 50g)", "#DC3912")
        st.plotly_chart(fig_g, use_container_width=True)
else:
    st.info("Sem dados para exibir gráficos de macros.")

st.markdown("---")

# --- SEÇÃO 4: PESO E HOJE ---
g3, g4 = st.columns([2, 1])

with g3:
    st.subheader("⚖️ Rumo aos 120kg")
    if not df_peso.empty and len(df_peso) > 1:
        df_peso['data'] = pd.to_datetime(df_peso['data'])
        p_ini = df_peso.iloc[0]['peso_kg']; d_ini = df_peso.iloc[0]['data']
        ultimo_dia_reg = df_peso.iloc[-1]['data']
        dias_totais = (ultimo_dia_reg - d_ini).days + 30
        dates_proj = [d_ini + timedelta(days=i) for i in range(dias_totais)]
        vals_proj = [max(META_PESO, p_ini - (i * (PERDA_SEMANAL_KG/7))) for i in range(dias_totais)]
        
        fig_p = go.Figure()
        fig_p.add_trace(go.Scatter(x=dates_proj, y=vals_proj, name='Meta Ideal', line=dict(color='gray', dash='dot')))
        fig_p.add_trace(go.Scatter(x=df_peso['data'], y=df_peso['peso_kg'], name='Real', mode='lines+markers', line=dict(color='blue', width=4)))
        fig_p.update_layout(height=300, margin=dict(l=20, r=20, t=20, b=20))
        st.plotly_chart(fig_p, use_container_width=True)
    else:
        st.warning("Adicione mais registros de peso.")

with g4:
    st.subheader("🍽️ Hoje")
    if not df_hoje.empty:
        for i, row in df_hoje.iterrows():
            st.markdown(f"**{row['alimento']}**")
            c1, c2, c3 = st.columns(3)
            c1.caption(f"🔥 {int(row['kcal'])}")
            c2.caption(f"🥩 {int(row['proteina'])}g")
            # Verifica glúten com lógica segura
            g_txt = str(row['gluten']).lower()
            if ('contém' in g_txt or 'sim' in g_txt) and 'não' not in g_txt:
                c3.error("Glúten!")
            st.divider()
    else:
        st.write("Nada registrado.")
