import streamlit as st
import pandas as pd
from sqlalchemy import create_engine, text
from datetime import datetime, timedelta
import pytz
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import numpy as np

# ============================================================================
# 1. CONFIGURAÇÃO VISUAL (TEMA INDUSTRIAL)
# ============================================================================
st.set_page_config(page_title="BioControl System", page_icon="🎛️", layout="wide", initial_sidebar_state="collapsed")

# CSS para dar um ar mais "Engenharia/Dashboard"
st.markdown("""
    <style>
    div[data-testid="stMetric"] { background-color: #1E1E1E; border: 1px solid #444; border-radius: 5px; color: #EEE; }
    h1, h2, h3 { font-family: 'Consolas', 'Courier New', monospace; color: #00FF00; }
    .stAlert { background-color: #222; border: 1px solid #555; }
    </style>
    """, unsafe_allow_html=True)

# ============================================================================
# 2. CONEXÃO E CACHE
# ============================================================================
@st.cache_resource(ttl=600)
def get_engine():
    db_url = st.secrets["DATABASE_URL"]
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)
    return create_engine(db_url, pool_pre_ping=True)

def run_query(query, params=None, is_select=True):
    engine = get_engine()
    try:
        with engine.connect() as conn:
            if is_select:
                df = pd.read_sql(text(query), conn, params=params)
                for col in ['data', 'log_date', 'measurement_time']:
                    if col in df.columns:
                        try: df[col] = pd.to_datetime(df[col])
                        except: pass
                return df
            return pd.DataFrame()
    except Exception as e:
        st.error(f"Erro DB: {e}")
        return pd.DataFrame()

# TRAVA DE SEGURANÇA
if st.query_params.get("token") != st.secrets.get("DASH_ACCESS_TOKEN"):
    st.error("🔒 SYSTEM LOCKED. AUTHORIZATION REQUIRED."); st.stop()

# ============================================================================
# 3. EXTRAÇÃO DE DADOS (ETL)
# ============================================================================
hoje = datetime.now(pytz.timezone('America/Sao_Paulo')).date()
DATA_INICIO = pd.to_datetime("2025-12-30").date()

# Queries
df_perfil = run_query("SELECT * FROM public.perfil WHERE id = 1")
df_peso = run_query("SELECT * FROM public.peso ORDER BY data ASC")
df_hist = run_query("SELECT data, SUM(kcal) as tkcal FROM public.consumo WHERE data >= :d GROUP BY data ORDER BY data ASC", {"d": DATA_INICIO})

# Setup Perfil
if not df_perfil.empty: p = df_perfil.iloc[0]
else: p = {'meta_kcal': 1650, 'meta_peso_alvo': 90.0, 'ritmo_semanal': 0.8}

# Dados Atuais
peso_atual = float(df_peso.iloc[-1]['peso_kg']) if not df_peso.empty else 0.0
meta_final = float(p['meta_peso_alvo'])
ritmo_semanal = float(p['ritmo_semanal'])

# --- CÁLCULO DO SETPOINT DINÂMICO (A LINHA IDEAL) ---
# Criamos uma linha ideal desde o dia 1 até hoje
df_peso['data_dt'] = pd.to_datetime(df_peso['data']).dt.date
data_start = df_peso.iloc[0]['data_dt']
peso_start = df_peso.iloc[0]['peso_kg']
days_passed = (hoje - data_start).days

# O Setpoint hoje é onde você DEVERIA estar se tivesse perdido 0.8kg/semana perfeitamente
sp_hoje = peso_start - ((ritmo_semanal / 7) * days_passed)
erro_atual = sp_hoje - peso_atual # Se positivo, estou leve. Se negativo, estou pesado.

# ============================================================================
# 4. INTERFACE DE CONTROLE (O NOVO DASHBOARD)
# ============================================================================

st.title(f"SYSTEM STATUS: {'ONLINE' if erro_atual > -2 else 'WARNING'}")
st.caption(f"Plant: Human Body (Leonardo) | Controller: External Cognition | Date: {hoje}")

# --- ABA 1: MALHA DE CONTROLE (O CORAÇÃO DA AULA) ---
tab_ctrl, tab_data = st.tabs(["🎛️ Malha de Controle (PID View)", "📊 Dados Brutos"])

