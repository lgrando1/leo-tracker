import streamlit as st
import pandas as pd
import psycopg2
from datetime import datetime, timedelta
import pytz
import plotly.graph_objects as go
from plotly.subplots import make_subplots
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

# --- CONEXÃO ---
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
                for col in ['data', 'log_date', 'measurement_time']:
                    if col in df.columns:
                        try: df[col] = pd.to_datetime(df[col])
                        except: pass 
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
# (Se estiver rodando local, comente a linha abaixo. Se for na nuvem, mantenha)
# if st.query_params.get("token") != st.secrets.get("DASH_ACCESS_TOKEN"): st.error("🔒 Acesso Negado."); st.stop()

# --- BUSCA DE DADOS ---
df_perfil = run_query("SELECT * FROM public.perfil WHERE id = 1")
df_peso_last = run_query("SELECT peso_kg FROM public.peso ORDER BY data DESC, id DESC LIMIT 1")
df_medidas = run_query("SELECT * FROM public.body_measurements ORDER BY log_date ASC")
df_bp = run_query("SELECT * FROM public.blood_pressure ORDER BY measurement_time ASC")

# Valores Padrão / Perfil
if not df_perfil.empty:
    p = df_perfil.iloc[0]
else:
    p = {'genero': 'Masculino', 'idade': 41, 'altura_cm': 178, 'atividade': 'Sedentário (1.2)', 
         'objetivo': 'Perder Peso (Moderado)', 'ritmo_semanal': 0.8, 'meta_kcal': 1650, 
         'meta_proteina': 130, 'meta_carbo': 150, 'meta_gordura': 59, 'meta_peso_alvo': 120.0}

PESO_ATUAL = float(df_peso_last.iloc[0]['peso_kg']) if not df_peso_last.empty else 141.9
ALTURA_ATUAL = int(p.get('altura_cm', 178))
META_AGUA = round((PESO_ATUAL * 35) / 1000, 1) # 35ml por kg

# --- SIDEBAR ---
st.sidebar.header("🧮 Perfil Biométrico")
st.sidebar.info(f"🧬 **Metas Diárias:**\n🔥 {p['meta_kcal']} kcal | 🥩 {p['meta_proteina']}g\n💧 {META_AGUA} Litros (Min)")
st.sidebar.markdown("---")
st.sidebar.caption("💡 *Dica: Se o peso travar, verifique a meta de água.*")

# --- DADOS TEMPORAIS ---
hoje = datetime.now(pytz.timezone('America/Sao_Paulo')).date()
DATA_INICIO = pd.to_datetime("2025-12-30").date()

df_hoje = run_query("SELECT * FROM public.consumo WHERE data = %s", (hoje,))
df_hist = run_query("""
    SELECT data, 
           SUM(kcal) as tkcal, 
           SUM(proteina) as tprot, 
           SUM(carbo) as tcarb, 
           SUM(gordura) as tgord,
           SUM(quantidade) as tqtd
    FROM public.consumo 
    WHERE data >= %s 
    GROUP BY data 
    ORDER BY data ASC
""", (DATA_INICIO,)) # Pegar desde o inicio para o calculo de deficit acumulado
df_peso = run_query("SELECT * FROM public.peso ORDER BY data ASC")

st.markdown(f"# 🦁 Leo's Performance | {hoje.strftime('%d/%m')}")

# KPI PRINCIPAIS
k_act, p_act, q_act = (df_hoje['kcal'].sum(), df_hoje['proteina'].sum(), df_hoje['quantidade'].sum()) if not df_hoje.empty else (0,0,0)
c1, c2, c3, c4 = st.columns(4)
c1.metric("🔥 Calorias Hoje", f"{int(k_act)}", f"Meta: {p['meta_kcal']}")
c2.metric("🥩 Proteína Hoje", f"{int(p_act)}g", f"Meta: {p['meta_proteina']}g")

# KPI Pressão
last_sys, last_dia, last_pulse = "--", "--", "--"
if not df_bp.empty:
    last_bp = df_bp.iloc[-1]
    last_sys, last_dia, last_pulse = last_bp['systolic'], last_bp['diastolic'], last_bp['pulse']

c3.metric("❤️ Pressão", f"{last_sys} x {last_dia}", "Normal" if isinstance(last_sys, int) and last_sys < 130 else "Atenção")
c4.metric("⚖️ Peso Atual", f"{PESO_ATUAL} kg")

st.divider()

# ==========================================
# NOVA SEÇÃO: ANALYTICS AVANÇADO
# ==========================================
st.subheader("📉 Inteligência de Perda de Peso")

col_a1, col_a2 = st.columns([2, 1])

