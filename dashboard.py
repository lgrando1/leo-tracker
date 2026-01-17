import streamlit as st
import pandas as pd
from sqlalchemy import create_engine, text
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

# --- CONEXÃO BLINDADA (SQLAlchemy) ---
@st.cache_resource(ttl=600)
def get_engine():
    db_url = st.secrets["DATABASE_URL"]
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)
    return create_engine(db_url)

def run_query(query, params=None, is_select=True):
    engine = get_engine()
    try:
        if is_select:
            with engine.connect() as conn:
                df = pd.read_sql(text(query), conn, params=params)
                for col in ['data', 'log_date', 'measurement_time']:
                    if col in df.columns:
                        try: df[col] = pd.to_datetime(df[col])
                        except: pass
                return df
        else:
            with engine.begin() as conn:
                conn.execute(text(query), params)
            return True
    except Exception as e:
        return pd.DataFrame() if is_select else False

# --- TRAVA DE SEGURANÇA ---
if st.query_params.get("token") != st.secrets.get("DASH_ACCESS_TOKEN"):
    st.error("🔒 Acesso Negado."); st.stop()

# --- 1. BUSCA DE DADOS ---
df_perfil = run_query("SELECT * FROM public.perfil WHERE id = 1")
df_peso_last = run_query("SELECT peso_kg FROM public.peso ORDER BY data DESC, id DESC LIMIT 1")
df_medidas = run_query("SELECT * FROM public.body_measurements ORDER BY log_date ASC")
df_bp = run_query("SELECT * FROM public.blood_pressure ORDER BY measurement_time ASC")

# Valores Padrão
if not df_perfil.empty:
    p = df_perfil.iloc[0]
else:
    p = {'genero': 'Masculino', 'idade': 41, 'altura_cm': 178, 'atividade': 'Sedentário (1.2)', 
         'objetivo': 'Perder Peso (Moderado)', 'ritmo_semanal': 0.8, 'meta_kcal': 1650, 
         'meta_proteina': 130, 'meta_carbo': 150, 'meta_gordura': 59, 'meta_peso_alvo': 120.0}

PESO_ATUAL = float(df_peso_last.iloc[0]['peso_kg']) if not df_peso_last.empty else 141.9
META_AGUA = round((PESO_ATUAL * 35) / 1000, 1)

# --- 2. VARIÁVEIS DE SAÚDE ---
last_sys, last_dia, last_pulse = "--", "--", "--"
if not df_bp.empty:
    last_bp = df_bp.iloc[-1]
    last_sys, last_dia = last_bp['systolic'], last_bp['diastolic']
    last_pulse = last_bp.get('pulse', "--")

# --- 3. HISTÓRICO ---
hoje = datetime.now(pytz.timezone('America/Sao_Paulo')).date()
DATA_INICIO = pd.to_datetime("2025-12-30").date()

df_hoje = run_query("SELECT * FROM public.consumo WHERE data = :d", {"d": hoje})
df_hist = run_query("""
    SELECT data, SUM(kcal) as tkcal, SUM(proteina) as tprot, SUM(carbo) as tcarb, 
           SUM(gordura) as tgord, SUM(quantidade) as tqtd
    FROM public.consumo WHERE data >= :d GROUP BY data ORDER BY data ASC
""", {"d": DATA_INICIO})
df_peso = run_query("SELECT * FROM public.peso ORDER BY data ASC")

# Variáveis de Hoje
if not df_hoje.empty:
    k_act = df_hoje['kcal'].sum()
    p_act = df_hoje['proteina'].sum()
    c_act = df_hoje['carbo'].sum()
    g_act = df_hoje['gordura'].sum()
else:
    k_act, p_act, c_act, g_act = 0, 0, 0, 0

# --- INTERFACE ---
st.markdown(f"# 🦁 Leo's Performance | {hoje.strftime('%d/%m')}")

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("🔥 Calorias", f"{int(k_act)}", f"Meta: {p['meta_kcal']}")
c2.metric("🥩 Proteína", f"{int(p_act)}g", f"Meta: {p['meta_proteina']}g")
c3.metric("💧 Água", f"{META_AGUA}L", "Meta Mínima")
c4.metric("❤️ Pressão", f"{last_sys}x{last_dia}", f"Pulso: {last_pulse}")
c5.metric("⚖️ Peso", f"{PESO_ATUAL}kg", f"Alvo: {p['meta_peso_alvo']}")

