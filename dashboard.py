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
                for col in ['data', 'log_date']:
                    if col in df.columns: df[col] = pd.to_datetime(df[col])
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
df_perfil = run_query("SELECT * FROM public.perfil WHERE id = 1")
df_peso_last = run_query("SELECT peso_kg FROM public.peso ORDER BY data DESC, id DESC LIMIT 1")
df_medidas = run_query("SELECT * FROM public.body_measurements ORDER BY log_date ASC")

if not df_perfil.empty:
    p = df_perfil.iloc[0]
else:
    p = {'genero': 'Masculino', 'idade': 41, 'altura_cm': 178, 'atividade': 'Sedentário (1.2)', 
         'objetivo': 'Perder Peso (Moderado)', 'ritmo_semanal': 0.8, 'meta_kcal': 1650, 
         'meta_proteina': 130, 'meta_carbo': 150, 'meta_gordura': 59, 'meta_peso_alvo': 120.0}

PESO_ATUAL = float(df_peso_last.iloc[0]['peso_kg']) if not df_peso_last.empty else 141.9
ALTURA_ATUAL = int(p.get('altura_cm', 178))

# --- 2. BARRA LATERAL INTELIGENTE ---
st.sidebar.header("🧮 Perfil Biométrico")
gen = st.sidebar.radio("Gênero:", ["Masculino", "Feminino"], index=0 if p['genero'] == "Masculino" else 1)
idade = st.sidebar.number_input("Idade:", value=int(p['idade']))
alt = st.sidebar.number_input("Altura (cm):", value=ALTURA_ATUAL)
peso_ref = st.sidebar.number_input("Peso Atual (kg):", value=PESO_ATUAL)

ativ_ops = {"Sedentário (1.2)": 1.2, "Leve (1.375)": 1.375, "Moderado (1.55)": 1.55}
ativ_sel = st.sidebar.selectbox("Atividade:", list(ativ_ops.keys()), index=list(ativ_ops.keys()).index(p['atividade']) if p['atividade'] in ativ_ops else 0)

tmb = (10 * peso_ref) + (6.25 * alt) - (5 * idade) + (5 if gen == "Masculino" else -161)
get_total = tmb * ativ_ops[ativ_sel]
deficit_padrao = 750 
kcal_sugerida = int(get_total - deficit_padrao)

sug_prot = int((kcal_sugerida * 0.30) / 4)
sug_carb = int((kcal_sugerida * 0.35) / 4)
sug_gord = int((kcal_sugerida * 0.35) / 9)

st.sidebar.markdown("---")
st.sidebar.info(f"🧬 **Sugestão (Déficit):**\n🔥 {kcal_sugerida} kcal | 🥩 {sug_prot}g | 🍞 {sug_carb}g | 🥑 {sug_gord}g")

with st.sidebar.form("perfil_persist"):
    st.write("### 📝 Suas Metas")
    obj_lista = ["Perder Peso (Agressivo)", "Perder Peso (Moderado)", "Manutenção", "Ganhar Massa"]
    obj_sel = st.selectbox("Objetivo:", obj_lista, index=obj_lista.index(p['objetivo']) if p['objetivo'] in obj_lista else 1)
    mkcal = st.number_input("Meta Kcal:", value=int(p['meta_kcal']))
    mprot = st.number_input("Prot (g):", value=int(p['meta_proteina']))
    mcarb = st.number_input("Carb (g):", value=int(p.get('meta_carbo', 150)))
    mgord = st.number_input("Gord (g):", value=int(p.get('meta_gordura', 59)))
    palvo = st.number_input("Peso Alvo (kg):", value=float(p['meta_peso_alvo']))
    ritmo = st.slider("Ritmo (kg/sem):", 0.1, 2.0, float(p['ritmo_semanal']))
    if st.form_submit_button("💾 SALVAR"):
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

# KPI: Macros Hoje
k_act, p_act, c_act, g_act = (df_hoje['kcal'].sum(), df_hoje['proteina'].sum(), df_hoje['carbo'].sum(), df_hoje['gordura'].sum()) if not df_hoje.empty else (0,0,0,0)
c1, c2, c3, c4 = st.columns(4)
c1.metric("🔥 Calorias", f"{int(k_act)}", f"Meta: {mkcal}")
c2.metric("🥩 Proteína", f"{int(p_act)}g", f"Meta: {mprot}g")
c3.metric("🍞 Carbo", f"{int(c_act)}g", f"Meta: {mcarb}g")
c4.metric("🥑 Gordura", f"{int(g_act)}g", f"Meta: {mgord}g")

st.divider()

# --- GRÁFICO MESTRE UNIFICADO ---
st.subheader("📉 Evolução Corporal Unificada")