with col_a1:
    st.markdown("##### Média Semanal vs Peso Diário (O Fim da Ansiedade)")
    if not df_peso.empty:
        # Calcular Média Móvel de 7 dias
        df_peso['media_movel'] = df_peso['peso_kg'].rolling(window=7, min_periods=1).mean()
        
        fig_trend = go.Figure()
        fig_trend.add_trace(go.Scatter(x=df_peso['data'], y=df_peso['peso_kg'], mode='markers', name='Pesagem Diária', marker=dict(color='gray', opacity=0.5, size=8)))
        fig_trend.add_trace(go.Scatter(x=df_peso['data'], y=df_peso['media_movel'], mode='lines', name='Tendência Real (7d)', line=dict(color='#2ecc71', width=4)))
        
        fig_trend.update_layout(height=300, margin=dict(l=10,r=10,t=20,b=10), hovermode="x unified", legend=dict(orientation="h", y=1.1))
        st.plotly_chart(fig_trend, use_container_width=True)

with col_a2:
    st.markdown("##### 🏦 Banco de Gordura")
    if not df_hist.empty:
        # Calcular Déficit Acumulado
        meta_fixa = float(p['meta_kcal'])
        df_hist['deficit_dia'] = meta_fixa - df_hist['tkcal']
        deficit_total = df_hist['deficit_dia'].sum()
        
        # Matemática: 7700kcal = 1kg gordura
        kg_teoricos = deficit_total / 7700
        
        st.metric("Calorias Economizadas (Total)", f"{int(deficit_total)} kcal")
        st.metric("Gordura Queimada (Teórico)", f"{kg_teoricos:.2f} kg", help="Baseado puramente na matemática: Déficit / 7700")
        
        if deficit_total > 0:
            st.success("Você está positivo no banco! A queima é inevitável.")
        else:
            st.warning("Atenção: Você comeu mais que a meta no acumulado.")

st.divider()

# ==========================================
# SEÇÃO 2: PROGRESSO DE PESO (CLÁSSICO)
# ==========================================
st.subheader("🎯 Planejamento vs Realidade")

peso_inicial = 146.0 # Ajustado para seu start real
ritmo_semanal = float(p.get('ritmo_semanal', 0.8))
ritmo_diario = ritmo_semanal / 7.0
peso_perdido = peso_inicial - PESO_ATUAL
dias_esperados = peso_perdido / ritmo_diario if ritmo_diario > 0 else 0
data_esperada_para_peso_atual = DATA_INICIO + timedelta(days=int(dias_esperados))
diferenca_dias = (hoje - data_esperada_para_peso_atual).days

col_p1, col_p2 = st.columns([1, 2])
with col_p1:
    st.write("") 
    if diferenca_dias < 0:
        st.success(f"🚀 **ADIANTADO: {abs(diferenca_dias)} dias**")
        st.caption(f"Você está pesando hoje ({PESO_ATUAL}kg) o que estava previsto apenas para **{data_esperada_para_peso_atual.strftime('%d/%m')}**.")
    elif diferenca_dias > 0:
        st.warning(f"⚠️ **ATRASADO: {diferenca_dias} dias**")
    else:
        st.info("🎯 **NO PLANO**")
    
    st.metric("Perda Total", f"{peso_perdido:.1f} kg")

with col_p2:
    if not df_peso.empty:
        d_total = (hoje + timedelta(days=60) - DATA_INICIO).days
        dates_m = [DATA_INICIO + timedelta(days=i) for i in range(d_total + 1)]
        vals_m = [max(float(p['meta_peso_alvo']), peso_inicial - (i * (ritmo_semanal/7))) for i in range(len(dates_m))]
        
        fig_combo = go.Figure()
        fig_combo.add_trace(go.Scatter(x=dates_m, y=vals_m, name="Meta Planejada", mode='lines', line=dict(color='gray', dash='dot')))
        fig_combo.add_trace(go.Scatter(x=df_peso['data'], y=df_peso['peso_kg'], name="Peso Real", mode='lines+markers', line=dict(color='#1f77b4', width=4)))
        fig_combo.add_trace(go.Scatter(x=[data_esperada_para_peso_atual], y=[PESO_ATUAL], mode='markers', marker=dict(color='purple', size=12, symbol='star'), name="Data Esperada"))
        fig_combo.update_layout(height=300, margin=dict(l=10,r=10,t=10,b=10), hovermode="x unified")
        st.plotly_chart(fig_combo, use_container_width=True)

st.divider()

# ==========================================
# SEÇÃO 3: SAÚDE & CORPO
# ==========================================
st.subheader("🧬 Saúde & Composição Corporal")

if not df_medidas.empty:
    last_m = df_medidas.iloc[-1]
    bf_atual = last_m['body_fat_est']
    cintura = last_m['waist_cm']
    quadril = last_m['hip_cm']
    pescoco = last_m['neck_cm']
    rcq = cintura / quadril if quadril > 0 else 0
    risco_rcq = "Baixo" if rcq < 0.90 else ("Moderado" if rcq < 0.95 else "Alto Risco")
    
    mc1, mc2, mc3, mc4 = st.columns(4)
    mc1.metric("⚖️ Peso (Medidas)", f"{last_m.get('weight_kg', PESO_ATUAL)} kg")
    mc2.metric("🐷 Gordura (BF)", f"{bf_atual:.1f}%", "-1.2% (Est)" if len(df_medidas) > 1 else None)
    mc3.metric("📏 Cintura", f"{cintura} cm", f"Pesc: {pescoco}cm")
    mc4.metric("🫀 Risco Cardíaco (RCQ)", f"{rcq:.2f}", risco_rcq, delta_color="inverse")

