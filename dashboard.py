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

# --- CONEXÃO COM TRATAMENTO DE ERRO ---
@st.cache_resource(ttl=300)
def get_connection():
    return psycopg2.connect(st.secrets["DATABASE_URL"])

def run_query(query, params=None, is_select=True):
    conn = None
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
        if conn: conn.rollback()
        st.error(f"Erro DB: {e}")
        return pd.DataFrame() if is_select else False

# --- TRAVA DE SEGURANÇA ---
if st.query_params.get("token") != st.secrets.get("DASH_ACCESS_TOKEN"):
    st.error("🔒 Acesso Negado."); st.stop()

# --- BUSCA DE DADOS ---
df_perfil = run_query("SELECT * FROM public.perfil WHERE id = 1")
df_peso_last = run_query("SELECT peso_kg FROM public.peso ORDER BY data DESC LIMIT 1")

# Seus dados iniciais conforme as imagens enviadas
if not df_perfil.empty:
    p = df_perfil.iloc[0]
else:
    p = {'genero': 'Masculino', 'idade': 41, 'altura_cm': 185, 'atividade': 'Sedentário (1.2)', 
         'objetivo': 'Perder Peso (Moderado)', 'ritmo_semanal': 0.8, 'meta_kcal': 1650, 
         'meta_proteina': 130, 'meta_carbo': 150, 'meta_gordura': 59, 'meta_peso_alvo': 120.0}

PESO_ATUAL = float(df_peso_last.iloc[0]['peso_kg']) if not df_peso_last.empty else 141.9

# --- 2. BARRA LATERAL (CÁLCULO DINÂMICO) ---
st.sidebar.header("🧮 Perfil Biométrico")
gen = st.sidebar.radio("Gênero:", ["Masculino", "Feminino"], index=0 if p['genero'] == "Masculino" else 1)
idade = st.sidebar.number_input("Idade:", value=int(p['idade']))
alt = st.sidebar.number_input("Altura (cm):", value=int(p['altura_cm']))

ativ_ops = {"Sedentário (1.2)": 1.2, "Leve (1.375)": 1.375, "Moderado (1.55)": 1.55}
ativ_sel = st.sidebar.selectbox("Atividade:", list(ativ_ops.keys()), index=list(ativ_ops.keys()).index(p['atividade']) if p['atividade'] in ativ_ops else 0)

# GET Científico Instantâneo
tmb = (10 * PESO_ATUAL) + (6.25 * alt) - (5 * idade) + (5 if gen == "Masculino" else -161)
get_total = tmb * ativ_ops[ativ_sel]
st.sidebar.info(f"🧬 **Gasto Total (GET): {int(get_total)} kcal**")

with st.sidebar.form("perfil_persist"):
    obj_lista = ["Perder Peso (Agressivo)", "Perder Peso (Moderado)", "Manutenção", "Ganhar Massa"]
    obj_sel = st.selectbox("Fase da Dieta:", obj_lista, index=obj_lista.index(p['objetivo']) if p['objetivo'] in obj_lista else 1)
    
    mkcal = st.number_input("Meta Kcal:", value=int(p['meta_kcal']))
    mprot = st.number_input("Prot (g):", value=int(p['meta_proteina']))
    mcarb = st.number_input("Carb (g):", value=int(p.get('meta_carbo', 150)))
    mgord = st.number_input("Gord (g):", value=int(p.get('meta_gordura', 59)))
    palvo = st.number_input("Peso Alvo (kg):", value=float(p['meta_peso_alvo']))
    ritmo = st.slider("Ritmo (kg/sem):", 0.1, 2.0, float(p['ritmo_semanal']))
    
    if st.form_submit_button("💾 SALVAR CONFIGURAÇÕES"):
        # Salvando especificamente na coluna 'objetivo'
        run_query("""
            INSERT INTO public.perfil (id, genero, idade, altura_cm, atividade, objetivo, ritmo_semanal, meta_kcal, meta_proteina, meta_carbo, meta_gordura, meta_peso_alvo)
            VALUES (1, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET 
            genero=EXCLUDED.genero, idade=EXCLUDED.idade, altura_cm=EXCLUDED.altura_cm, atividade=EXCLUDED.atividade, 
            objetivo=EXCLUDED.objetivo, ritmo_semanal=EXCLUDED.ritmo_semanal, meta_kcal=EXCLUDED.meta_kcal, 
            meta_proteina=EXCLUDED.meta_proteina, meta_carbo=EXCLUDED.meta_carbo, meta_gordura=EXCLUDED.meta_gordura, 
            meta_peso_alvo=EXCLUDED.meta_peso_alvo;
        """, (gen, idade, alt, ativ_sel, obj_sel, ritmo, mkcal, mprot, mcarb, mgord, palvo), is_select=False)
        st.rerun()

# --- INTERFACE PRINCIPAL ---
hoje = datetime.now(pytz.timezone('America/Sao_Paulo')).date()
DATA_INICIO_DIETA = pd.to_datetime("2025-12-30").date()

df_hoje = run_query("SELECT * FROM public.consumo WHERE data = %s", (hoje,))
df_hist = run_query("SELECT data, SUM(kcal) as tkcal, SUM(proteina) as tprot FROM public.consumo WHERE data >= %s GROUP BY data ORDER BY data ASC", (hoje - timedelta(days=30),))
df_peso = run_query("SELECT * FROM public.peso ORDER BY data ASC")

st.markdown(f"# 🦁 Leo's Performance | {hoje.strftime('%d/%m')}")

# KPIs
k_act, p_act = (df_hoje['kcal'].sum(), df_hoje['proteina'].sum()) if not df_hoje.empty else (0,0)
c1, c2, c3 = st.columns(3)
c1.metric("🔥 Calorias", f"{int(k_act)}", f"Meta: {mkcal}")
c2.metric("🥩 Proteína", f"{int(p_act)}g", f"Meta: {mprot}g")
c3.metric("⚖️ Peso Atual", f"{PESO_ATUAL}kg")

st.divider()

# Gráfico de Peso fixado em 144,9kg no dia 30/12
st.subheader("⚖️ Rumo ao Peso Ideal (Início: 30/12)")
if not df_peso.empty:
    peso_start = 144.9 
    dias_proj = (hoje + timedelta(days=45) - DATA_INICIO_DIETA).days
    dates_meta = [DATA_INICIO_DIETA + timedelta(days=i) for i in range(dias_proj + 1)]
    vals_meta = [max(palvo, peso_start - (i * (ritmo/7))) for i in range(len(dates_meta))]
    
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=dates_meta, y=vals_meta, name='Plano', mode='lines', line=dict(color='gray', dash='dot')))
    fig.add_trace(go.Scatter(x=pd.to_datetime(df_peso['data']), y=df_peso['peso_kg'], name='Real', mode='lines+markers', line=dict(color='blue', width=4)))
    st.plotly_chart(fig, use_container_width=True)
