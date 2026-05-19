import os
import streamlit as st
import pandas as pd
import numpy as np
from sqlalchemy import create_engine, text
from datetime import datetime, timedelta
import pytz
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# ============================================================================
# 1. CONFIG E CSS
# ============================================================================
st.set_page_config(
    page_title="Leo · Jornada de Transformação",
    page_icon="🦁",
    layout="wide",
    initial_sidebar_state="collapsed"
)

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Syne:wght@400;700;800&family=DM+Sans:wght@400;500&display=swap');

#MainMenu {visibility: hidden;} footer {visibility: hidden;} header {visibility: hidden;}

html, body, [class*="css"] { font-family: 'DM Sans', sans-serif; }

/* HERO CARD */
.hero-card {
    background: linear-gradient(135deg, #0f172a 0%, #1e3a5f 60%, #0f2d40 100%);
    border-radius: 20px;
    padding: 32px 36px;
    margin-bottom: 24px;
    color: white;
    position: relative;
    overflow: hidden;
}
.hero-card::before {
    content: '';
    position: absolute;
    top: -60px; right: -60px;
    width: 220px; height: 220px;
    background: radial-gradient(circle, rgba(16,185,129,0.15) 0%, transparent 70%);
    border-radius: 50%;
}
.hero-day {
    font-family: 'Syne', sans-serif;
    font-size: 13px;
    font-weight: 700;
    letter-spacing: 3px;
    text-transform: uppercase;
    color: #10b981;
    margin-bottom: 6px;
}
.hero-title {
    font-family: 'Syne', sans-serif;
    font-size: 42px;
    font-weight: 800;
    line-height: 1.1;
    margin-bottom: 8px;
}
.hero-title span { color: #10b981; }
.hero-subtitle {
    font-size: 14px;
    color: rgba(255,255,255,0.6);
    margin-bottom: 24px;
}
.hero-stats {
    display: flex;
    gap: 32px;
    flex-wrap: wrap;
}
.hero-stat-label {
    font-size: 11px;
    letter-spacing: 1.5px;
    text-transform: uppercase;
    color: rgba(255,255,255,0.45);
    margin-bottom: 2px;
}
.hero-stat-value {
    font-family: 'Syne', sans-serif;
    font-size: 26px;
    font-weight: 800;
}
.hero-stat-value.green { color: #10b981; }
.hero-stat-value.yellow { color: #f59e0b; }
.hero-stat-value.white { color: #ffffff; }

/* PROGRESS BAR */
.progress-track {
    background: rgba(255,255,255,0.1);
    border-radius: 10px;
    height: 8px;
    margin-top: 20px;
    position: relative;
    overflow: hidden;
}
.progress-fill {
    height: 100%;
    border-radius: 10px;
    background: linear-gradient(90deg, #10b981, #34d399);
    transition: width 0.8s ease;
}
.progress-label {
    display: flex;
    justify-content: space-between;
    font-size: 11px;
    color: rgba(255,255,255,0.45);
    margin-top: 6px;
}

/* BADGES */
.badge-panel { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 16px; }
.badge {
    padding: 5px 12px;
    border-radius: 20px;
    font-size: 11px;
    font-weight: 700;
    font-family: 'Syne', sans-serif;
    letter-spacing: 0.5px;
    text-transform: uppercase;
}
.badge-green  { background: rgba(16,185,129,0.12); color: #059669; border: 1px solid rgba(16,185,129,0.35); }
.badge-yellow { background: rgba(245,158,11,0.12);  color: #d97706; border: 1px solid rgba(245,158,11,0.35); }
.badge-red    { background: rgba(239,68,68,0.12);   color: #dc2626; border: 1px solid rgba(239,68,68,0.35); }
.badge-blue   { background: rgba(59,130,246,0.12);  color: #2563eb; border: 1px solid rgba(59,130,246,0.35); }

/* SECTION HEADER */
.section-header {
    font-family: 'Syne', sans-serif;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 3px;
    text-transform: uppercase;
    color: #94a3b8;
    margin: 28px 0 14px 0;
    padding-bottom: 8px;
    border-bottom: 1px solid #e2e8f0;
}

/* INSIGHT BOX */
.insight-box {
    background: #f0fdf4;
    border-left: 3px solid #10b981;
    border-radius: 0 8px 8px 0;
    padding: 12px 16px;
    font-size: 14px;
    color: #065f46;
    margin: 10px 0;
}
.insight-box.warn {
    background: #fffbeb;
    border-color: #f59e0b;
    color: #78350f;
}
.insight-box.alert {
    background: #fef2f2;
    border-color: #ef4444;
    color: #7f1d1d;
}

/* CYCLING CARD */
.cycling-card {
    background: linear-gradient(135deg, #ecfdf5, #d1fae5);
    border: 1px solid #a7f3d0;
    border-radius: 14px;
    padding: 18px 22px;
}
.cycling-title {
    font-family: 'Syne', sans-serif;
    font-size: 12px;
    font-weight: 700;
    letter-spacing: 2px;
    text-transform: uppercase;
    color: #059669;
    margin-bottom: 10px;
}

/* METRICS */
div[data-testid="stMetric"] {
    background: #f8fafc;
    padding: 16px;
    border-radius: 14px;
    border: 1px solid #e2e8f0;
    box-shadow: 0 1px 4px rgba(0,0,0,0.04);
}
@media (prefers-color-scheme: dark) {
    div[data-testid="stMetric"] { background: #1e293b; border-color: #334155; }
    .section-header { border-color: #334155; color: #64748b; }
    .insight-box { background: #064e3b; color: #6ee7b7; }
    .insight-box.warn { background: #451a03; color: #fcd34d; }
    .cycling-card { background: #064e3b; border-color: #065f46; }
}

/* CHAPTER PILL */
.chapter-pill {
    display: inline-block;
    background: #0f172a;
    color: #10b981;
    font-family: 'Syne', sans-serif;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 2px;
    text-transform: uppercase;
    padding: 4px 14px;
    border-radius: 20px;
    margin-bottom: 10px;
}
</style>
""", unsafe_allow_html=True)

# ============================================================================
# 2. CONEXÃO E ETL BLINDADO
# ============================================================================
@st.cache_resource(ttl=600)
def get_engine():
    db_url = st.secrets.get("DATABASE_URL", "")
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)
    return create_engine(db_url, pool_pre_ping=True)

def run_query(query, params=None):
    engine = get_engine()
    try:
        with engine.connect() as conn:
            df = pd.read_sql(text(query), conn, params=params)
            for col in ['data', 'log_date', 'measurement_time']:
                if col in df.columns:
                    try:
                        df[col] = pd.to_datetime(df[col]).dt.date
                    except:
                        pass
            return df
    except Exception as e:
        st.error(f"🚨 DB Error: {e}")
        return pd.DataFrame()

# ── AUTH ──────────────────────────────────────────────────────────────────────
if st.query_params.get("token") != st.secrets.get("DASH_ACCESS_TOKEN"):
    st.error("🔒 Acesso Restrito.")
    st.stop()

# ── DATAS BASE ────────────────────────────────────────────────────────────────
hoje = datetime.now(pytz.timezone('America/Sao_Paulo')).date()
DATA_INICIO = pd.to_datetime("2024-12-30").date()
dias_jornada = (hoje - DATA_INICIO).days

# ── QUERIES ───────────────────────────────────────────────────────────────────
df_perfil  = run_query("SELECT * FROM public.perfil WHERE id = 1")
df_peso    = run_query("SELECT * FROM public.peso ORDER BY data ASC")
df_medidas = run_query("SELECT * FROM public.body_measurements ORDER BY log_date ASC")
df_bp      = run_query("SELECT * FROM public.blood_pressure ORDER BY measurement_time ASC")
df_hist    = run_query("""
    SELECT data, SUM(kcal) as tkcal, SUM(proteina) as tprot,
           SUM(carbo) as tcarb, SUM(gordura) as tgord
    FROM public.consumo WHERE data >= :d GROUP BY data ORDER BY data ASC
""", {"d": DATA_INICIO})
df_treino  = run_query("""
    SELECT data,
           SUM(duracao_min)       as t_min,
           SUM(passos_trabalho)   as t_passos_trabalho,
           SUM(calorias)          as t_cal_out
    FROM public.exercicios WHERE data >= :d GROUP BY data ORDER BY data ASC
""", {"d": DATA_INICIO})
df_hidra   = run_query("""
    SELECT data, SUM(agua_ml) as tagua
    FROM public.hidratacao WHERE data >= :d GROUP BY data ORDER BY data ASC
""", {"d": DATA_INICIO})
df_hoje_c  = run_query("""
    SELECT SUM(kcal) as k, SUM(proteina) as p, SUM(carbo) as c, SUM(gordura) as g
    FROM public.consumo WHERE data = :d
""", {"d": hoje})

# ── PERFIL ────────────────────────────────────────────────────────────────────
p = df_perfil.iloc[0] if not df_perfil.empty else {
    'meta_kcal': 1415, 'meta_proteina': 104, 'meta_carbo': 105,
    'meta_gordura': 71, 'meta_peso_alvo': 120.0,
    'fator_atividade': 1.2, 'ritmo_semanal': 0.8
}
meta_kcal = int(p['meta_kcal'])
meta_prot = int(p['meta_proteina'])
meta_carb = int(p['meta_carbo'])
meta_gord = int(p['meta_gordura'])
meta_peso_alvo = float(p['meta_peso_alvo'])

# ── ETL MERGED ────────────────────────────────────────────────────────────────
df_merged = pd.DataFrame()

if not df_hist.empty and not df_peso.empty:
    df_peso_u = df_peso.copy()
    df_peso_u['data_dt'] = df_peso_u['data']
    df_peso_u = df_peso_u.drop_duplicates(subset=['data_dt'], keep='last')

    df_hist['data_dt'] = df_hist['data']
    df_merged = pd.merge(
        df_hist,
        df_peso_u[['data_dt', 'peso_kg']],
        on='data_dt', how='left'
    ).ffill()
    df_merged['peso_kg'] = df_merged['peso_kg'].bfill().fillna(115.0)

    for df_tmp, col_list in [
        (df_treino, ['t_min', 't_passos_trabalho', 't_cal_out']),
        (df_hidra,  ['tagua'])
    ]:
        if not df_tmp.empty:
            df_tmp['data_dt'] = df_tmp['data']
            df_merged = pd.merge(
                df_merged,
                df_tmp.groupby('data_dt')[col_list].sum().reset_index(),
                on='data_dt', how='left'
            )
            for c in col_list:
                df_merged[c] = df_merged[c].fillna(0)

    if not df_medidas.empty:
        df_med_tmp = df_medidas.copy()
        df_med_tmp['data_dt'] = df_med_tmp['log_date']
        df_merged = pd.merge(
            df_merged,
            df_med_tmp.groupby('data_dt')[['waist_cm']].last().reset_index(),
            on='data_dt', how='left'
        )
    else:
        df_merged['waist_cm'] = np.nan

    df_merged['waist_cm'] = df_merged['waist_cm'].bfill().ffill()
    df_merged['data'] = df_merged['data_dt']
    df_merged['peso_ewma']    = df_merged['peso_kg'].ewm(span=7, adjust=False).mean()
    df_merged['cintura_ewma'] = df_merged['waist_cm'].ewm(span=7, adjust=False).mean()

    df_merged['get_total'] = (
        ((10 * df_merged['peso_kg']) + (6.25 * 178) - (5 * 41) + 5)
        * float(p['fator_atividade'])
    ) + df_merged['t_cal_out']
    df_merged['deficit_real'] = df_merged['get_total'] - df_merged['tkcal']
    df_merged['%G_weltman']   = (
        (0.31457 * df_merged['cintura_ewma'])
        - (0.10969 * df_merged['peso_ewma'])
        + 10.834
    )
    df_merged['massa_magra'] = df_merged['peso_ewma'] * (
        1 - (df_merged['%G_weltman'] / 100)
    )

# ── PESO INÍCIO / ATUAL ───────────────────────────────────────────────────────
peso_inicio = None
peso_atual  = None

if not df_peso.empty:
    peso_inicio_row = df_peso[df_peso['data'] >= DATA_INICIO]
    if not peso_inicio_row.empty:
        peso_inicio = float(peso_inicio_row.iloc[0]['peso_kg'])
    peso_atual = float(df_peso.iloc[-1]['peso_kg'])

peso_perdido = round(peso_inicio - peso_atual, 1) if peso_inicio and peso_atual else 33.0
falta_meta   = round(peso_atual - meta_peso_alvo, 1) if peso_atual else None
pct_jornada  = min(100, round((peso_perdido / (peso_perdido + (falta_meta or 0))) * 100))

# ── MOTOR FISIOLÓGICO ─────────────────────────────────────────────────────────
confidence_score = retention_score = recovery_load = consistency_score = 0
status_txt, status_class = "COLETANDO SINAIS", "badge-blue"
atual = anterior = None

if not df_merged.empty and len(df_merged) >= 3:
    atual   = df_merged.iloc[-1]
    anterior = df_merged.iloc[-2]

    d_peso    = atual['peso_ewma'] - anterior['peso_ewma']
    d_cintura = (atual['cintura_ewma'] - anterior['cintura_ewma']) if pd.notnull(atual['cintura_ewma']) else 0

    input_metrics = [
        pd.notnull(atual['peso_kg']),
        pd.notnull(atual['waist_cm']),
        atual['tagua'] > 0,
        atual['t_passos_trabalho'] > 0,
    ]
    confidence_score = int(sum(input_metrics) / len(input_metrics) * 100)

    criterio_ret_1 = 40 if (d_peso > 0.05 and d_cintura <= 0) else 0
    criterio_ret_2 = 30 if atual['t_passos_trabalho'] > 12000 else 0
    criterio_ret_3 = 30 if atual['tagua'] < (atual['peso_kg'] * 30) else 0
    retention_score = criterio_ret_1 + criterio_ret_2 + criterio_ret_3

    criterio_rec_1 = 50 if atual['t_passos_trabalho'] > 14000 else (25 if atual['t_passos_trabalho'] > 9000 else 0)
    criterio_rec_2 = 50 if atual['deficit_real'] > 800 else (25 if atual['deficit_real'] > 400 else 0)
    recovery_load  = criterio_rec_1 + criterio_rec_2

    ultimos_dias   = df_merged.tail(3)
    macro_check    = sum((ultimos_dias['tprot'] >= meta_prot - 10).astype(int))
    agua_check     = sum((ultimos_dias['tagua'] >= (ultimos_dias['peso_kg'] * 35)).astype(int))
    consistency_score = int(((macro_check + agua_check) / 6) * 100)

    if retention_score >= 60:
        status_txt, status_class = "RETENÇÃO PROVÁVEL", "badge-yellow"
    elif d_cintura < 0 and d_peso <= 0.05:
        status_txt, status_class = "RECOMPOSIÇÃO EFICIENTE", "badge-green"
    elif recovery_load >= 75:
        status_txt, status_class = "ESTRESSE SISTÊMICO ALTO", "badge-red"
    else:
        status_txt, status_class = "ESTÁVEL — CRUZEIRO", "badge-blue"

# ── CICLISMO STATS ────────────────────────────────────────────────────────────
# Como não há campo tipo, usamos a tabela completa de treinos como proxy de atividade
total_min_treino   = int(df_treino['t_min'].sum())   if not df_treino.empty else 0
total_sessoes      = int(len(df_treino))             if not df_treino.empty else 0
total_cal_treino   = int(df_treino['t_cal_out'].sum()) if not df_treino.empty else 0
media_min_sessao   = round(total_min_treino / total_sessoes, 0) if total_sessoes > 0 else 0

# ── PRESSÃO ARTERIAL ──────────────────────────────────────────────────────────
bp_valida = not df_bp.empty and 'systolic' in df_bp.columns and 'diastolic' in df_bp.columns

# ============================================================================
# 3. INTERFACE — NARRATIVA
# ============================================================================

# ── CAPÍTULO HERO ─────────────────────────────────────────────────────────────
peso_perdido_str = f"{peso_perdido:.1f}" if peso_perdido else "—"
peso_atual_str   = f"{peso_atual:.1f} kg"  if peso_atual  else "—"
falta_meta_str   = f"{falta_meta:.1f} kg"  if falta_meta  else "—"

progress_html = ""
if falta_meta is not None:
    progress_html = f"""
    <div class="progress-track">
        <div class="progress-fill" style="width:{pct_jornada}%"></div>
    </div>
    <div class="progress-label">
        <span>🏁 Início: 30 Dez 2024</span>
        <span>{pct_jornada}% da jornada concluída</span>
        <span>🎯 Meta: {meta_peso_alvo:.0f} kg</span>
    </div>
    """

st.markdown(f"""
<div class="hero-card">
    <div class="hero-day">🦁 &nbsp; Dia {dias_jornada} da Jornada</div>
    <div class="hero-title">Você perdeu <span>-{peso_perdido_str} kg</span></div>
    <div class="hero-subtitle">Desde 30 de dezembro de 2024 · Isso é extraordinário.</div>
    <div class="hero-stats">
        <div>
            <div class="hero-stat-label">Peso Atual</div>
            <div class="hero-stat-value white">{peso_atual_str}</div>
        </div>
        <div>
            <div class="hero-stat-label">Perdidos</div>
            <div class="hero-stat-value green">−{peso_perdido_str} kg</div>
        </div>
        <div>
            <div class="hero-stat-label">Faltam para a Meta</div>
            <div class="hero-stat-value yellow">{falta_meta_str}</div>
        </div>
        <div>
            <div class="hero-stat-label">Sessões de Treino</div>
            <div class="hero-stat-value white">{total_sessoes}</div>
        </div>
    </div>
    {progress_html}
</div>
""", unsafe_allow_html=True)

# ── ESTADO FISIOLÓGICO ────────────────────────────────────────────────────────
st.markdown('<div class="section-header">📡 Estado Fisiológico — Hoje</div>', unsafe_allow_html=True)

st.markdown(f"""
<div class="badge-panel">
    <span class="badge {status_class}">🎯 {status_txt}</span>
    <span class="badge {'badge-green' if confidence_score >= 75 else 'badge-yellow'}">🔍 Telemetria: {confidence_score}%</span>
    <span class="badge {'badge-green' if consistency_score >= 75 else 'badge-yellow'}">🛡️ Aderência 3D: {consistency_score}%</span>
</div>
""", unsafe_allow_html=True)

col_p1, col_p2, col_p3 = st.columns(3)
col_p1.progress(retention_score / 100, text=f"💧 Risco de Retenção: {retention_score}%")
col_p2.progress(recovery_load / 100,   text=f"⚡ Estresse Fisiológico: {recovery_load}%")
col_p3.progress(consistency_score / 100, text=f"📈 Consistência: {consistency_score}%")

# ── TENDÊNCIAS CORPORAIS ──────────────────────────────────────────────────────
st.markdown('<div class="section-header">📉 Tendências Corporais (Filtro EWMA)</div>', unsafe_allow_html=True)

if not df_merged.empty and atual is not None:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("⚖️ Peso (EWMA)", f"{atual['peso_ewma']:.2f} kg",     f"{d_peso*1000:+.0f} g (48h)")
    c2.metric("📐 Cintura",     f"{atual['cintura_ewma']:.1f} cm",   f"{d_cintura:+.1f} cm")
    c3.metric("🧬 Gordura Weltman", f"{atual['%G_weltman']:.1f} %")
    c4.metric("💪 Massa Magra",  f"{atual['massa_magra']:.1f} kg")

    # Gráfico de peso com meta visível
    fig_peso = go.Figure()
    fig_peso.add_trace(go.Scatter(
        x=df_merged['data'], y=df_merged['peso_ewma'],
        name="Peso EWMA", line=dict(color='#ef4444', width=3),
        fill='tozeroy', fillcolor='rgba(239,68,68,0.05)'
    ))
    if not df_peso.empty:
        fig_peso.add_trace(go.Scatter(
            x=df_peso['data'], y=df_peso['peso_kg'],
            name="Peso Bruto", mode='markers',
            marker=dict(color='#fca5a5', size=5, opacity=0.6)
        ))
    # Linha de meta
    fig_peso.add_hline(
        y=meta_peso_alvo,
        line_dash="dash", line_color="#10b981", line_width=2,
        annotation_text=f"🎯 Meta: {meta_peso_alvo:.0f} kg",
        annotation_position="top right",
        annotation_font_color="#10b981"
    )
    fig_peso.update_layout(
        title="Trajetória de Peso — Rumo à Meta",
        height=300, template="plotly_white",
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        margin=dict(l=10, r=10, t=40, b=10),
        yaxis_title="kg"
    )
    st.plotly_chart(fig_peso, use_container_width=True)

    # Cintura + Massa Magra lado a lado
    col_g1, col_g2 = st.columns(2)
    with col_g1:
        fig_cin = go.Figure()
        fig_cin.add_trace(go.Scatter(
            x=df_merged['data'], y=df_merged['cintura_ewma'],
            name="Cintura EWMA", line=dict(color='#10b981', width=3)
        ))
        fig_cin.update_layout(
            title="Evolução da Cintura (cm)",
            height=230, template="plotly_white", showlegend=False,
            margin=dict(l=10, r=10, t=40, b=10)
        )
        st.plotly_chart(fig_cin, use_container_width=True)

    with col_g2:
        fig_mm = go.Figure()
        fig_mm.add_trace(go.Scatter(
            x=df_merged['data'], y=df_merged['massa_magra'],
            name="Massa Magra", line=dict(color='#6366f1', width=3),
            fill='tozeroy', fillcolor='rgba(99,102,241,0.06)'
        ))
        fig_mm.update_layout(
            title="Massa Magra Preservada (kg)",
            height=230, template="plotly_white", showlegend=False,
            margin=dict(l=10, r=10, t=40, b=10)
        )
        st.plotly_chart(fig_mm, use_container_width=True)

# ── PRESSÃO ARTERIAL ──────────────────────────────────────────────────────────
if bp_valida:
    st.markdown('<div class="section-header">❤️ Pressão Arterial</div>', unsafe_allow_html=True)

    df_bp_plot = df_bp.copy()
    df_bp_plot['data_dt'] = pd.to_datetime(df_bp_plot['measurement_time'])
    df_bp_plot = df_bp_plot.sort_values('data_dt')

    ultima_bp = df_bp_plot.iloc[-1]
    sis = int(ultima_bp['systolic'])
    dia = int(ultima_bp['diastolic'])

    if sis < 120 and dia < 80:
        bp_status, bp_class = "ÓTIMA", "badge-green"
        bp_msg = "Pressão dentro da faixa ideal. Continue assim."
        bp_box_class = "insight-box"
    elif sis < 130:
        bp_status, bp_class = "ELEVADA", "badge-yellow"
        bp_msg = "Pressão levemente acima do ideal. Hidratação e redução de sódio ajudam."
        bp_box_class = "insight-box warn"
    else:
        bp_status, bp_class = "ATENÇÃO", "badge-red"
        bp_msg = "Pressão elevada. Monitore de perto e considere consultar seu médico."
        bp_box_class = "insight-box alert"

    col_bp1, col_bp2, col_bp3 = st.columns([1, 1, 3])
    col_bp1.metric("🔴 Sistólica", f"{sis} mmHg")
    col_bp2.metric("🔵 Diastólica", f"{dia} mmHg")
    with col_bp3:
        st.markdown(f'<div class="{bp_box_class}">💡 {bp_msg}</div>', unsafe_allow_html=True)

    fig_bp = go.Figure()
    fig_bp.add_trace(go.Scatter(
        x=df_bp_plot['data_dt'], y=df_bp_plot['systolic'],
        name="Sistólica", line=dict(color='#ef4444', width=2)
    ))
    fig_bp.add_trace(go.Scatter(
        x=df_bp_plot['data_dt'], y=df_bp_plot['diastolic'],
        name="Diastólica", line=dict(color='#3b82f6', width=2)
    ))
    fig_bp.add_hline(y=120, line_dash="dot", line_color="#10b981", line_width=1,
                     annotation_text="Referência Sistólica", annotation_font_color="#10b981")
    fig_bp.add_hline(y=80,  line_dash="dot", line_color="#6366f1", line_width=1,
                     annotation_text="Referência Diastólica", annotation_position="bottom right",
                     annotation_font_color="#6366f1")
    fig_bp.update_layout(
        title="Histórico de Pressão Arterial",
        height=260, template="plotly_white",
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        margin=dict(l=10, r=10, t=40, b=10)
    )
    st.plotly_chart(fig_bp, use_container_width=True)

# ── ATIVIDADE FÍSICA / CICLISMO ───────────────────────────────────────────────
st.markdown('<div class="section-header">🚴 Atividade Física na Jornada</div>', unsafe_allow_html=True)

col_bike1, col_bike2, col_bike3, col_bike4 = st.columns(4)
col_bike1.metric("🏋️ Sessões Totais",     f"{total_sessoes}")
col_bike2.metric("⏱️ Total em Movimento", f"{total_min_treino} min")
col_bike3.metric("🔥 Calorias Queimadas", f"{total_cal_treino} kcal")
col_bike4.metric("📊 Duração Média",      f"{media_min_sessao:.0f} min/sessão")

if not df_treino.empty:
    df_treino_plot = df_treino.copy()
    df_treino_plot['data_dt'] = pd.to_datetime(df_treino_plot['data'])
    df_treino_plot = df_treino_plot.sort_values('data_dt')

    # Volume semanal acumulado
    df_treino_plot['semana'] = df_treino_plot['data_dt'].dt.to_period('W').dt.start_time
    df_semanal = df_treino_plot.groupby('semana')[['t_min', 't_cal_out']].sum().reset_index()

    fig_treino = make_subplots(
        rows=1, cols=2,
        subplot_titles=("Duração por Sessão (min)", "Volume Semanal de Atividade (min)")
    )
    fig_treino.add_trace(go.Bar(
        x=df_treino_plot['data_dt'], y=df_treino_plot['t_min'],
        name="Duração", marker_color='#10b981', opacity=0.8
    ), row=1, col=1)
    fig_treino.add_trace(go.Bar(
        x=df_semanal['semana'], y=df_semanal['t_min'],
        name="Volume Semana", marker_color='#6366f1', opacity=0.85
    ), row=1, col=2)
    fig_treino.update_layout(
        height=280, template="plotly_white", showlegend=False,
        margin=dict(l=10, r=10, t=40, b=10)
    )
    st.plotly_chart(fig_treino, use_container_width=True)

    # Streak e tendência
    df_treino_plot['data_date'] = df_treino_plot['data_dt'].dt.date
    datas_treino = sorted(df_treino_plot['data_date'].unique())
    streak = 0
    for i in range(len(datas_treino) - 1, -1, -1):
        expected = hoje - timedelta(days=(len(datas_treino) - 1 - i))
        if datas_treino[i] == expected:
            streak += 1
        else:
            break

    if streak > 0:
        st.markdown(f'<div class="insight-box">🔥 <strong>Sequência ativa: {streak} dia(s) consecutivo(s) de treino!</strong> Continue o embalo.</div>', unsafe_allow_html=True)

# ── NUTRIÇÃO DE HOJE ──────────────────────────────────────────────────────────
st.markdown('<div class="section-header">🍽️ Cota Energética — Hoje</div>', unsafe_allow_html=True)

k_hoje = float(df_hoje_c.iloc[0]['k']) if not df_hoje_c.empty and pd.notnull(df_hoje_c.iloc[0]['k']) else 0
p_hoje = float(df_hoje_c.iloc[0]['p']) if not df_hoje_c.empty and pd.notnull(df_hoje_c.iloc[0]['p']) else 0
c_hoje = float(df_hoje_c.iloc[0]['c']) if not df_hoje_c.empty and pd.notnull(df_hoje_c.iloc[0]['c']) else 0
g_hoje = float(df_hoje_c.iloc[0]['g']) if not df_hoje_c.empty and pd.notnull(df_hoje_c.iloc[0]['g']) else 0
rest_k = meta_kcal - k_hoje

c_nut_l, c_nut_r = st.columns([1, 2])
with c_nut_l:
    st.metric(
        "🔥 Saldo Calórico Restante",
        f"{int(rest_k)} kcal",
        delta=f"Cota: {meta_kcal} kcal",
        delta_color="normal" if rest_k >= 0 else "inverse"
    )

with c_nut_r:
    m_p_status = "🟢 ALVO ATINGIDO"   if p_hoje >= meta_prot          else f"🟡 FALTA {int(meta_prot - p_hoje)}g"
    m_c_status = "🔴 LIMITE CRÍTICO"  if c_hoje >= meta_carb - 15     else "🟢 DENTRO DO BUDGET"
    m_g_status = "🔴 LIMITE CRÍTICO"  if g_hoje >= meta_gord - 10     else "🟢 DENTRO DO BUDGET"
    st.markdown(f"🥩 **Proteína:** {int(p_hoje)}g / {meta_prot}g ➔ **{m_p_status}**")
    st.markdown(f"🍞 **Carboidratos:** {int(c_hoje)}g / {meta_carb}g ➔ **{m_c_status}**")
    st.markdown(f"🥑 **Gorduras:** {int(g_hoje)}g / {meta_gord}g ➔ **{m_g_status}**")

# Déficit histórico
if not df_merged.empty:
    with st.expander("📊 Ver histórico de déficit calórico"):
        fig_def = go.Figure()
        fig_def.add_trace(go.Bar(
            x=df_merged['data'], y=df_merged['deficit_real'],
            name="Déficit Diário",
            marker_color=df_merged['deficit_real'].apply(lambda x: '#10b981' if x >= 0 else '#ef4444')
        ))
        fig_def.add_hline(y=0, line_color='#1e293b', line_width=1)
        fig_def.update_layout(
            title="Déficit Calórico Diário (Verde = Queima | Vermelho = Superávit)",
            height=250, template="plotly_white",
            margin=dict(l=10, r=10, t=40, b=10)
        )
        st.plotly_chart(fig_def, use_container_width=True)

# ── P-CONTROLLER ──────────────────────────────────────────────────────────────
st.markdown('<div class="section-header">🤖 Orientação de Trajetória (P-Controller Adaptativo)</div>', unsafe_allow_html=True)

if not df_peso.empty and not df_merged.empty and len(df_merged) >= 7 and atual is not None:
    passado_7d   = df_merged.iloc[-8] if len(df_merged) >= 8 else df_merged.iloc[0]
    peso_baseline = passado_7d['peso_ewma']
    ritmo_semanal = float(p.get('ritmo_semanal', 0.8))
    sp_hoje       = peso_baseline - ritmo_semanal
    pv_hoje       = atual['peso_ewma']
    erro_kg       = pv_hoje - sp_hoje

    col_p1, col_p2, col_p3 = st.columns(3)
    col_p1.metric("🎯 Rampa da Semana", f"{sp_hoje:.2f} kg", f"Base: {peso_baseline:.2f} kg", delta_color="off")
    col_p2.metric("📊 Inércia Real (EWMA)", f"{pv_hoje:.2f} kg")

    if erro_kg <= 0.05 and erro_kg >= -0.6:
        col_p3.metric("🏆 Status", f"{erro_kg*1000:+.0f} g", delta_color="normal")
        st.markdown(f'<div class="insight-box">💡 <strong>Voo de Cruzeiro:</strong> Você está no ritmo certo. Manter cota em <strong>{meta_kcal} kcal</strong>.</div>', unsafe_allow_html=True)
    elif erro_kg < -0.6:
        col_p3.metric("🔥 Aceleração", f"{erro_kg*1000:+.0f} g", delta_color="normal")
        st.markdown(f'<div class="insight-box">💡 <strong>Over-performance:</strong> {abs(erro_kg):.2f} kg à frente da meta. Mantenha os <strong>{meta_kcal} kcal</strong> e garanta a proteína para proteger a massa magra.</div>', unsafe_allow_html=True)
    else:
        col_p3.metric("⚠️ Desvio", f"{erro_kg*1000:+.0f} g", delta_color="inverse")
        ajuste      = -(erro_kg * 500)
        kcal_recalc = max(1200, min(meta_kcal + ajuste, atual['get_total']))
        st.markdown(f'<div class="insight-box warn">💡 <strong>P-Controller Ativo:</strong> Inércia levemente atrasada. Teto sugerido para as próximas 24h: <strong>{int(kcal_recalc)} kcal</strong>.</div>', unsafe_allow_html=True)
else:
    st.info("⏳ Aguardando 7 dias de dados para acionar o P-Controller.")

# ── ELÁSTICNET — GÊMEO DIGITAL ────────────────────────────────────────────────
st.markdown('<div class="section-header">🧠 Gêmeo Digital Metabólico (ElasticNet ML)</div>', unsafe_allow_html=True)

try:
    from sklearn.linear_model import ElasticNet
    from sklearn.preprocessing import StandardScaler
    from sklearn.metrics import r2_score
    from sklearn.model_selection import train_test_split

    if not df_merged.empty and len(df_merged) > 20:
        df_ml = df_merged.copy()
        df_ml['delta_peso']         = df_ml['peso_ewma'].diff()
        df_ml['delta_cintura']      = df_ml['cintura_ewma'].diff()
        df_ml['retencao_estimada']  = df_ml['delta_peso'] - (df_ml['delta_cintura'].fillna(0) * 0.5)
        df_ml['carb_3d_acum']       = df_ml['tcarb'].rolling(3).sum().shift(1)
        df_ml['deficit_7d_acum']    = df_ml['deficit_real'].rolling(7).sum().shift(1)
        df_ml['passos_3d_med']      = df_ml['t_passos_trabalho'].rolling(3).mean().shift(1)
        df_ml['dia_semana']         = pd.to_datetime(df_ml['data']).dt.dayofweek

        lags = [1, 3, 5]
        features_base = ['tcarb', 'tprot', 'tgord', 'tagua', 't_passos_trabalho', 'deficit_real']
        for col in features_base:
            for lag in lags:
                df_ml[f'{col}_lag{lag}'] = df_ml[col].shift(lag)

        col_ctrl1, col_ctrl2 = st.columns([1, 2])
        with col_ctrl1:
            target_view = st.selectbox(
                "🎯 Lente de Observação (Alvo):",
                ["Retenção Hídrica/Inflamação", "Cintura (Gordura Visceral)", "Peso Bruto (Misto)"]
            )
        target_map = {
            "Retenção Hídrica/Inflamação": "retencao_estimada",
            "Cintura (Gordura Visceral)":  "delta_cintura",
            "Peso Bruto (Misto)":          "delta_peso"
        }
        target_col = target_map[target_view]
        features_ml = [c for c in df_ml.columns if '_lag' in c or '_acum' in c or '_med' in c or c == 'dia_semana']
        df_ml_clean = df_ml.dropna(subset=[target_col] + features_ml)

        if len(df_ml_clean) > 25:
            X = df_ml_clean[features_ml]
            y = df_ml_clean[target_col]

            X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, shuffle=False)
            scaler = StandardScaler()
            X_train_sc = scaler.fit_transform(X_train)
            X_test_sc  = scaler.transform(X_test)

            model = ElasticNet(alpha=0.01, l1_ratio=0.5, max_iter=2000)
            model.fit(X_train_sc, y_train)
            r2 = r2_score(y_test, model.predict(X_test_sc))

            with col_ctrl2:
                st.metric(
                    "🧠 Capacidade Explicativa Real (R² out-of-sample)",
                    f"{r2:.2%}",
                    delta="Sinal vs Ruído",
                    delta_color="normal" if r2 > 0.15 else "inverse"
                )
                if r2 < 0.1:
                    st.caption("⚠️ R² baixo: o modelo não sustentou a previsão no futuro. Continue alimentando o tracker.")

            # Coeficientes na base completa (só para visualização)
            X_full_sc = scaler.fit_transform(X)
            model_viz = ElasticNet(alpha=0.01, l1_ratio=0.5, max_iter=2000)
            model_viz.fit(X_full_sc, y)

            coefs = pd.DataFrame({'Variavel': features_ml, 'Impacto': model_viz.coef_})
            coefs = coefs[coefs['Impacto'].abs() > 0.001].sort_values('Impacto')

            if not coefs.empty:
                rename_map = {
                    'tcarb': 'Carbo', 'tprot': 'Proteína', 'tgord': 'Gordura',
                    'tagua': 'Água', 't_passos_trabalho': 'Passos',
                    'deficit_real': 'Déficit', 'dia_semana': 'Dia da Semana'
                }
                def beautify_name(name):
                    for k, v in rename_map.items():
                        name = name.replace(k, v)
                    name = name.replace('_lag1', ' (Ontem)').replace('_lag3', ' (−3 Dias)').replace('_lag5', ' (−5 Dias)')
                    name = name.replace('_3d_acum', ' (Acum 3D)').replace('_7d_acum', ' (Acum 7D)').replace('_3d_med', ' (Média 3D)')
                    return name

                coefs['Variavel_Limpa'] = coefs['Variavel'].apply(beautify_name)
                coefs['Cor'] = coefs['Impacto'].apply(lambda x: '#ef4444' if x > 0 else '#10b981')

                fig_ml = go.Figure(go.Bar(
                    x=coefs['Impacto'], y=coefs['Variavel_Limpa'],
                    orientation='h', marker_color=coefs['Cor'],
                    text=coefs['Impacto'].apply(lambda x: f"{x:+.3f}"),
                    textposition='auto'
                ))
                fig_ml.add_vline(x=0, line_width=2, line_color="#1e293b")
                fig_ml.update_layout(
                    title="Mapa de Influência Metabólica (Verde = Reduz | Vermelho = Aumenta)",
                    height=max(300, len(coefs) * 35),
                    template="plotly_white",
                    margin=dict(l=10, r=10, t=40, b=10),
                    yaxis=dict(autorange="reversed")
                )
                st.plotly_chart(fig_ml, use_container_width=True)
            else:
                st.info("🧠 Nenhum padrão causal forte encontrado ainda. Continue registrando.")

            st.caption(f"Amostra limpa: **{len(df_ml_clean)} dias** (Treino: {len(X_train)} / Validação: {len(X_test)})")
        else:
            dias_faltam = 25 - len(df_ml_clean)
            st.progress(len(df_ml_clean) / 25, text=f"🧠 Coletando dados: {len(df_ml_clean)}/25 dias necessários para o modelo (faltam {dias_faltam})")

    else:
        st.info("⏳ Ainda coletando dados para o Gêmeo Digital. Continue registrando diariamente.")

except ImportError:
    st.error("🚨 Adicione `scikit-learn` ao ambiente para rodar o ElasticNet.")
