import streamlit as st
import pandas as pd
import psycopg2
from datetime import datetime, timedelta
import pytz
import plotly.express as px
import plotly.graph_objects as go

# 1. CONFIGURAÇÃO VISUAL
st.set_page_config(page_title="Leo's Nutrition Dash", page_icon="🦁", layout="wide", initial_sidebar_state="expanded")

# CSS para interface
st.markdown("""
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    .block-container {padding-top: 1rem; padding-bottom: 2rem;}
    div[data-testid="stMetric"] {
        background-color: #f0f2f6;
        padding: 10px;
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

# --- CONEXÃO E DADOS INICIAIS ---
@st.cache_resource(ttl=300)
def get_connection():
    return psycopg2.connect(st.secrets["DATABASE_URL"])

def run_query(query, params=None):
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute("SET timezone TO 'America/Sao_Paulo';")
            if params: return pd.read_sql(query, conn, params=params)
            else: return pd.read_sql(query, conn)
    except Exception as e:
        st.error(f"Erro DB: {e}"); return pd.DataFrame()

# Pega peso atual para a calculadora
df_peso_last = run_query("SELECT peso_kg FROM public.peso ORDER BY data DESC LIMIT 1")
PESO_ATUAL = float(df_peso_last.iloc[0]['peso_kg']) if not df_peso_last.empty else 125.0

# --- 2. BARRA LATERAL (CALCULADORA CIENTÍFICA) ---
st.sidebar.header("🧮 Calculadora Metabólica")

with st.sidebar.expander("📝 Seus Dados Biométricos", expanded=True):
    genero = st.radio("Gênero:", ["Masculino", "Feminino"], horizontal=True)
    idade = st.number_input("Idade:", value=35, step=1)
    altura_cm = st.number_input("Altura (cm):", value=180, step=1)
    peso_calc = st.number_input("Peso Atual (kg):", value=PESO_ATUAL, step=0.1)

st.sidebar.subheader("🏃‍♂️ Nível de Atividade")
atividade_opcoes = {
    "Sedentário (1.2)": 1.2,
    "Leve (1.375) - 1 a 3x/sem": 1.375,
    "Moderado (1.55) - 3 a 5x/sem": 1.55,
    "Alto (1.725) - 6 a 7x/sem": 1.725,
    "Atleta (1.9) - 2x por dia": 1.9
}
ativ_selecao = st.sidebar.selectbox("Fator de Movimento:", list(atividade_opcoes.keys()), index=1)
fator_ativ = atividade_opcoes[ativ_selecao]

# --- CÁLCULO MIFFLIN-ST JEOR ---
# Fórmula: (10 x peso) + (6.25 x altura) - (5 x idade) + 5 (homem) ou -161 (mulher)
tmb = (10 * peso_calc) + (6.25 * altura_cm) - (5 * idade)
if genero == "Masculino": tmb += 5
else: tmb -= 161

get_total = tmb * fator_ativ

st.sidebar.markdown("---")
st.sidebar.subheader("🎯 Objetivo")
objetivo = st.sidebar.selectbox("Fase da Dieta:", 
                                ["Perder Peso (Agressivo)", "Perder Peso (Moderado)", "Manutenção", "Ganhar Massa"])

if objetivo == "Perder Peso (Agressivo)":
    meta_calorica_calc = get_total - 750
elif objetivo == "Perder Peso (Moderado)":
    meta_calorica_calc = get_total - 500
elif objetivo == "Ganhar Massa":
    meta_calorica_calc = get_total + 300
else:
    meta_calorica_calc = get_total

# Arredonda
meta_calorica_calc = int(meta_calorica_calc)

# Distribuição de Macros Sugerida (Pode ajustar manualmente depois)
# Padrão Nutri: 30% Prot / 40% Carb / 30% Fat (Aproximado)
sug_prot = int((meta_calorica_calc * 0.30) / 4)
sug_carb = int((meta_calorica_calc * 0.40) / 4)
sug_gord = int((meta_calorica_calc * 0.30) / 9)

st.sidebar.markdown(f"""
<div style="background-color: #e8f5e9; padding: 10px; border-radius: 5px; color: black;">
    <b>📊 Resultados da Ciência:</b><br>
    • TMB (Basal): {int(tmb)} kcal<br>
    • Gasto Total (GET): {int(get_total)} kcal<br>
    • <b>Sua Meta: {meta_calorica_calc} kcal</b>
    <br><small>Ref: Fórmula Mifflin-St Jeor</small>
</div>
""", unsafe_allow_html=True)

st.sidebar.divider()
st.sidebar.subheader("🍽️ Ajuste Fino das Metas")
# Permite override manual, mas começa com o calculado
META_KCAL = st.sidebar.number_input("Meta Kcal:", value=meta_calorica_calc, step=50)
META_PROTEINA = st.sidebar.number_input("Meta Proteína (g):", value=sug_prot, step=5)
META_CARBO = st.sidebar.number_input("Meta Carbo (g):", value=sug_carb, step=5)
META_GORDURA = st.sidebar.number_input("Meta Gordura (g):", value=sug_gord, step=5)

# Config Peso Meta
st.sidebar.divider()
META_PESO = st.sidebar.number_input("Peso Alvo (kg):", value=120.0, step=0.5)
PERDA_SEMANAL_KG = st.sidebar.slider("Ritmo (kg/sem):", 0.1, 2.0, 0.8, 0.1)
DATA_INICIO_REGIME = st.sidebar.date_input("Início Regime:", value=pd.to_datetime("2025-12-30").date())

# --- DADOS DO APP ---
def get_now_br():
    return datetime.now(pytz.timezone('America/Sao_Paulo'))

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

# --- INDICADOR GLÚTEN ---
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

# --- HELPER GRÁFICOS ---
def create_macro_chart(df, date_col, val_col, meta_val, title, color):
    fig = go.Figure()
    fig.add_trace(go.Bar(x=df[date_col], y=df[val_col], name='Realizado', marker_color=color))
    fig.add_trace(go.Scatter(x=df[date_col], y=[meta_val]*len(df), mode='lines', name='Meta', line=dict(color='gray', width=2, dash='dash')))
    fig.update_layout(title=dict(text=title, font=dict(size=14)), height=250, margin=dict(l=10, r=10, t=40, b=20), showlegend=False)
    return fig

# --- INTERFACE ---
c1, c2 = st.columns([3, 1])
c1.markdown("# 🦁 Leo's Performance")
c2.markdown(f"### {hoje.strftime('%d/%m')}")

if tem_gluten:
    st.error(f"⚠️ **GLÚTEN DETECTADO:** {', '.join(itens_gluten)}")
else:
    st.success("✅ **Dieta Limpa (Glúten-Free)**")

st.markdown("---")

# KPI
k_act = df_hoje['kcal'].sum() if not df_hoje.empty else 0
p_act = df_hoje['proteina'].sum() if not df_hoje.empty else 0
c_act = df_hoje['carbo'].sum() if not df_hoje.empty else 0
g_act = df_hoje['gordura'].sum() if not df_hoje.empty else 0

cols = st.columns(4)
def metric_card(col, label, actual, target, suffix=""):
    delta = actual - target
    color = "inverse" if (label in ["🔥 Calorias", "🥑 Gordura"] and delta > 0) else "normal"
    col.metric(label, f"{int(actual)}{suffix}", f"Meta: {target}{suffix}", delta_color="off")
    col.progress(min(actual / target, 1.0) if target > 0 else 0)

metric_card(cols[0], "🔥 Calorias", k_act, META_KCAL)
metric_card(cols[1], "🥩 Proteína", p_act, META_PROTEINA, "g")
metric_card(cols[2], "🍞 Carbo", c_act, META_CARBO, "g")
metric_card(cols[3], "🥑 Gordura", g_act, META_GORDURA, "g")

st.markdown("---")

# PRINCIPAL
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

# MACROS
st.subheader("🔍 Controle Semanal de Macros")
if not df_hist.empty:
    m1, m2, m3 = st.columns(3)
    with m1: st.plotly_chart(create_macro_chart(df_hist, 'data', 'tprot', META_PROTEINA, "🥩 Proteína", "#3366CC"), use_container_width=True)
    with m2: st.plotly_chart(create_macro_chart(df_hist, 'data', 'tcarb', META_CARBO, "🍞 Carbo", "#FF9900"), use_container_width=True)
    with m3: st.plotly_chart(create_macro_chart(df_hist, 'data', 'tgord', META_GORDURA, "🥑 Gordura", "#DC3912"), use_container_width=True)

st.markdown("---")

# PESO
g3, g4 = st.columns([2, 1])
with g3:
    st.subheader("⚖️ Rumo ao Peso Ideal")
    if not df_peso.empty and len(df_peso) > 1:
        df_peso['data'] = pd.to_datetime(df_peso['data'])
        
        df_peso['diff_dias'] = abs(df_peso['data'].dt.date - DATA_INICIO_REGIME)
        idx_inicio = df_peso['diff_dias'].idxmin()
        peso_start = df_peso.loc[idx_inicio, 'peso_kg']
        
        ultimo_dia_grafico = max(df_peso['data'].max().date(), hoje) + timedelta(days=45)
        dias_projecao = (ultimo_dia_grafico - DATA_INICIO_REGIME).days
        
        if dias_projecao > 0:
            dates_proj = [DATA_INICIO_REGIME + timedelta(days=i) for i in range(dias_projecao + 1)]
            vals_proj = [max(META_PESO, peso_start - (i * (PERDA_SEMANAL_KG/7))) for i in range(dias_projecao + 1)]
            
            fig_p = go.Figure()
            fig_p.add_trace(go.Scatter(x=dates_proj, y=vals_proj, name=f'Meta (-{PERDA_SEMANAL_KG}kg/sem)', mode='lines', line=dict(color='gray', width=2, dash='dot')))
            fig_p.add_trace(go.Scatter(x=df_peso['data'], y=df_peso['peso_kg'], name='Peso Real', mode='lines+markers', line=dict(color='blue', width=4)))
            fig_p.update_layout(height=350, margin=dict(l=20, r=20, t=20, b=20), showlegend=True)
            st.plotly_chart(fig_p, use_container_width=True)
        else:
            st.warning("Data futura.")
    else:
        st.warning("Registre peso.")

with g4:
    st.subheader("🍽️ Hoje")
    if not df_hoje.empty:
        for i, row in df_hoje.iterrows():
            st.markdown(f"**{row['alimento']}**")
            c1, c2, c3 = st.columns(3)
            c1.caption(f"🔥 {int(row['kcal'])}")
            c2.caption(f"🥩 {int(row['proteina'])}g")
            g_txt = str(row['gluten']).lower()
            if ('contém' in g_txt or 'sim' in g_txt) and 'não' not in g_txt:
                c3.error("Glúten!")
            st.divider()
    else:
        st.write("Nada registrado.")