st.divider()

# ============================================================================
# 🎯 PROJEÇÃO VS REALIDADE (DATA BASE 31/12/2025)
# ============================================================================
st.subheader("🎯 Projeção vs. Realidade")
if not df_peso.empty:
    df_peso['data_dt'] = pd.to_datetime(df_peso['data']).dt.date
    BASE_DATE = pd.to_datetime("2025-12-31").date()
    df_base = df_peso[df_peso['data_dt'] >= BASE_DATE].sort_values('data_dt')
    
    if not df_base.empty:
        peso_inicial = float(df_base.iloc[0]['peso_kg'])
        datas_proj = pd.date_range(start=BASE_DATE, end=hoje)
        ritmo_diario = p['ritmo_semanal'] / 7
        pesos_estimados = [peso_inicial - (i * ritmo_diario) for i in range(len(datas_proj))]
        peso_esperado_hoje = peso_inicial - ((hoje - BASE_DATE).days * ritmo_diario)
        diferenca_peso = PESO_ATUAL - peso_esperado_hoje
        dias_diff = diferenca_peso / ritmo_diario
        
        cp1, cp2, cp3 = st.columns([2, 1, 1])
        with cp1:
            fig_proj = go.Figure()
            fig_proj.add_trace(go.Scatter(x=datas_proj, y=pesos_estimados, mode='lines', name='Meta (Previsto)', line=dict(color='#29B5E8', dash='dash')))
            fig_proj.add_trace(go.Scatter(x=df_base['data_dt'], y=df_base['peso_kg'], mode='lines+markers', name='Realizado', line=dict(color='#FF4B4B', width=3)))
            fig_proj.update_layout(height=350, margin=dict(l=10,r=10,t=20,b=10), legend=dict(orientation="h", y=1.1))
            st.plotly_chart(fig_proj, use_container_width=True)
        with cp2:
            st.write("")
            st.metric("Peso Esperado (Hoje)", f"{peso_esperado_hoje:.1f} kg")
            status_cor = "normal" if dias_diff <= 0 else "inverse"
            label_status = "Adiantado" if dias_diff <= 0 else "Atrasado"
            st.metric(f"Status vs Cronograma", f"{abs(dias_diff):.1f} dias", f"{label_status}", delta_color=status_cor)
        with cp3:
            st.write("")
            meta_atingir = PESO_ATUAL - p['meta_peso_alvo']
            semanas_restantes = meta_atingir / p['ritmo_semanal']
            data_final = hoje + timedelta(weeks=semanas_restantes)
            st.metric("Distância do Alvo", f"{meta_atingir:.1f} kg")
            st.metric("Previsão de Chegada", data_final.strftime('%d/%m/%y'))

st.divider()

# ANALYTICS AVANÇADO
st.subheader("📉 Inteligência de Perda de Peso")
col_a1, col_a2 = st.columns([2, 1])

with col_a1:
    if not df_peso.empty:
        df_peso['media_movel'] = df_peso['peso_kg'].rolling(window=7, min_periods=1).mean()
        fig_trend = go.Figure()
        fig_trend.add_trace(go.Scatter(x=df_peso['data'], y=df_peso['peso_kg'], mode='markers', name='Pesagem Diária', marker=dict(color='gray', opacity=0.4)))
        fig_trend.add_trace(go.Scatter(x=df_peso['data'], y=df_peso['media_movel'], mode='lines', name='Tendência (7d)', line=dict(color='#2ecc71', width=4)))
        fig_trend.update_layout(height=300, margin=dict(l=10,r=10,t=20,b=10), legend=dict(orientation="h", y=1.1))
        st.plotly_chart(fig_trend, use_container_width=True)

