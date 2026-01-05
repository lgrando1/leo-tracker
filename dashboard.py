import streamlit as st
import pandas as pd
import psycopg2
from datetime import datetime, timedelta
import pytz
import plotly.graph_objects as go

# 1. CONFIGURAÇÃO VISUAL
st.set_page_config(page_title="Leo's Nutrition Dash", page_icon="🦁", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
    <style>
    #MainMenu {visibility: hidden;} footer {visibility: hidden;} header {visibility: hidden;}
    div[data-testid="stMetric"] { background-color: #f0f2f6; padding: 10px; border-radius: 10px; border: 1px solid #e0e0e0; }
    @media (prefers-color-scheme: dark) { div[data-testid="stMetric"] { background-color: #262730; border: 1px solid #464b5c; } }
    </style>
    """, unsafe_allow_html=True)

# --- CONEXÃO COM TRATAMENTO DE ERRO DE TRANSAÇÃO ---
@st.cache_resource(ttl=300)
def get_connection():
    return psycopg2.connect(st.secrets["DATABASE_URL"])

def run_query(query, params=None, is_select=True):
    conn = None
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute("SET timezone TO 'America/Sao_Paulo';")
            if is_select:
                return pd.read_sql(query, conn, params=params)
            else:
                cur.execute(query, params)
                conn.commit()
                return True
    except Exception as e:
        if conn: conn.rollback() 
        st.error(f"Erro DB: {e}")
        return pd.DataFrame() if is_select else False

# --- CONTROLE DE ACESSO VIA URL ---
token_url = st.query_params.get("token")
token_esperado = st.secrets.get("DASH_ACCESS_TOKEN")

if token_url != token_esperado:
    st.error("🔒 Acesso Negado. Token inválido ou ausente.")
    st.stop() 

# --- INICIALIZAÇÃO DA TABELA DE PERFIL ---
run_query("""
    CREATE TABLE IF NOT EXISTS public.perfil (
        id INTEGER PRIMARY KEY, genero TEXT, idade INTEGER, altura_cm INTEGER, 
        atividade TEXT, ritmo_semanal REAL, meta_kcal INTEGER, 
        meta_proteina INTEGER, meta_carbo INTEGER, meta_gordura INTEGER, meta_peso_alvo REAL
    );
""", is_select=False)

# --- BUSCA DE DADOS ---
df_perfil = run_query("SELECT * FROM public.perfil WHERE id = 1")
df_peso_last = run_query("SELECT peso_kg FROM public.peso ORDER BY data DESC, id DESC LIMIT 1")

if not df_perfil.empty:
    p = df_perfil.iloc[0]
else:
    p = {'genero': 'Masculino', 'idade': 41, 'altura_cm': 185, 'atividade': 'Sedentário (1.2)', 
         'ritmo_semanal': 0.8, 'meta_kcal': 1650, 'meta_proteina': 130, 'meta_carbo': 150, 'meta_gordura': 59, 'meta_peso_alvo': 120.0}

PESO_ATUAL = float(df_peso_last.iloc[0]['peso_kg']) if not df_peso_last.empty else 141.9

# --- 2. BARRA LATERAL (CÁLCULO + PERSISTÊNCIA) ---
st.sidebar.header("🧮 Perfil Biométrico")

gen = st.sidebar.radio("Gênero:", ["Masculino", "Feminino"], index=0 if p['genero'] == "Masculino" else 1)
idade = st.sidebar.number_input("Idade:", value=int(p['idade']))
alt = st.sidebar.number_input("Altura (cm):", value=int(p['altura_cm']))

ativ_ops = {"Sedentário (1.2)": 1.2, "Leve (1.375)": 1.375, "Moderado (1.55)": 1.55}
ativ_sel = st.sidebar.selectbox("Atividade:", list(ativ_ops.keys()), index=list(ativ_ops.keys()).index(p['atividade']))

tmb = (10 * PESO_ATUAL) + (6.25 * alt) - (5 * idade) + (5 if gen == "Masculino" else -161)
get_total = tmb * ativ_ops[ativ_sel]
st.sidebar.info(f"🧬 **Gasto Total (GET): {int(get_total)} kcal**")

with st.sidebar.form("form_persist"):
    st.write("### Ajuste Final de Metas")
    mkcal = st.number_input("Meta Kcal:", value=int(p['meta_kcal']))
    mprot = st.number_input("Prot (g):", value=int(p['meta_proteina']))
    mcarb = st.number_input("Carb (g):", value=int(p['meta_carbo']))
    mgord = st.number_input("Gord (g):", value=int(p['meta_gordura']))
    palvo = st.number_input("Peso Alvo (kg):", value=float(p['meta_peso_alvo']))
    ritmo = st.slider("Ritmo (kg/sem):", 0.1, 2.0, float(p['ritmo_semanal']))
    
    if st.form_submit_button("💾 SALVAR CONFIGURAÇÕES"):
        run_query("""
            INSERT INTO public.perfil (id, genero, idade, altura_cm, atividade, ritmo_semanal, meta_kcal, meta_proteina, meta_carbo, meta_gordura, meta_peso_alvo)
            VALUES (1, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET genero=EXCLUDED.genero, idade=EXCLUDED.idade, altura_cm=EXCLUDED.altura_cm, atividade=EXCLUDED.atividade, ritmo_semanal=EXCLUDED.ritmo_semanal, meta_kcal=EXCLUDED.meta_kcal, meta_proteina=EXCLUDED.meta_proteina, meta_carbo=EXCLUDED.meta_carbo, meta_gordura=EXCLUDED.meta_gordura, meta_peso_alvo=EXCLUDED.meta_peso_alvo;
        """, (gen, idade, alt, ativ_sel, ritmo, mkcal, mprot, mcarb, mgord, palvo), is_select=False)
        st.rerun()

# --- 3. INTERFACE PRINCIPAL ---
hoje = datetime.now(pytz.timezone('America/Sao_Paulo')).date()
DATA_INICIO_DIETA = pd.to_datetime("2025-12-30").date()

df_hoje = run_query("SELECT * FROM public.consumo WHERE data = %s", (hoje,))
df_hist = run_query("SELECT data, SUM(kcal) as tkcal, SUM(proteina) as tprot, SUM(carbo) as tcarb, SUM(gordura) as tgord FROM public.consumo WHERE data >= %s GROUP BY data ORDER BY data ASC", (hoje - timedelta(days=30),))
df_peso_hist = run_query("SELECT * FROM public.peso ORDER BY data ASC")

st.markdown(f"# 🦁 Leo's Performance | {hoje.strftime('%d/%m')}")

# KPIs
k_act, p_act, c_act, g_act = (df_hoje['kcal'].sum(), df_hoje['proteina'].sum(), df_hoje['carbo'].sum(), df_hoje['gordura'].sum()) if not df_hoje.empty else (0,0,0,0)
c1, c2, c3, c4 = st.columns(4)
c1.metric("🔥 Calorias", f"{int(k_act)}", f"Meta: {mkcal}")
c2.metric("🥩 Proteína", f"{int(p_act)}g", f"Meta: {mprot}g")
c3.metric("🍞 Carbo", f"{int(c_act)}g", f"Meta: {mcarb}g")
c4.metric("🥑 Gordura", f"{int(g_act)}g", f"Meta: {mgord}g")

st.divider()

# --- BLOCO DE COMPARATIVO DINÂMICO ---
st.subheader("📊 Análise de Metas vs. Recomendação Científica")

# Recomendações calculadas dinamicamente com base no peso atual
rec_prot = round(PESO_ATUAL * 1.0) 
rec_gord = round(PESO_ATUAL * 0.4) 
rec_kcal = round(get_total - 750)   

cr1, cr2, cr3 = st.columns(3)
with cr1:
    st.metric("Proteína Ideal", f"{rec_prot}g", f"{mprot - rec_prot}g vs sua meta")
    st.caption("Cálculo: 1g/kg de peso total")
with cr2:
    st.metric("Calorias Sugeridas", f"{rec_kcal} kcal", f"{mkcal - rec_kcal} kcal vs sua meta")
    st.caption(f"Baseado no seu GET de {int(get_total)} kcal")
with cr3:
    st.metric("Gordura Ideal", f"{rec_gord}g", f"{mgord - rec_gord}g vs sua meta")
    st.caption("Cálculo: 0.4g/kg de peso total")

st.divider()

# Gráficos de Macros Semanais
st.subheader("🔍 Controle Semanal de Macros")
if not df_hist.empty:
    m1, m2, m3 = st.columns(3)
    def make_small(df, col, meta, title, color):
        f = go.Figure()
        f.add_trace(go.Bar(x=df['data'], y=df[col], marker_color=color))
        f.add_trace(go.Scatter(x=df['data'], y=[meta]*len(df), mode='lines', line=dict(color='gray', dash='dash')))
        f.update_layout(title=title, height=220, margin=dict(l=5,r=5,t=30,b=5), showlegend=False)
        return f
    m1.plotly_chart(make_small(df_hist, 'tprot', mprot, "Proteína (g)", "#3366CC"), use_container_width=True)
    m2.plotly_chart(make_small(df_hist, 'tcarb', mcarb, "Carbo (g)", "#FF9900"), use_container_width=True)
    m3.plotly_chart(make_small(df_hist, 'tgord', mgord, "Gordura (g)", "#DC3912"), use_container_width=True)

st.divider()

# Gráfico de Peso (Início fixo em 30/12 com 141.9 kg)
st.subheader("⚖️ Rumo ao Peso Ideal (Início: 30/12)")
if not df_peso_hist.empty:
    df_p = df_peso_hist.copy()
    df_p['data'] = pd.to_datetime(df_p['data'])
    peso_inicial_regime = 144.9 # Fixado em seus dados iniciais
    
    ultimo_dia_proj = hoje + timedelta(days=45)
    dias_total = (ultimo_dia_proj - DATA_INICIO_DIETA).days
    dates_meta = [DATA_INICIO_DIETA + timedelta(days=i) for i in range(dias_total + 1)]
    vals_meta = [max(palvo, peso_inicial_regime - (i * (ritmo/7))) for i in range(dias_total + 1)]
    
    fig_p = go.Figure()
    fig_p.add_trace(go.Scatter(x=dates_meta, y=vals_meta, name='Plano Saudável', mode='lines', line=dict(color='gray', dash='dot')))
    fig_p.add_trace(go.Scatter(x=df_p['data'], y=df_p['peso_kg'], name='Seu Progresso', mode='lines+markers', line=dict(color='blue', width=4)))
    st.plotly_chart(fig_p, use_container_width=True)
