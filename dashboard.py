import streamlit as st
import pandas as pd
import psycopg2
from datetime import datetime, timedelta
import pytz
import plotly.graph_objects as go
import math

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
            if is_select: 
                df = pd.read_sql(query, conn, params=params)
                # Padronizar datas automaticamente para evitar erros de plotagem
                for col in ['data', 'log_date']:
                    if col in df.columns:
                        df[col] = pd.to_datetime(df[col])
                return df
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
# Perfil e Peso
df_perfil = run_query("SELECT * FROM public.perfil WHERE id = 1")
df_peso_last = run_query("SELECT peso_kg FROM public.peso ORDER BY data DESC, id DESC LIMIT 1")
# NOVAS Medidas
df_medidas = run_query("SELECT * FROM public.body_measurements ORDER BY log_date ASC")

if not df_perfil.empty:
    p = df_perfil.iloc[0]
else:
    # Fallback
    p = {'genero': 'Masculino', 'idade': 41, 'altura_cm': 178, 'atividade': 'Sedentário (1.2)', 
         'objetivo': 'Perder Peso (Moderado)', 'ritmo_semanal': 0.8, 'meta_kcal': 1650, 
         'meta_proteina': 130, 'meta_carbo': 150, 'meta_gordura': 59, 'meta_peso_alvo': 120.0}

PESO_ATUAL = float(df_peso_last.iloc[0]['peso_kg']) if not df_peso_last.empty else 141.9
ALTURA_ATUAL = int(p.get('altura_cm', 178))

# --- 2. BARRA LATERAL INTELIGENTE ---
st.sidebar.header("🧮 Perfil Biométrico")

# Inputs
gen = st.sidebar.radio("Gênero:", ["Masculino", "Feminino"], index=0 if p['genero'] == "Masculino" else 1)
idade = st.sidebar.number_input("Idade:", value=int(p['idade']))
alt = st.sidebar.number_input("Altura (cm):", value=ALTURA_ATUAL)
peso_ref = st.sidebar.number_input("Peso Atual (kg):", value=PESO_ATUAL)

ativ_ops = {"Sedentário (1.2)": 1.2, "Leve (1.375)": 1.375, "Moderado (1.55)": 1.55}
ativ_sel = st.sidebar.selectbox("Atividade:", list(ativ_ops.keys()), index=list(ativ_ops.keys()).index(p['atividade']) if p['atividade'] in ativ_ops else 0)

# Cálculos
tmb = (10 * peso_ref) + (6.25 * alt) - (5 * idade) + (5 if gen == "Masculino" else -161)
get_total = tmb * ativ_ops[ativ_sel]
deficit_padrao = 750 
kcal_sugerida = int(get_total - deficit_padrao)

sug_prot = int((kcal_sugerida * 0.30) / 4)
sug_carb = int((kcal_sugerida * 0.35) / 4)
sug_gord = int((kcal_sugerida * 0.35) / 9)

st.sidebar.markdown("---")
st.sidebar.info(f"""
🧬 **Sugestão Científica (Déficit):**
\n🔥 **Calorias:** {kcal_sugerida} kcal
\n🥩 **Proteína:** {sug_prot}g
\n🍞 **Carbo:** {sug_carb}g
\n🥑 **Gordura:** {sug_gord}g
\nBaseado no seu GET de {int(get_total)} kcal
""")

# Formulário de Ajuste
with st.sidebar.form("perfil_persist"):
    st.write("### 📝 Suas Metas Reais")
    
    obj_lista = ["Perder Peso (Agressivo)", "Perder Peso (Moderado)", "Manutenção", "Ganhar Massa"]
    obj_sel = st.selectbox("Objetivo:", obj_lista, index=obj_lista.index(p['objetivo']) if p['objetivo'] in obj_lista else 1)
    
    mkcal = st.number_input("Meta Kcal:", value=int(p['meta_kcal']))
    mprot = st.number_input("Prot (g):", value=int(p['meta_proteina']))
    mcarb = st.number_input("Carb (g):", value=int(p.get('meta_carbo', 150)))
    mgord = st.number_input("Gord (g):", value=int(p.get('meta_gordura', 59)))
    palvo = st.number_input("Peso Alvo (kg):", value=float(p['meta_peso_alvo']))
    ritmo = st.slider("Ritmo (kg/sem):", 0.1, 2.0, float(p['ritmo_semanal']))
    
    if st.form_submit_button("💾 SALVAR CONFIGURAÇÕES"):
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