with col_a2:
    st.markdown("##### 🏦 Banco de Gordura")
    if not df_hist.empty and not df_peso.empty:
        try:
            df_hist['data_dt'] = pd.to_datetime(df_hist['data']).dt.date
            df_peso['data_dt'] = pd.to_datetime(df_peso['data']).dt.date
            df_merged = pd.merge(df_hist, df_peso[['data_dt', 'peso_kg']], on='data_dt', how='left').ffill()
            idade, altura = int(p.get('idade', 41)), int(p.get('altura_cm', 178))
            df_merged['get_dia'] = ((10 * df_merged['peso_kg']) + (6.25 * altura) - (5 * idade) + 5) * 1.09 * 1.2
            deficit_total = (df_merged['get_dia'] - df_merged['tkcal']).sum()
            kg_gordura = deficit_total / 7700
            st.metric("Déficit Acumulado", f"{int(deficit_total)} kcal")
            st.metric("Gordura Eliminada (Teórica)", f"{kg_gordura:.2f} kg")
        except: st.info("Sincronizando dados...")
    else: st.info("Aguardando dados...")

st.divider()

# SAÚDE & COMPOSIÇÃO
st.subheader("🧬 Saúde & Composição Corporal")

if not df_medidas.empty:
    l_m = df_medidas.iloc[-1]
    def safe_get(key, default=0.0):
        val = l_m.get(key)
        if pd.isna(val): return default
        return float(val)

    bf_est, bf_welt, bf_pol, dobra_abd = safe_get('body_fat_est'), safe_get('body_fat_weltman'), safe_get('body_fat_pollock'), safe_get('fold_abdominal')
    
    if bf_welt > 0 and abs(bf_est - bf_welt) < 0.1: label_bf = "🐷 Gordura (Weltman)"
    elif bf_pol > 0 and abs(bf_est - bf_pol) < 0.1: label_bf = "🐷 Gordura (Pollock)"
    else: label_bf = "🐷 Gordura (Navy/Est)"

    rcq = l_m['waist_cm'] / l_m['hip_cm'] if l_m['hip_cm'] > 0 else 0
    m1, m2, m3, m4 = st.columns(4)
    m1.metric(label_bf, f"{bf_est:.1f}%")
    m2.metric("📏 Cintura", f"{l_m['waist_cm']} cm")
    m3.metric("🫀 Risco (RCQ)", f"{rcq:.2f}", "Moderado" if rcq > 0.9 else "Baixo")
    if dobra_abd > 0: m4.metric("🤏 Dobra Abdominal", f"{dobra_abd} mm")
    else: m4.metric("📐 Quadril", f"{l_m['hip_cm']} cm")

col_left, col_right = st.columns(2)
with col_left:
    st.markdown("**📉 Evolução de Gordura (%)**")
    fig_bf = go.Figure(go.Scatter(x=df_medidas['log_date'], y=df_medidas['body_fat_est'], mode='lines+markers', line=dict(color='#e67e22')))
    fig_bf.update_layout(height=250, margin=dict(l=10,r=10,t=20,b=10))
    st.plotly_chart(fig_bf, use_container_width=True)

with col_right:
    st.markdown("**🫀 Pressão Arterial**")
    if not df_bp.empty:
        fig_bp = go.Figure()
        fig_bp.add_trace(go.Scatter(x=df_bp['measurement_time'], y=df_bp['systolic'], name="Sist.", line=dict(color='red')))
        fig_bp.add_trace(go.Scatter(x=df_bp['measurement_time'], y=df_bp['diastolic'], name="Diast.", line=dict(color='blue')))
        fig_bp.update_layout(height=250, margin=dict(l=10,r=10,t=20,b=10))
        st.plotly_chart(fig_bp, use_container_width=True)

st.divider()

# NUTRIÇÃO
st.subheader("🍽️ Comportamento Alimentar")