col_med, col_press = st.columns(2)
with col_med:
    st.markdown("**📉 Evolução de Gordura (%)**")
    if not df_medidas.empty:
        fig_bf = go.Figure()
        fig_bf.add_trace(go.Scatter(x=df_medidas['log_date'], y=df_medidas['body_fat_est'], mode='lines+markers', name='% Gordura', line=dict(color='#e67e22', width=3)))
        fig_bf.update_layout(height=250, margin=dict(l=10,r=10,t=20,b=10))
        st.plotly_chart(fig_bf, use_container_width=True)

with col_press:
    st.markdown("**🫀 Pressão Arterial**")
    if not df_bp.empty:
        fig_bp = go.Figure()
        fig_bp.add_hline(y=120, line_dash="dot", line_color="green", annotation_text="120")
        fig_bp.add_hline(y=80, line_dash="dot", line_color="green", annotation_text="80")
        
        fig_bp.add_trace(go.Scatter(x=df_bp['measurement_time'], y=df_bp['systolic'], name="Alta", line=dict(color='red')))
        fig_bp.add_trace(go.Scatter(x=df_bp['measurement_time'], y=df_bp['diastolic'], name="Baixa", line=dict(color='blue')))
        fig_bp.update_layout(height=250, margin=dict(l=10,r=10,t=20,b=10))
        st.plotly_chart(fig_bp, use_container_width=True)

st.divider()

# ==========================================
# SEÇÃO 4: NUTRIÇÃO & COMPORTAMENTO
# ==========================================
st.subheader("🍽️ Comportamento Alimentar")

if not df_hist.empty:
    df_macros = df_hist.copy()
    df_macros['kcal_p'] = df_macros['tprot'] * 4
    df_macros['kcal_c'] = df_macros['tcarb'] * 4
    df_macros['kcal_g'] = df_macros['tgord'] * 9
    df_macros['kcal_total_calc'] = df_macros['kcal_p'] + df_macros['kcal_c'] + df_macros['kcal_g']
    df_macros = df_macros[df_macros['kcal_total_calc'] > 0]
    
    df_macros['pct_p'] = (df_macros['kcal_p'] / df_macros['kcal_total_calc']) * 100
    df_macros['pct_c'] = (df_macros['kcal_c'] / df_macros['kcal_total_calc']) * 100
    df_macros['pct_g'] = (df_macros['kcal_g'] / df_macros['kcal_total_calc']) * 100

    c1, c2 = st.columns([2, 1])
    
    with c1:
        st.markdown("#### 📊 Distribuição de Macros (%)")
        fig_stack = go.Figure()
        fig_stack.add_trace(go.Bar(x=df_macros['data'], y=df_macros['pct_p'], name='Proteína', marker_color='#3366CC'))
        fig_stack.add_trace(go.Bar(x=df_macros['data'], y=df_macros['pct_g'], name='Gordura', marker_color='#DC3912'))
        fig_stack.add_trace(go.Bar(x=df_macros['data'], y=df_macros['pct_c'], name='Carbo', marker_color='#FF9900'))
        
        fig_stack.update_layout(barmode='stack', height=350, margin=dict(l=10,r=10,t=20,b=10), legend=dict(orientation="h", y=1.1), yaxis=dict(title="Percentual (%)", range=[0, 100]))
        st.plotly_chart(fig_stack, use_container_width=True)
        
    with c2:
        st.markdown("#### 🥗 Hoje")
        if k_act > 0:
            c_act = df_hoje['carbo'].sum()
            g_act = df_hoje['gordura'].sum()
            fig_p = go.Figure(data=[go.Pie(labels=['Prot','Carb','Gord'], values=[p_act*4, c_act*4, g_act*9], hole=.4, marker=dict(colors=['#3366CC','#FF9900','#DC3912']))])
            fig_p.update_layout(height=350, margin=dict(l=10,r=10,t=20,b=10), showlegend=False)
            st.plotly_chart(fig_p, use_container_width=True)
        else:
            st.info("Registre sua alimentação hoje para ver a distribuição.")

    # Gráfico de Heatmap Semanal (Novo!)
    st.markdown("#### 📅 Média Calórica por Dia da Semana")
    df_hist['dia_semana'] = df_hist['data'].dt.day_name()
    df_week = df_hist.groupby('dia_semana')['tkcal'].mean().reindex(['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday']).reset_index()
    
    fig_week = go.Figure(go.Bar(
        x=df_week['dia_semana'], y=df_week['tkcal'], 
        marker_color=['#3498db']*5 + ['#e74c3c']*2 # Fim de semana vermelho
    ))
    fig_week.add_hline(y=float(p['meta_kcal']), line_dash="dot", annotation_text="Meta")
    fig_week.update_layout(height=250, margin=dict(l=10,r=10,t=20,b=10), title="Onde está o perigo? (Médias)")
    st.plotly_chart(fig_week, use_container_width=True)

else:
    st.info("Sem dados de consumo registrados.")