# --- 3. DADOS PRINCIPAIS ---
hoje = datetime.now(pytz.timezone('America/Sao_Paulo')).date()
DATA_INICIO = pd.to_datetime("2025-12-30").date()

df_hoje = run_query("SELECT * FROM public.consumo WHERE data = %s", (hoje,))
df_hist = run_query("SELECT data, SUM(kcal) as tkcal, SUM(proteina) as tprot, SUM(carbo) as tcarb, SUM(gordura) as tgord FROM public.consumo WHERE data >= %s GROUP BY data ORDER BY data ASC", (hoje - timedelta(days=30),))
df_peso = run_query("SELECT * FROM public.peso ORDER BY data ASC")

st.markdown(f"# 🦁 Leo's Performance | {hoje.strftime('%d/%m')}")

# KPI: Macros Hoje (Original)
k_act, p_act, c_act, g_act = (df_hoje['kcal'].sum(), df_hoje['proteina'].sum(), df_hoje['carbo'].sum(), df_hoje['gordura'].sum()) if not df_hoje.empty else (0,0,0,0)
c1, c2, c3, c4 = st.columns(4)
c1.metric("🔥 Calorias", f"{int(k_act)}", f"Meta: {mkcal}")
c2.metric("🥩 Proteína", f"{int(p_act)}g", f"Meta: {mprot}g")
c3.metric("🍞 Carbo", f"{int(c_act)}g", f"Meta: {mcarb}g")
c4.metric("🥑 Gordura", f"{int(g_act)}g", f"Meta: {mgord}g")

st.divider()

# --- NOVO BLOCO: COMPOSIÇÃO CORPORAL ---
st.subheader("📏 Composição Corporal & Risco Metabólico")

cintura_atual = 0
gordura_atual = 0
if not df_medidas.empty:
    last_m = df_medidas.iloc[-1]
    cintura_atual = last_m['waist_cm']
    # Lógica de fallback para cálculo
    if last_m.get('body_fat_est') and last_m['body_fat_est'] > 0:
        gordura_atual = last_m['body_fat_est']
    else:
        try:
            gordura_atual = 495 / (1.0324 - 0.19077 * math.log10(last_m['waist_cm'] - last_m['neck_cm']) + 0.15456 * math.log10(ALTURA_ATUAL)) - 450
        except: gordura_atual = 0

col_corp1, col_corp2, col_corp3 = st.columns(3)
col_corp1.metric("⚖️ Peso Atual", f"{PESO_ATUAL} kg", delta=f"{PESO_ATUAL - float(p['meta_peso_alvo']):.1f} kg para a meta", delta_color="inverse")
col_corp2.metric("📏 Cintura (Umbigo)", f"{cintura_atual} cm", "Meta: < 94 cm (Saúde)", delta_color="inverse")
col_corp3.metric("📊 Gordura Estimada", f"{gordura_atual:.1f}%", "Navy Method", delta_color="inverse")

# Gráfico Novo: Peso vs Cintura
if not df_medidas.empty:
    fig_body = go.Figure()
    # Eixo Y1: Peso
    fig_body.add_trace(go.Scatter(x=df_peso['data'], y=df_peso['peso_kg'], name="Peso (kg)", line=dict(color='blue', width=3)))
    # Eixo Y2: Cintura
    fig_body.add_trace(go.Scatter(x=df_medidas['log_date'], y=df_medidas['waist_cm'], name="Cintura (cm)", line=dict(color='red', dash='dot'), yaxis='y2'))
    
    fig_body.update_layout(
        title="Correlação: Peso vs Cintura",
        yaxis=dict(title="Peso (kg)"),
        yaxis2=dict(title="Cintura (cm)", overlaying='y', side='right'),
        height=350, margin=dict(l=10,r=10,t=40,b=10),
        legend=dict(orientation="h", y=1.1)
    )
    st.plotly_chart(fig_body, use_container_width=True)