if not df_hist.empty:
    st.markdown("##### ⚖️ Volume de Comida (g) vs. Energia (kcal)")
    fig_vol = make_subplots(specs=[[{"secondary_y": True}]])

    # Barras de Calorias
    fig_vol.add_trace(go.Bar(x=df_hist['data'], y=df_hist['tkcal'], name="Calorias (kcal)", marker_color='#e74c3c', opacity=0.7), secondary_y=False)
    # Linha de Volume
    fig_vol.add_trace(go.Scatter(x=df_hist['data'], y=df_hist['tqtd'], name="Volume (g)", mode='lines+markers', line=dict(color='#3498db', width=3)), secondary_y=True)
    
    # 1. LINHA DE META (MARCELA)
    fig_vol.add_hline(y=p['meta_kcal'], line_dash="dash", line_color="#27ae60", annotation_text=f"Meta Marcela ({p['meta_kcal']} kcal)", annotation_position="top left", secondary_y=False)

    # 2. LINHA DINÂMICA DE GET (Gasto Energético do Dia)
    try:
        # Prepara dados para o GET
        df_chart = df_hist.copy()
        df_chart['data_dt'] = pd.to_datetime(df_chart['data']).dt.date
        
        if not df_peso.empty:
            df_peso_chart = df_peso.copy()
            df_peso_chart['data_dt'] = pd.to_datetime(df_peso_chart['data']).dt.date
            # Garante apenas um peso por dia para o merge
            df_peso_chart = df_peso_chart.sort_values('data').drop_duplicates(subset='data_dt', keep='last')
            
            # Merge para trazer o peso para cada dia do histórico
            df_chart = pd.merge(df_chart, df_peso_chart[['data_dt', 'peso_kg']], on='data_dt', how='left')
            # Preenche dias sem peso com o último peso conhecido (Forward Fill)
            df_chart['peso_kg'] = df_chart['peso_kg'].ffill().fillna(PESO_ATUAL)
            
            # Calcula GET
            idade, altura = int(p.get('idade', 41)), int(p.get('altura_cm', 178))
            df_chart['get_dia'] = ((10 * df_chart['peso_kg']) + (6.25 * altura) - (5 * idade) + 5) * 1.09 * 1.2
            
            # Adiciona a linha ao gráfico
            fig_vol.add_trace(go.Scatter(x=df_chart['data'], y=df_chart['get_dia'], name="Gasto Real (GET)", mode='lines', line=dict(color='#f39c12', width=2, dash='dot')), secondary_y=False)
    except: pass

    fig_vol.update_layout(height=350, margin=dict(l=10,r=10,t=20,b=10), legend=dict(orientation="h", y=1.1), yaxis=dict(title="Energia (kcal)", showgrid=False), yaxis2=dict(title="Volume (g)", showgrid=False))
    st.plotly_chart(fig_vol, use_container_width=True)

    c_n1, c_n2 = st.columns([2, 1])
    with c_n1:
        st.markdown("##### Distribuição de Macros")
        df_macros = df_hist.copy()
        df_macros['tot'] = (df_macros['tprot']*4 + df_macros['tcarb']*4 + df_macros['tgord']*9).replace(0, 1)
        fig_stack = go.Figure()
        fig_stack.add_trace(go.Bar(x=df_macros['data'], y=(df_macros['tprot']*4/df_macros['tot'])*100, name='Prot', marker_color='#3366CC'))
        fig_stack.add_trace(go.Bar(x=df_macros['data'], y=(df_macros['tgord']*9/df_macros['tot'])*100, name='Gord', marker_color='#DC3912'))
        fig_stack.add_trace(go.Bar(x=df_macros['data'], y=(df_macros['tcarb']*4/df_macros['tot'])*100, name='Carb', marker_color='#FF9900'))
        fig_stack.update_layout(barmode='stack', height=350, margin=dict(l=10,r=10,t=20,b=10), yaxis=dict(range=[0, 100]))
        st.plotly_chart(fig_stack, use_container_width=True)
    with c_n2:
        st.markdown("##### Hoje")
        if k_act > 0:
            fig_pie = go.Figure(data=[go.Pie(labels=['P','C','G'], values=[p_act*4, c_act*4, g_act*9], hole=.4, marker=dict(colors=['#3366CC','#FF9900','#DC3912']))])
            fig_pie.update_layout(height=350, showlegend=False, margin=dict(l=10,r=10,t=20,b=10))
            st.plotly_chart(fig_pie, use_container_width=True)

st.caption("Leo Tracker Dash v3.3 | Dynamic GET Line")