if not df_peso.empty:
    p_inicial = 144.9
    d_total = (hoje + timedelta(days=60) - DATA_INICIO).days
    dates_m = [DATA_INICIO + timedelta(days=i) for i in range(d_total + 1)]
    vals_m = [max(float(p['meta_peso_alvo']), p_inicial - (i * (float(p['ritmo_semanal'])/7))) for i in range(len(dates_m))]
    
    fig_combo = go.Figure()
    fig_combo.add_trace(go.Scatter(x=dates_m, y=vals_m, name="Meta Planejada", mode='lines', line=dict(color='gray', dash='dot', width=2)))
    fig_combo.add_trace(go.Scatter(x=df_peso['data'], y=df_peso['peso_kg'], name="Peso Real (kg)", mode='lines+markers', line=dict(color='#1f77b4', width=4)))
    
    if not df_medidas.empty:
        fig_combo.add_trace(go.Scatter(
            x=df_medidas['log_date'], y=df_medidas['waist_cm'], 
            name="Cintura (cm)", mode='lines+markers', 
            line=dict(color='#d62728', width=3), yaxis='y2'
        ))

    # Layout Blindado
    fig_combo.update_layout(
        title=dict(text="Correlação: Peso (Esq) vs Cintura (Dir) vs Meta"),
        xaxis=dict(title=dict(text="Data")),
        yaxis=dict(title=dict(text="Peso (kg)", font=dict(color="#1f77b4")), tickfont=dict(color="#1f77b4")),
        yaxis2=dict(title=dict(text="Cintura (cm)", font=dict(color="#d62728")), tickfont=dict(color="#d62728"), overlaying='y', side='right'),
        legend=dict(x=0.01, y=0.99, bgcolor='rgba(255,255,255,0.8)'),
        height=500, hovermode="x unified"
    )
    st.plotly_chart(fig_combo, use_container_width=True)

    c_m1, c_m2, c_m3 = st.columns(3)
    cintura_atual = df_medidas.iloc[-1]['waist_cm'] if not df_medidas.empty else 0
    gordura_atual = 0
    if cintura_atual > 0:
        neck_atual = df_medidas.iloc[-1]['neck_cm'] if 'neck_cm' in df_medidas.columns else 40
        try: gordura_atual = 495 / (1.0324 - 0.19077 * math.log10(cintura_atual - neck_atual) + 0.15456 * math.log10(ALTURA_ATUAL)) - 450
        except: pass
    
    c_m1.metric("⚖️ Peso Hoje", f"{PESO_ATUAL} kg", f"Meta: {p['meta_peso_alvo']} kg")
    c_m2.metric("📏 Cintura", f"{cintura_atual} cm", "Risco < 94cm", delta_color="inverse")
    c_m3.metric("📊 Gordura (Navy)", f"{gordura_atual:.1f}%", "Estimada", delta_color="inverse")

else:
    st.info("Adicione dados de peso para visualizar o gráfico unificado.")

st.divider()

# --- NOVO BLOCO: HISTÓRICO DE MACROS (SOLICITADO) ---
st.subheader("🗓️ Histórico de Macros (30 dias)")

if not df_hist.empty:
    m1, m2, m3 = st.columns(3)
    
    # Função auxiliar para criar gráficos consistentes
    def plot_macro(df, col_real, val_meta, nome, cor):
        fig = go.Figure()
        fig.add_trace(go.Bar(x=df['data'], y=df[col_real], name="Real", marker_color=cor))
        fig.add_trace(go.Scatter(x=df['data'], y=[val_meta]*len(df), name="Meta", mode='lines', line=dict(color='gray', dash='dot')))
        fig.update_layout(
            title=dict(text=nome),
            height=250, 
            margin=dict(l=10,r=10,t=40,b=10),
            showlegend=False
        )
        return fig

    with m1:
        st.plotly_chart(plot_macro(df_hist, 'tprot', mprot, "🥩 Proteína (Meta: {}g)".format(mprot), "#3366CC"), use_container_width=True)
    with m2:
        st.plotly_chart(plot_macro(df_hist, 'tcarb', mcarb, "🍞 Carbo (Meta: {}g)".format(mcarb), "#FF9900"), use_container_width=True)
    with m3:
        st.plotly_chart(plot_macro(df_hist, 'tgord', mgord, "🥑 Gordura (Meta: {}g)".format(mgord), "#DC3912"), use_container_width=True)

else:
    st.info("Ainda não há dados suficientes para gerar histórico de macros.")

st.divider()

# --- GRÁFICOS GERAIS (Calorias e Pizza) ---
st.subheader("🍽️ Visão Geral da Dieta")
g1, g2 = st.columns([2, 1])
with g1:
    if not df_hist.empty:
        fig_k = go.Figure()
        fig_k.add_trace(go.Bar(x=df_hist['data'], y=df_hist['tkcal'], name='Kcal', marker_color='#4CAF50'))
        fig_k.add_trace(go.Scatter(x=df_hist['data'], y=[mkcal]*len(df_hist), mode='lines', name='Meta', line=dict(color='red', dash='dot')))
        fig_k.update_layout(
            title=dict(text="Calorias vs Meta"),
            height=300, margin=dict(l=10,r=10,t=40,b=10)
        )
        st.plotly_chart(fig_k, use_container_width=True)
    else: st.info("Sem dados.")

with g2:
    if k_act > 0:
        fig_p = go.Figure(data=[go.Pie(labels=['Prot','Carb','Gord'], values=[p_act*4, c_act*4, g_act*9], hole=.5, marker=dict(colors=['#3366CC','#FF9900','#DC3912']))])
        fig_p.update_layout(
            title=dict(text="Distribuição Hoje"),
            height=300, margin=dict(l=10,r=10,t=40,b=10)
        )
        st.plotly_chart(fig_p, use_container_width=True)
    else: st.info("Registre hoje.")
