import streamlit as st
import pandas as pd
import psycopg2
from datetime import datetime, timedelta
import pytz
import plotly.express as px
import plotly.graph_objects as go

# 1. CONFIGURAÇÃO VISUAL
st.set_page_config(page_title="Leo's Nutrition Dash", page_icon="🦁", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
    <style>
    #MainMenu {visibility: hidden;} footer {visibility: hidden;} header {visibility: hidden;}
    .block-container {padding-top: 1rem; padding-bottom: 2rem;}
    div[data-testid="stMetric"] {background-color: #f0f2f6; padding: 10px; border-radius: 10px; border: 1px solid #e0e0e0;}
    @media (prefers-color-scheme: dark) { div[data-testid="stMetric"] {background-color: #262730; border: 1px solid #464b5c;} }
    </style>
    """, unsafe_allow_html=True)

# --- CONEXÃO E DADOS INICIAIS ---
@st.cache_resource(ttl=300)
def get_connection():
    return psycopg2.connect(st.secrets["DATABASE_URL"])

def run_query(query, params=None, is_select=True):
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute("SET timezone TO 'America/Sao_Paulo';")
            if is_select: return pd.read_sql(query, conn, params=params)
            else:
                cur.execute(query, params)
                conn.commit()
                return True
    except Exception as e:
        st.error(f"Erro DB: {e}"); return pd.DataFrame()

# --- CONTROLE DE ACESSO VIA URL ---
token_url = st.query_params.get("token")
if token_url != st.secrets.get("DASH_ACCESS_TOKEN"):
    st.error("🔒 Acesso Negado."); st.stop()

# --- INICIALIZAÇÃO DA TABELA DE PERFIL ---
run_query("""
    CREATE TABLE IF NOT EXISTS public.perfil (
        id INTEGER PRIMARY KEY, genero TEXT, idade INTEGER, altura_cm INTEGER, 
        ritmo_semanal REAL, meta_kcal INTEGER, meta_proteina INTEGER, meta_peso_alvo REAL
    );
""", is_select=False)

# --- BUSCA DE DADOS SALVOS ---
df_perfil = run_query("SELECT * FROM public.perfil WHERE id = 1")
df_peso_last = run_query("SELECT peso_kg FROM public.peso ORDER BY data DESC LIMIT 1")

# Se não houver perfil salvo, usa seus dados iniciais
if not df_perfil.empty:
    p = df_perfil.iloc[0]
else:
    p = {'genero': 'Masculino', 'idade': 41, 'altura_cm': 185, 'ritmo_semanal': 0.8, 'meta_kcal': 1650, 'meta_proteina': 110, 'meta_peso_alvo': 120.0}

PESO_ATUAL = float(df_peso_last.iloc[0]['peso_kg']) if not df_peso_last.empty else 141.9

# --- 2. BARRA LATERAL (COM SALVAMENTO) ---
st.sidebar.header("🧮 Perfil Biométrico")
with st.sidebar.form("perfil_form"):
    st.write(f"**Peso Atual:** {PESO_ATUAL} kg")
    gen = st.radio("Gênero:", ["Masculino", "Feminino"], index=0 if p['genero'] == "Masculino" else 1)
    id_val = st.number_input("Idade:", value=int(p['idade']))
    alt_val = st.number_input("Altura (cm):", value=int(p['altura_cm']))
    rit_val = st.slider("Ritmo (kg/sem):", 0.1, 2.0, float(p['ritmo_semanal']))
    
    st.divider()
    mkcal = st.number_input("Meta Kcal:", value=int(p['meta_kcal']))
    mprot = st.number_input("Meta Proteína (g):", value=int(p['meta_proteina']))
    palvo = st.number_input("Peso Alvo (kg):", value=float(p['meta_peso_alvo']))
    
    if st.form_submit_button("💾 Salvar Dados no SQL"):
        run_query("""
            INSERT INTO public.perfil (id, genero, idade, altura_cm, ritmo_semanal, meta_kcal, meta_proteina, meta_peso_alvo)
            VALUES (1, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET 
            genero=EXCLUDED.genero, idade=EXCLUDED.idade, altura_cm=EXCLUDED.altura_cm, 
            ritmo_semanal=EXCLUDED.ritmo_semanal, meta_kcal=EXCLUDED.meta_kcal, 
            meta_proteina=EXCLUDED.meta_proteina, meta_peso_alvo=EXCLUDED.meta_peso_alvo;
        """, (gen, id_val, alt_val, rit_val, mkcal, mprot, palvo), is_select=False)
        st.rerun()

# --- PROCESSAMENTO ---
hoje = datetime.now(pytz.timezone('America/Sao_Paulo')).date()
DATA_INICIO_REGIME = pd.to_datetime("2025-12-30").date()

df_hoje = run_query("SELECT * FROM public.consumo WHERE data = %s", (hoje,))
df_hist = run_query("SELECT data, SUM(kcal) as tkcal, SUM(proteina) as tprot, SUM(carbo) as tcarb, SUM(gordura) as tgord FROM public.consumo WHERE data >= %s GROUP BY data ORDER BY data ASC", (hoje - timedelta(days=30),))
df_peso_hist = run_query("SELECT * FROM public.peso ORDER BY data ASC")

# --- INTERFACE ---
st.markdown(f"# 🦁 Leo's Performance | {hoje.strftime('%d/%m')}")

# KPIs
k_act, p_act = (df_hoje['kcal'].sum(), df_hoje['proteina'].sum()) if not df_hoje.empty else (0,0)
cols = st.columns(4)
cols[0].metric("🔥 Calorias", f"{int(k_act)}", f"Meta: {mkcal}")
cols[1].metric("🥩 Proteína", f"{int(p_act)}g", f"Meta: {mprot}g")
cols[2].metric("⚖️ Peso Atual", f"{PESO_ATUAL}kg")
cols[3].metric("📉 Ritmo", f"{rit_val}kg/sem")

st.divider()

# Gráfico de Peso
st.subheader("⚖️ Evolução do Peso (Início em 30/12)")
if not df_peso_hist.empty:
    df_peso_hist['data'] = pd.to_datetime(df_peso_hist['data'])
    peso_start_plano = 141.9
    
    # Projeção
    ultimo_dia = hoje + timedelta(days=45)
    dias_proj = (ultimo_dia - DATA_INICIO_REGIME).days
    dates_p = [DATA_INICIO_REGIME + timedelta(days=i) for i in range(dias_proj + 1)]
    vals_p = [max(palvo, peso_start_plano - (i * (rit_val/7))) for i in range(dias_proj + 1)]
    
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=dates_p, y=vals_p, name='Plano Saudável', mode='lines', line=dict(color='gray', dash='dot')))
    fig.add_trace(go.Scatter(x=df_peso_hist['data'], y=df_peso_hist['peso_kg'], name='Peso Real', mode='lines+markers', line=dict(color='#1f77b4', width=4)))
    fig.update_layout(height=400, margin=dict(l=20, r=20, t=20, b=20))
    st.plotly_chart(fig, use_container_width=True)