with tab_ctrl:
    
    # --- BLOCO 1: VARIÁVEIS DE ESTADO ---
    st.markdown("### 1. Estado do Sistema (System State)")
    c1, c2, c3, c4 = st.columns(4)
    
    with c1:
        st.metric(
            label="🎯 Setpoint (SP)",
            value=f"{sp_hoje:.2f} kg",
            help="Onde você DEVERIA estar hoje seguindo a meta linear."
        )
        
    with c2:
        st.metric(
            label="⚖️ Process Variable (PV)",
            value=f"{peso_atual:.2f} kg",
            delta=f"{peso_atual - float(df_peso.iloc[-2]['peso_kg']):.2f} kg (desde ontem)",
            delta_color="inverse",
            help="Leitura real do sensor (Balança)."
        )

    with c3:
        # O ERRO É CRUCIAL. Se negativo, precisa atuar.
        # Erro = SP - PV. 
        # Ex: Meta 90, Real 92. Erro = -2. (Estamos 2kg acima do ideal).
        erro_calc = sp_hoje - peso_atual
        lbl_erro = "✅ Estável" if abs(erro_calc) < 0.5 else ("⚠️ Desvio Crítico" if erro_calc < -1 else "Avançado")
        st.metric(
            label="📉 Erro (SP - PV)",
            value=f"{erro_calc:.2f} kg",
            delta=lbl_erro,
            delta_color="normal" if erro_calc >= 0 else "inverse",
            help="Diferença entre a Meta e o Real. O objetivo do controlador é ZERAR este número."
        )

    with c4:
        # AÇÃO DE CONTROLE SUGERIDA (Lógica Proporcional Simples)
        # Se Erro < 0 (Estou gordo), Reduz Kcal. Se Erro > 0 (Estou magro), Mantém.
        kp = 200 # Ganho Proporcional (Arbitrário: 200kcal para cada kg de erro)
        acao_p = kp * erro_calc
        meta_ajustada = float(p['meta_kcal']) + acao_p
        # Saturação (Limites de segurança)
        meta_ajustada = max(1200, min(2500, meta_ajustada))
        
        st.metric(
            label="🔥 Variável Manipulada (MV)",
            value=f"{int(meta_ajustada)} kcal",
            delta=f"{int(acao_p)} kcal (Correção P)",
            help="Sugestão de Ingestão para hoje baseada no Erro atual (Lógica P)."
        )

    st.divider()

    # --- BLOCO 2: GRÁFICO DE CONTROLE (SP vs PV) ---
    st.markdown("### 2. Análise de Rastreamento (Tracking Analysis)")
    
    if not df_peso.empty:
        # Criar dados projetados (Setpoint Line)
        dates = pd.date_range(start=data_start, end=hoje)
        sp_line = [peso_start - ((ritmo_semanal / 7) * (d.date() - data_start).days) for d in dates]
        
        # Filtrar dados reais para o mesmo período
        df_plot = df_peso[df_peso['data_dt'] <= hoje].set_index('data_dt').reindex(dates.date).reset_index()
        
        fig = go.Figure()
        
        # Linha do Setpoint (Meta)
        fig.add_trace(go.Scatter(
            x=dates, y=sp_line,
            name='Setpoint (Meta Linear)',
            mode='lines',
            line=dict(color='green', dash='dash')
        ))
        
        # Linha da PV (Real)
        fig.add_trace(go.Scatter(
            x=dates, y=df_plot['peso_kg'],
            name='PV (Peso Real)',
            mode='lines+markers',
            line=dict(color='red', width=3)
        ))
        
        # Preencher a área do ERRO (Integral visual)
        fig.add_trace(go.Scatter(
            x=dates, y=sp_line,
            fill=None, mode='lines', line_color='green', showlegend=False
        ))
        fig.add_trace(go.Scatter(
            x=dates, y=df_plot['peso_kg'],
            fill='tonexty', # Preenche até a linha do SP
            name='Erro (Integral)',
            mode='none',
            fillcolor='rgba(255, 0, 0, 0.1)'
        ))

        fig.update_layout(
            template="plotly_dark",
            title="Resposta do Sistema: PV rastreando SP",
            xaxis_title="Tempo",
            yaxis_title="Peso (kg)",
            height=400,
            hovermode="x unified"
        )
        st.plotly_chart(fig, use_container_width=True)

    # --- BLOCO 3: ATUAÇÃO DO CONTROLADOR (CALORIAS) ---
    c_act1, c_act2 = st.columns(2)
    
    with c_act1:
        st.markdown("### 3. Sinal de Controle (Histórico MV)")
        if not df_hist.empty:
            df_hist['MV_Target'] = float(p['meta_kcal'])
            
            fig_mv = go.Figure()
            fig_mv.add_trace(go.Bar(
                x=df_hist['data'], y=df_hist['tkcal'],
                name='MV Real (Ingestão)',
                marker_color='#3498DB'
            ))
            fig_mv.add_trace(go.Scatter(
                x=df_hist['data'], y=df_hist['MV_Target'],
                name='MV Alvo',
                mode='lines',
                line=dict(color='orange', dash='dot')
            ))
            fig_mv.update_layout(template="plotly_dark", height=300, title="Atuação vs Meta")
            st.plotly_chart(fig_mv, use_container_width=True)

    with c_act2:
        st.markdown("### 4. Diagnóstico de Distúrbios")
        st.info(f"""
        **Análise de Estabilidade:**
        * **Offset (Erro Atual):** {erro_calc:.2f} kg.
        * **Ação do Controlador:** {'Aumentar Restrição' if erro_calc < 0 else 'Manter'}
        * **Perturbação Estimada:** Baixa
        
        **Conceitos Aplicados:**
        * O corpo humano possui **Grande Inércia** (Peso não muda no mesmo dia que se come).
        * A **Balança** atua como sensor com **Ruído** (Retenção hídrica).
        * A **Dieta** é a única forma de atuar na planta (MV).
        """)

# --- ABA 2: VISÃO ANTIGA (DADOS) ---
with tab_data:
    st.dataframe(df_peso)