else:
    st.info("Adicione suas medidas no Tracker para ver o gráfico de composição corporal.")

st.divider()

# --- GRÁFICOS DIETA (Originais) ---
g1, g2 = st.columns([2, 1])
with g1:
    st.subheader("📊 Calorias vs Meta (30 dias)")
    if not df_hist.empty:
        fig_k = go.Figure()
        fig_k.add_trace(go.Bar(x=df_hist['data'], y=df_hist['tkcal'], name='Real', marker_color='#4CAF50'))
        fig_k.add_trace(go.Scatter(x=df_hist['data'], y=[mkcal]*len(df_hist), mode='lines', name='Meta', line=dict(color='red', dash='dot')))
        fig_k.update_layout(height=320, margin=dict(l=10,r=10,t=10,b=10), legend=dict(orientation="h", y=1.1))
        st.plotly_chart(fig_k, use_container_width=True)
    else: st.info("Sem dados de consumo.")

with g2:
    st.subheader("🎯 Distribuição Hoje")
    if k_act > 0:
        fig_p = go.Figure(data=[go.Pie(labels=['P','C','G'], values=[p_act*4, c_act*4, g_act*9], hole=.5, marker=dict(colors=['#3366CC','#FF9900','#DC3912']))])
        fig_p.update_layout(height=320, margin=dict(l=10,r=10,t=10,b=10))
        st.plotly_chart(fig_p, use_container_width=True)
    else: st.info("Registre alimentos hoje.")

st.subheader("🔍 Controle Semanal de Macros")
if not df_hist.empty:
    m1, m2, m3 = st.columns(3)
    def make_chart(df, col, meta, title, color):
        f = go.Figure()
        f.add_trace(go.Bar(x=df['data'], y=df[col], marker_color=color))
        f.add_trace(go.Scatter(x=df['data'], y=[meta]*len(df), mode='lines', line=dict(color='gray', dash='dash')))
        f.update_layout(title=title, height=220, margin=dict(l=5,r=5,t=30,b=5), showlegend=False)
        return f
    m1.plotly_chart(make_chart(df_hist, 'tprot', mprot, "Proteína (g)", "#3366CC"), use_container_width=True)
    m2.plotly_chart(make_chart(df_hist, 'tcarb', mcarb, "Carbo (g)", "#FF9900"), use_container_width=True)
    m3.plotly_chart(make_chart(df_hist, 'tgord', mgord, "Gordura (g)", "#DC3912"), use_container_width=True)

st.divider()

# --- GRÁFICO FINAL (Restaurado) ---
st.subheader("⚖️ Rumo ao Peso Ideal (Início: 30/12)")
if not df_peso.empty:
    df_p = df_peso.copy()
    df_p['data'] = pd.to_datetime(df_p['data'])
    p_inicial = 144.9 # Fixo do seu histórico
    
    d_total = (hoje + timedelta(days=45) - DATA_INICIO).days
    dates_m = [DATA_INICIO + timedelta(days=i) for i in range(d_total + 1)]
    vals_m = [max(palvo, p_inicial - (i * (ritmo/7))) for i in range(len(dates_m))]
    
    fig_w = go.Figure()
    fig_w.add_trace(go.Scatter(x=dates_m, y=vals_m, name='Plano', mode='lines', line=dict(color='gray', dash='dot')))
    fig_w.add_trace(go.Scatter(x=df_p['data'], y=df_p['peso_kg'], name='Real', mode='lines+markers', line=dict(color='blue', width=4)))
    fig_w.update_layout(height=400, margin=dict(l=10,r=10,t=10,b=10))
    st.plotly_chart(fig_w, use_container_width=True)
