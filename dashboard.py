import os
import streamlit as st
import pandas as pd
import numpy as np
from sqlalchemy import create_engine, text
from datetime import datetime, timedelta
import pytz
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import statsmodels.api as sm
from statsmodels.formula.api import ols
from sklearn.linear_model import LinearRegression
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error
import itertools
import random

# ============================================================================
# 1. CONFIGURAÇÃO VISUAL E ESTADO DA SESSÃO (PERSISTÊNCIA DOS SLIDERS)
# ============================================================================
st.set_page_config(page_title="Leo's Nutrition Control", page_icon="🦁", layout="wide", initial_sidebar_state="collapsed")

# Inicialização do Session State para que o Algoritmo Genético possa "girar" os sliders
defaults = {
    'win_peso': 3, 'win_jej': 1, 'win_prot': 3, 'win_carb': 2, 
    'win_gord': 1, 'win_passos': 2, 'win_agua': 2, 'win_int': 1, 
    'win_bristol': 1, 'win_sono_h': 1, 'win_sono_q': 1
}
for key, val in defaults.items():
    if key not in st.session_state:
        st.session_state[key] = val

st.markdown("""
    <style>
    #MainMenu {visibility: hidden;} footer {visibility: hidden;} header {visibility: hidden;}
    div[data-testid="stMetric"] { background-color: #f0f2f6; padding: 15px; border-radius: 12px; border: 1px solid #e0e0e0; box-shadow: 2px 2px 5px rgba(0,0,0,0.05); }
    @media (prefers-color-scheme: dark) { div[data-testid="stMetric"] { background-color: #262730; border: 1px solid #464b5c; } }
    h1, h2, h3 { font-family: 'Helvetica', sans-serif; font-weight: 700; }
    .control-text { font-family: 'Consolas', monospace; color: #4CAF50; }
    </style>
    """, unsafe_allow_html=True)

# ============================================================================
# 2. CONEXÃO BLINDADA
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
        if is_select:
            with engine.connect() as conn:
                df = pd.read_sql(text(query), conn, params=params)
                for col in ['data', 'log_date', 'measurement_time']:
                    if col in df.columns:
                        try: df[col] = pd.to_datetime(df[col])
                        except: pass
                return df
    except Exception as e:
        st.error(f"🚨 Alerta de Banco de Dados: {e}")
        return pd.DataFrame()

if st.query_params.get("token") != st.secrets.get("DASH_ACCESS_TOKEN"):
    st.error("🔒 Acesso Restrito. Token inválido."); st.stop()

# ============================================================================
# 3. ETL (EXTRAÇÃO E TRATAMENTO - V10)
# ============================================================================
hoje = datetime.now(pytz.timezone('America/Sao_Paulo')).date()
DATA_INICIO = pd.to_datetime("2025-12-30").date()

df_perfil = run_query("SELECT * FROM public.perfil WHERE id = 1")
df_peso = run_query("SELECT * FROM public.peso ORDER BY data ASC")
df_medidas = run_query("SELECT * FROM public.body_measurements ORDER BY log_date ASC")
df_bp = run_query("SELECT * FROM public.blood_pressure ORDER BY measurement_time ASC")

df_hist = run_query("""
    SELECT data, SUM(kcal) as tkcal, SUM(proteina) as tprot, SUM(carbo) as tcarb, 
           SUM(gordura) as tgord, SUM(quantidade) as tqtd,
           MIN(data_hora) as primeira_refeicao_dt, 
           MAX(data_hora) as ultima_refeicao_dt
    FROM public.consumo WHERE data >= :d GROUP BY data ORDER BY data ASC
""", {"d": DATA_INICIO})

df_treino = run_query("""
    SELECT data, SUM(duracao_min) as t_min, SUM(passos_trabalho) as t_passos_trabalho, SUM(calorias) as t_cal_out 
    FROM public.exercicios WHERE data >= :d GROUP BY data ORDER BY data ASC
""", {"d": DATA_INICIO})

df_hidra = run_query("SELECT data, SUM(agua_ml) as tagua FROM public.hidratacao WHERE data >= :d GROUP BY data ORDER BY data ASC", {"d": DATA_INICIO})
df_evac = run_query("SELECT data, SUM(vezes) as tintestino, MAX(bristol) as tbristol FROM public.evacuacao WHERE data >= :d GROUP BY data ORDER BY data ASC", {"d": DATA_INICIO})
df_sono = run_query("SELECT data, MAX(horas) as sono_h, MAX(qualidade) as sono_q FROM public.sono WHERE data >= :d GROUP BY data ORDER BY data ASC", {"d": DATA_INICIO})

df_hoje_comida = run_query("SELECT * FROM public.consumo WHERE data = :d", {"d": hoje})
df_hoje_treino = run_query("SELECT * FROM public.exercicios WHERE data = :d", {"d": hoje})

if not df_perfil.empty:
    p = df_perfil.iloc[0]
else:
    p = {'meta_kcal': 1650, 'meta_proteina': 130, 'meta_carbo': 150, 'meta_gordura': 59, 
         'meta_peso_alvo': 120.0, 'ritmo_semanal': 0.8, 'idade': 41, 'altura_cm': 178, 'fator_atividade': 1.2}

fator_atividade = float(p.get('fator_atividade') or 1.2)
peso_atual = float(df_peso.iloc[-1]['peso_kg']) if not df_peso.empty else 140.0

df_merged = pd.DataFrame()

if not df_hist.empty and not df_peso.empty:
    df_hist['data_dt'] = pd.to_datetime(df_hist['data']).dt.date
    df_peso['data_dt'] = pd.to_datetime(df_peso['data']).dt.date
    
    df_peso_unico = df_peso.drop_duplicates(subset=['data_dt'], keep='last')
    df_merged = pd.merge(df_hist, df_peso_unico[['data_dt', 'peso_kg']], on='data_dt', how='left').ffill()
    
    if df_merged['peso_kg'].isnull().any():
         df_merged['peso_kg'] = df_merged['peso_kg'].bfill().fillna(peso_atual)

    if not df_treino.empty:
        df_treino['data_dt'] = pd.to_datetime(df_treino['data']).dt.date
        df_treino_agg = df_treino.groupby('data_dt')[['t_min', 't_passos_trabalho', 't_cal_out']].sum().reset_index()
        df_merged = pd.merge(df_merged, df_treino_agg, on='data_dt', how='left')
        df_merged[['t_min', 't_passos_trabalho', 't_cal_out']] = df_merged[['t_min', 't_passos_trabalho', 't_cal_out']].fillna(0)
    else:
        df_merged['t_min'] = 0; df_merged['t_passos_trabalho'] = 0; df_merged['t_cal_out'] = 0
        
    if not df_hidra.empty:
        df_hidra['data_dt'] = pd.to_datetime(df_hidra['data']).dt.date
        df_hidra_agg = df_hidra.groupby('data_dt')[['tagua']].sum().reset_index()
        df_merged = pd.merge(df_merged, df_hidra_agg, on='data_dt', how='left')
        df_merged['tagua'] = df_merged['tagua'].fillna(0)
    else:
        df_merged['tagua'] = 0
        
    if not df_evac.empty:
        df_evac['data_dt'] = pd.to_datetime(df_evac['data']).dt.date
        df_evac_agg = df_evac.groupby('data_dt').agg({'tintestino': 'sum', 'tbristol': 'max'}).reset_index()
        df_merged = pd.merge(df_merged, df_evac_agg, on='data_dt', how='left')
        
    df_merged['tintestino'] = df_merged['tintestino'].fillna(0)
    df_merged['tbristol'] = df_merged['tbristol'].fillna(0)

    if not df_sono.empty:
        df_sono['data_dt'] = pd.to_datetime(df_sono['data']).dt.date
        df_sono_agg = df_sono.groupby('data_dt')[['sono_h', 'sono_q']].max().reset_index()
        df_merged = pd.merge(df_merged, df_sono_agg, on='data_dt', how='left')
        df_merged['sono_h'] = df_merged['sono_h'].fillna(7.0) 
        df_merged['sono_q'] = df_merged['sono_q'].fillna(3)
    else:
        df_merged['sono_h'] = 7.0; df_merged['sono_q'] = 3

    idade, altura = int(p.get('idade', 41)), int(p.get('altura_cm', 178))
    df_merged['get_basal'] = ((10 * df_merged['peso_kg']) + (6.25 * altura) - (5 * idade) + 5) * fator_atividade
    df_merged['get_total'] = df_merged['get_basal'] + df_merged['t_cal_out']
    df_merged['deficit_real'] = df_merged['get_total'] - df_merged['tkcal']

# ============================================================================
# 4. MOTOR PREDITIVO (EL FAROL) - DINÂMICO
# ============================================================================
def torneio_el_farol(df_modelo, features, target_col):
    X = df_modelo[features]
    y = df_modelo[target_col]
    
    if len(df_modelo) < 10:
        return None, None, None, None, None
        
    X_treino, X_teste = X[:-5], X[-5:]
    y_treino, y_teste = y[:-5], y[-5:]
    
    datas_teste = df_modelo['data_dt'].iloc[-5:] if 'data_dt' in df_modelo.columns else df_modelo.index[-5:]
    
    agente_lr = LinearRegression().fit(X_treino, y_treino)
    agente_rf = RandomForestRegressor(n_estimators=10, random_state=42).fit(X_treino, y_treino)
    
    preds_lr = agente_lr.predict(X_teste)
    preds_rf = agente_rf.predict(X_teste)
    
    erro_lr = mean_absolute_error(y_teste, preds_lr)
    erro_rf = mean_absolute_error(y_teste, preds_rf)
    
    vencedor = "Random Forest" if erro_rf < erro_lr else "Regressão Linear Múltipla"
    menor_erro = min(erro_rf, erro_lr)
    
    df_transparencia = pd.DataFrame({
        'Data': datas_teste,
        'Real (g)': y_teste.values * 1000,
        'Previsto LR (g)': preds_lr * 1000,
        'Previsto RF (g)': preds_rf * 1000
    })
    df_transparencia['Erro LR (g)'] = abs(df_transparencia['Real (g)'] - df_transparencia['Previsto LR (g)'])
    df_transparencia['Erro RF (g)'] = abs(df_transparencia['Real (g)'] - df_transparencia['Previsto RF (g)'])
    
    return vencedor, menor_erro, agente_lr, agente_rf, df_transparencia

# ============================================================================
# 5. ORGANIZAÇÃO EM ABAS
# ============================================================================
tab_qs, tab_dash = st.tabs(["🧠 Quantified Self (Engenharia Metabólica)", "🦁 Dashboard Original"])

with tab_qs:
    st.markdown("### 🧠 Laboratório de Termodinâmica & Turnos de Jejum")
    
    if not df_merged.empty and 'deficit_real' in df_merged.columns:
        df_qs = df_merged.copy()
        
        df_qs['peso_amanha'] = df_qs['peso_kg'].shift(-1)
        df_qs['delta_peso_kg'] = df_qs['peso_amanha'] - df_qs['peso_kg']
        
        df_qs['delta_esperado_kg'] = - (df_qs['deficit_real'] / 7700)
        df_qs['fator_desinflamacao'] = df_qs['delta_peso_kg'] - df_qs['delta_esperado_kg']
        
        def classificar_perda(fator):
            if pd.isna(fator): return 'Sem Dados'
            if fator < -0.1: return 'Água/Desinflamação (Azul)' 
            elif fator > 0.1: return 'Retenção/Glicogênio (Amarelo)' 
            else: return 'Perda de Gordura Pura (Vermelho)'
            
        def cor_fator(fator):
            if pd.isna(fator): return '#bdc3c7'
            if fator < -0.1: return '#3498DB' 
            elif fator > 0.1: return '#F1C40F' 
            else: return '#E74C3C' 
            
        df_qs['tipo_perda'] = df_qs['fator_desinflamacao'].apply(classificar_perda)
        df_qs['cor'] = df_qs['fator_desinflamacao'].apply(cor_fator)

        df_qs['primeira_refeicao_dt'] = pd.to_datetime(df_qs['primeira_refeicao_dt'])
        df_qs['ultima_refeicao_dt'] = pd.to_datetime(df_qs['ultima_refeicao_dt'])
        df_qs['ultima_ref_ontem'] = df_qs['ultima_refeicao_dt'].shift(1)
        df_qs['jejum_h'] = (df_qs['primeira_refeicao_dt'] - df_qs['ultima_ref_ontem']).dt.total_seconds() / 3600
        df_qs['jejum_h'] = df_qs['jejum_h'].apply(lambda x: x if 8 <= x <= 48 else np.nan)

        if not df_qs.dropna(subset=['delta_peso_kg']).empty:
            last_day = df_qs.dropna(subset=['delta_peso_kg']).iloc[-1]
            
            col1, col2, col3, col4, col5 = st.columns(5)
            col1.metric("⚖️ Variação Diária (Real)", f"{last_day['delta_peso_kg']*1000:.0f} g", help="Valores negativos indicam perda de peso na balança.")
            col2.metric("📐 Termodinâmica (Esperado)", f"{last_day['delta_esperado_kg']*1000:.0f} g", help="Gordura teórica queimada baseada no déficit.")
            col3.metric("💧 Fator Desinflamação", f"{last_day['fator_desinflamacao']*1000:.0f} g", help="Negativo = Eliminou água/Desinflamou. Positivo = Reteu líquido/glicogênio.")
            status_color = "🔴" if last_day['tipo_perda'] == 'Perda de Gordura Pura (Vermelho)' else "🔵" if "Desinflamação" in last_day['tipo_perda'] else "🟡"
            col4.markdown(f"**Qualidade da Variação:**<br> {status_color} {last_day['tipo_perda'].split(' (')[0]}", unsafe_allow_html=True)
            col5.metric("💤 Último Sono", f"{last_day.get('sono_h', 0):.1f}h", help=f"Qualidade: {last_day.get('sono_q', 0)}")

            st.markdown("---")

            # ============================================================================
            # BLOCO 1 E 2: GRÁFICOS
            # ============================================================================
            st.markdown("### 1️⃣ Visão Macro: Peso Absoluto e Combustão Calórica")
            c_macro1, c_macro2 = st.columns(2)

            with c_macro1:
                fig_peso_abs = go.Figure()
                fig_peso_abs.add_trace(go.Scatter(x=df_merged['data_dt'], y=df_merged['peso_kg'], mode='lines+markers', name='Peso Real (kg)', line=dict(color='#2980B9', width=4)))
                fig_peso_abs.update_layout(title="Evolução do Peso na Balança", height=500, template="plotly_white", yaxis_title="Peso (kg)", hovermode="x unified")
                st.plotly_chart(fig_peso_abs, use_container_width=True)

            with c_macro2:
                fig_cal = go.Figure()
                fig_cal.add_trace(go.Bar(x=df_merged['data_dt'], y=df_merged['tkcal'], name='Calorias Ingeridas', marker_color='#E74C3C', opacity=0.8))
                fig_cal.add_trace(go.Scatter(x=df_merged['data_dt'], y=df_merged['get_total'], mode='lines', name='Gasto Energético (TDEE)', line=dict(color='#27AE60', width=3, dash='dot')))
                fig_cal.update_layout(title="Déficit Calórico: Consumo vs Gasto Total", height=500, template="plotly_white", yaxis_title="Kcal", hovermode="x unified", legend=dict(orientation="h", y=1.1))
                st.plotly_chart(fig_cal, use_container_width=True)

            st.markdown("---")
            st.markdown("### 2️⃣ O Laboratório: Desinflamação e o Shift de Jejum")
            c_qs1, c_qs2 = st.columns([2, 1])

            with c_qs1:
                st.markdown("##### 🧬 Série Temporal: Água vs Gordura vs Retenção (Eixo Invertido)")
                fig_qs_time = go.Figure()
                fig_qs_time.add_trace(go.Bar(x=df_qs['data_dt'], y=df_qs['delta_peso_kg'], marker_color=df_qs['cor'], name='Delta Real na Balança', text=df_qs['tipo_perda'], hoverinfo='x+y+text'))
                fig_qs_time.add_trace(go.Scatter(x=df_qs['data_dt'], y=df_qs['delta_esperado_kg'], mode='lines', name='Delta Esperado (Teórico)', line=dict(color='#2ECC71', dash='dash', width=2)))
                fig_qs_time.update_layout(height=500, template="plotly_white", hovermode="x unified", yaxis_title="Variação de Peso (kg) - Perda é Negativo", legend=dict(orientation="h", y=1.1))
                fig_qs_time.add_hline(y=0, line_width=1, line_color="black")
                st.plotly_chart(fig_qs_time, use_container_width=True)

            with c_qs2:
                st.markdown("##### ⏳ O 'Shift': Jejum vs Delta de Peso")
                fig_shift = go.Figure()
                df_qs_trend = df_qs.dropna(subset=['jejum_h', 'delta_peso_kg'])
                fig_shift.add_trace(go.Scatter(x=df_qs_trend['jejum_h'], y=df_qs_trend['delta_peso_kg'], mode='markers', marker=dict(size=12, color=df_qs_trend['cor'], opacity=0.8, line=dict(width=1, color='black')), text=df_qs_trend['data_dt'], hoverinfo='text+x+y'))
                if len(df_qs_trend) > 2:
                    z = np.polyfit(df_qs_trend['jejum_h'], df_qs_trend['delta_peso_kg'], 1)
                    poly_func = np.poly1d(z)
                    x_trend = np.linspace(df_qs_trend['jejum_h'].min(), df_qs_trend['jejum_h'].max(), 100)
                    fig_shift.add_trace(go.Scatter(x=x_trend, y=poly_func(x_trend), mode='lines', name='Tendência', line=dict(color='black', dash='dot')))
                fig_shift.update_layout(height=500, template="plotly_white", xaxis_title="Horas de Jejum", yaxis_title="Variação de Peso Seguinte (kg)", showlegend=False)
                fig_shift.add_hline(y=0, line_width=1, line_dash="dash", line_color="gray")
                st.plotly_chart(fig_shift, use_container_width=True)

            st.markdown("---")

            # ============================================================================
            # BLOCO 3: ORÁCULO METABÓLICO INTERATIVO (DOE & REGRESSÃO MULTIVARIÁVEL)
            # ============================================================================
            
            if 'novo_dna_metabolico' in st.session_state:
                dna = st.session_state.pop('novo_dna_metabolico')
                st.session_state['win_peso'] = dna[0]
                st.session_state['win_jej'] = dna[1]
                st.session_state['win_prot'] = dna[2]
                st.session_state['win_carb'] = dna[3]
                st.session_state['win_gord'] = dna[4]
                st.session_state['win_passos'] = dna[5]
                st.session_state['win_agua'] = dna[6]
                st.session_state['win_int'] = dna[7]
                st.session_state['win_bristol'] = dna[8]
                st.session_state['win_sono_h'] = dna[9]
                st.session_state['win_sono_q'] = dna[9]

            st.markdown("### 3️⃣ Oráculo Metabólico Dinâmico (Sintonizador de Sinais)")
            
            st.markdown("**🎯 Variável Alvo (Filtro Anti-Ruído)**")
            win_peso = st.slider("⚖️ Filtro: Peso (Tendência da Balança)", 1, 7, key='win_peso')
            
            st.markdown("**⚙️ Variáveis Independentes (Atraso Fisiológico)**")
            col_f1, col_f2, col_f3, col_f4, col_f5 = st.columns(5)
            with col_f1: 
                win_jej = st.slider("⏳ Jejum", 1, 7, key='win_jej')
                win_agua = st.slider("💧 Água", 1, 7, key='win_agua')
            with col_f2: 
                win_prot = st.slider("🥩 Proteína", 1, 7, key='win_prot')
                win_int = st.slider("💩 Intestino", 1, 7, key='win_int')
            with col_f3: 
                win_carb = st.slider("🍞 Carbo", 1, 7, key='win_carb')
                win_bristol = st.slider("🧪 Bristol", 1, 7, key='win_bristol')
            with col_f4: 
                win_gord = st.slider("🥑 Gordura", 1, 7, key='win_gord')
                win_passos = st.slider("👣 Passos", 1, 7, key='win_passos')
            with col_f5:
                win_sono_h = st.slider("💤 Sono (Horas)", 1, 7, key='win_sono_h')
                win_sono_q = st.slider("🌟 Sono (Qualid.)", 1, 7, key='win_sono_q')
            
            df_model = df_qs.copy()
            
            df_model['peso_suav'] = df_model['peso_kg'].rolling(window=win_peso, min_periods=1).mean()
            df_model['peso_suav_amanha'] = df_model['peso_suav'].shift(-1)
            df_model['target'] = df_model['peso_suav_amanha'] - df_model['peso_suav']
            
            df_model['gord_f'] = df_model['tgord'].rolling(window=win_gord, min_periods=1).mean()
            df_model['carb_f'] = df_model['tcarb'].rolling(window=win_carb, min_periods=1).mean()
            df_model['prot_f'] = df_model['tprot'].rolling(window=win_prot, min_periods=1).mean()
            df_model['jejum_f'] = df_model['jejum_h'].rolling(window=win_jej, min_periods=1).mean()
            df_model['passos_f'] = df_model['t_passos_trabalho'].rolling(window=win_passos, min_periods=1).mean()
            df_model['agua_f'] = df_model['tagua'].rolling(window=win_agua, min_periods=1).mean()
            df_model['int_f'] = df_model['tintestino'].rolling(window=win_int, min_periods=1).mean()
            df_model['bristol_f'] = df_model['tbristol'].rolling(window=win_bristol, min_periods=1).mean()
            df_model['sono_h_f'] = df_model['sono_h'].rolling(window=win_sono_h, min_periods=1).mean()
            df_model['sono_q_f'] = df_model['sono_q'].rolling(window=win_sono_q, min_periods=1).mean()
            
            lista_features = ['jejum_f', 'prot_f', 'carb_f', 'gord_f', 'passos_f', 'agua_f', 'int_f', 'bristol_f', 'sono_h_f', 'sono_q_f']
            df_model = df_model.dropna(subset=['target'] + lista_features)
            
            st.markdown("---")

            if len(df_model) > 5:
                formula = 'target ~ ' + ' + '.join(lista_features)
                model = ols(formula, data=df_model).fit()
                
                r2 = model.rsquared
                aic_val = model.aic
                bic_val = model.bic
                params = model.params
                pvalues = model.pvalues
                
                st.markdown(f"**R² Sintonizado:** {r2*100:.1f}% | **AIC:** {aic_val:.1f} | **BIC:** {bic_val:.1f} | **N:** {len(df_model)} dias")
                
                c_stats1, c_stats2 = st.columns([1, 1.2])
                
                with c_stats1:
                    st.markdown("##### 🔬 Peso Estatístico (P-Valor)")
                    df_resumo = pd.DataFrame({'Coeficiente (kg)': params, 'P-Valor': pvalues}).drop('Intercept')
                    df_resumo.index = [f'Jejum ({win_jej}d)', f'Proteína ({win_prot}d)', f'Carbo ({win_carb}d)', f'Gordura ({win_gord}d)', f'Passos ({win_passos}d)', f'Água ({win_agua}d)', f'Intestino ({win_int}d)', f'Bristol ({win_bristol}d)', f'Sono H ({win_sono_h}d)', f'Sono Q ({win_sono_q}d)']
                    
                    df_resumo_table = df_resumo.copy()
                    df_resumo_table['Coeficiente (kg)'] = df_resumo_table['Coeficiente (kg)'].apply(lambda x: f"{x:+.5f}")
                    df_resumo_table['P-Valor'] = df_resumo_table['P-Valor'].apply(lambda x: f"{x:.3f} {'(🟢)' if x < 0.05 else '(🟠)' if x < 0.15 else '(⚪)'}")
                    
                    st.table(df_resumo_table)
                    st.caption("🟢 P < 0.05: Alta Relevância | 🟠 P < 0.15: Relevância Moderada | ⚪ > 0.15: Ruído Sistêmico")
                    
                with c_stats2:
                    st.markdown("##### 🏆 Torneio El Farol (Agente no Comando)")
                    
                    vencedor, menor_erro, mod_lr, mod_rf, df_auditoria = torneio_el_farol(df_model, features=lista_features, target_col='target')
                    
                    if vencedor:
                        st.info(f"**Líder Atual:** {vencedor} | **Erro da Tendência:** {menor_erro*1000:.0f} g")
                        
                        with st.expander("🔍 Auditoria dos Agentes", expanded=False):
                            df_auditoria_tb = df_auditoria.copy()
                            for col in ['Real (g)', 'Previsto LR (g)', 'Previsto RF (g)']: df_auditoria_tb[col] = df_auditoria_tb[col].apply(lambda x: f"{x:+.0f}")
                            for col in ['Erro LR (g)', 'Erro RF (g)']: df_auditoria_tb[col] = df_auditoria_tb[col].apply(lambda x: f"{x:.0f}")
                            st.table(df_auditoria_tb)

                        st.markdown("##### 🔮 Simulador Preditivo")
                        sim_col1, sim_col2, sim_col3 = st.columns(3) 
                        with sim_col1:
                            sim_jej = st.slider(f"Jejum ({win_jej}d)", 8.0, 24.0, 16.0, 0.5)
                            sim_prot = st.slider(f"Proteína ({win_prot}d)", 50, 250, int(p['meta_proteina']), 5)
                            sim_agua = st.slider(f"Água ml ({win_agua}d)", 1000, 5000, 3000, 100)
                            sim_sono_h = st.slider(f"Sono h ({win_sono_h}d)", 0.0, 14.0, 7.5, 0.5)
                        with sim_col2:
                            sim_carb = st.slider(f"Carbo ({win_carb}d)", 20, 300, int(p['meta_carbo']), 5)
                            sim_gord = st.slider(f"Gordura ({win_gord}d)", 20, 150, int(p['meta_gordura']), 5)
                            sim_int = st.slider(f"Idas Intestino ({win_int}d)", 0, 5, 1, 1)
                            sim_sono_q = st.slider(f"Qualid. Sono ({win_sono_q}d)", 1, 5, 3, 1)
                        with sim_col3:
                            sim_passos = st.slider(f"Passos ({win_passos}d)", 0, 30000, 10000, 500)
                            sim_bristol = st.slider(f"Bristol ({win_bristol}d)", 1, 7, 3, 1)
                        
                        entrada_sim = pd.DataFrame({'jejum_f': [sim_jej], 'prot_f': [sim_prot], 'carb_f': [sim_carb], 'gord_f': [sim_gord], 'passos_f': [sim_passos], 'agua_f': [sim_agua], 'int_f': [sim_int], 'bristol_f': [sim_bristol], 'sono_h_f': [sim_sono_h], 'sono_q_f': [sim_sono_q]})
                        
                        if vencedor == "Random Forest": pred_delta = mod_rf.predict(entrada_sim)[0]
                        else: pred_delta = mod_lr.predict(entrada_sim)[0]
                        
                        st.metric("Tendência de Variação", f"{pred_delta*1000:+.0f} g", delta_color="inverse")
                    else:
                        st.warning("⏳ Aguardando acúmulo de dados (mínimo 10 dias) para iniciar o Torneio El Farol.")

            # ============================================================================
            # 🧠 IA GROQ: FEEDBACK METABÓLICO EM TEMPO REAL
            # ============================================================================
            st.markdown("---")
            st.markdown("##### 🧠 Consultoria Metabólica Especializada (IA)")
            if st.button("🩺 Pedir Feedback ao Groq (Análise de Inércia)"):
                try:
                    from groq import Groq
                    api_key = st.secrets.get("api_key")
                    
                    if not api_key:
                        st.error("⚠️ Chave 'api_key' não encontrada no arquivo .streamlit/secrets.toml")
                    else:
                        client = Groq(api_key=api_key)
                        
                        prompt_medico = f"""
                        Atue como um endocrinologista e especialista em biologia de sistemas. 
                        Abaixo estão os resultados do meu modelo de regressão linear multivariável (OLS) que prevê a variação diária do meu peso baseado no meu comportamento metabólico histórico.
                        
                        Métricas Globais de Previsibilidade:
                        - Poder de explicação (R²): {r2*100:.1f}%
                        - Ruído/Ajuste (AIC): {aic_val:.1f}
                        
                        Sinais Vitais e Inércia Metabólica (Variável | Coeficiente de Impacto em kg | P-Valor):
                        {df_resumo_table.to_string()}
                        
                        Considerando que P-valores < 0.05 indicam alta significância estatística (marcados com 🟢) e os coeficientes indicam impacto direto na balança:
                        Faça uma análise clínica de exatos 2 parágrafos curtos:
                        1. O que a inércia dos dias (ex: impacto de variáveis de 7 dias vs 1 dia) revela sobre como o meu corpo processa e retém peso atualmente? Foque nos P-valores mais relevantes (🟢).
                        2. Com base nesses dados quantitativos, qual é a principal recomendação prática para eu otimizar a queima de gordura/desinflamação para amanhã?
                        """
                        
                        with st.spinner("Conectando ao laboratório de IA... Analisando sua bioestatística..."):
                            stream = client.chat.completions.create(
                                model="llama3-70b-8192",
                                messages=[{"role": "user", "content": prompt_medico}],
                                temperature=0.3,
                                stream=True,
                            )
                            
                            def generate_groq_stream(stream_obj):
                                for chunk in stream_obj:
                                    if chunk.choices[0].delta.content is not None:
                                        yield chunk.choices[0].delta.content
                                        
                            st.write_stream(generate_groq_stream(stream))
                            
                except ImportError:
                    st.error("⚠️ Biblioteca 'groq' não instalada. Abra o terminal e execute: pip install groq")
                except Exception as e:
                    st.error(f"🚨 Erro na comunicação com a API do Groq: {e}")
            
            # ============================================================================
            # 🧬 BLOCO EVOLUTIVO V12.1 (ALGORITMO GENÉTICO)
            # ============================================================================
            st.markdown("---")
            with st.expander("🧬 Evolução Genética do DNA Metabólico (AIC Evaluator)", expanded=False):
                st.markdown("O Algoritmo Genético busca a **Inércia de Ouro** simulando a seleção natural. Ele testa cruzamentos e mutações de janelas (1 a 7 dias) e converge para as combinações de menor AIC (Akaike Information Criterion).")
                if st.button("🚀 Iniciar Evolução Biométrica"):
                    with st.spinner("Decodificando DNA Metabólico através de algoritmos genéticos..."):
                        TAM_POP = 50
                        GERACOES = 15
                        JANELA_MAX = 7
                        
                        base_df = df_qs[['peso_kg', 'jejum_h', 'tprot', 'tcarb', 'tgord', 't_passos_trabalho', 'tagua', 'tintestino', 'tbristol', 'sono_h', 'sono_q']].copy()
                        
                        pre_calc = {}
                        for w in range(1, JANELA_MAX + 1):
                            pre_calc[f't_{w}'] = base_df['peso_kg'].rolling(window=w, min_periods=1).mean().shift(-1) - base_df['peso_kg'].rolling(window=w, min_periods=1).mean()
                            for c in ['tprot', 'tcarb', 'tgord', 'tagua', 'tintestino', 'tbristol', 'sono_h', 'sono_q', 'jejum_h', 't_passos_trabalho']:
                                pre_calc[f'{c}_{w}'] = base_df[c].rolling(window=w, min_periods=1).mean()
                        df_pre = pd.DataFrame(pre_calc)

                        def fitness(ind):
                            cols = [f'jejum_h_{ind[1]}', f'tprot_{ind[2]}', f'tcarb_{ind[3]}', f'tgord_{ind[4]}', f't_passos_trabalho_{ind[5]}', f'tagua_{ind[6]}', f'tintestino_{ind[7]}', f'tbristol_{ind[8]}', f'sono_h_{ind[9]}', f'sono_q_{ind[9]}']
                            d = df_pre[[f't_{ind[0]}'] + cols].dropna()
                            if len(d) < 15: return 9999
                            try:
                                return sm.OLS(d[f't_{ind[0]}'], sm.add_constant(d[cols])).fit().aic
                            except:
                                return 9999

                        pop = [[random.randint(1, JANELA_MAX) for _ in range(10)] for _ in range(TAM_POP)]
                        progress_bar = st.progress(0)
                        
                        for g in range(GERACOES):
                            pop = sorted(pop, key=lambda i: fitness(i))
                            nova_pop = pop[:5] 
                            while len(nova_pop) < TAM_POP:
                                p1, p2 = random.sample(pop[:20], 2)
                                filho = [p1[i] if random.random() > 0.5 else p2[i] for i in range(10)]
                                if random.random() < 0.2: 
                                    filho[random.randint(0,9)] = random.randint(1, JANELA_MAX)
                                nova_pop.append(filho)
                            pop = nova_pop
                            progress_bar.progress((g + 1) / GERACOES)
                        
                        best = pop[0]
                        st.session_state['novo_dna_metabolico'] = best
                        st.rerun()

            st.markdown("---")

        else:
            st.warning("Aguardando dados consolidados de variação de peso para processar o laboratório.")
    else:
        st.info("📊 Aguardando cruzamento de dados de peso e consumo para exibir a aba Quantified Self.")

# ============================================================================
# ABA 2: DASHBOARD ORIGINAL (MANTIDO)
# ============================================================================
with tab_dash:
    st.markdown(f"### 🦁 Leo's Performance Dashboard | {hoje.strftime('%d/%m/%Y')}")

    k_act = df_hoje_comida['kcal'].sum() if not df_hoje_comida.empty else 0
    p_act = df_hoje_comida['proteina'].sum() if not df_hoje_comida.empty else 0
    meta_agua = round((peso_atual * 35) / 1000, 1)

    treino_min = int(df_hoje_treino['duracao_min'].sum()) if not df_hoje_treino.empty else 0
    treino_passos_trabalho = int(df_hoje_treino['passos_trabalho'].sum()) if not df_hoje_treino.empty else 0

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("⚖️ Peso Atual", f"{peso_atual} kg", f"Meta: {p['meta_peso_alvo']}")
    c2.metric("🔥 Calorias (Hoje)", f"{int(k_act)}", f"Meta: {p['meta_kcal']}")
    c3.metric("🥩 Proteína (Hoje)", f"{int(p_act)}g", f"Meta: {p['meta_proteina']}")
    c4.metric("💧 Água", f"{meta_agua}L", "Minímo")
    c5.metric("🏃‍♂️ Treino (Hoje)", f"{treino_min} min", f"{treino_passos_trabalho} passos")

    last_bp_txt = "--"
    if not df_bp.empty:
        last = df_bp.iloc[-1]
        last_bp_txt = f"{last['systolic']}x{last['diastolic']}"
    c6.metric("❤️ Pressão", last_bp_txt, f"Pulso: {last.get('pulse', '--')}")

    st.divider()

    c_main1, c_main2 = st.columns([2, 1])

    with c_main1:
        st.markdown("##### 🧪 Densidade Energética: Volume vs. Calorias")
        if not df_merged.empty and 'tkcal' in df_merged.columns:
            fig_vol = make_subplots(specs=[[{"secondary_y": True}]])
            fig_vol.add_trace(go.Bar(x=df_merged['data_dt'], y=df_merged['tqtd'], name="Volume (g)", marker_color='#AED6F1', opacity=0.5), secondary_y=True)
            fig_vol.add_trace(go.Scatter(x=df_merged['data_dt'], y=df_merged['tkcal'], name="Calorias In", mode='lines+markers', line=dict(color='#C0392B', width=3)), secondary_y=False)
            if 'get_total' in df_merged.columns:
                fig_vol.add_trace(go.Scatter(x=df_merged['data_dt'], y=df_merged['get_total'], name="Gasto Total (Out)", mode='lines', line=dict(color='#27AE60', width=2, dash='dot')), secondary_y=False)
            fig_vol.update_layout(height=450, margin=dict(l=10,r=10,t=30,b=10), legend=dict(orientation="h", y=1.1), template="plotly_white")
            fig_vol.update_yaxes(title_text="Kcal", secondary_y=False, showgrid=True)
            fig_vol.update_yaxes(title_text="Gramas", secondary_y=True, showgrid=False)
            st.plotly_chart(fig_vol, use_container_width=True)

    with c_main2:
        st.markdown("##### 🏦 Termodinâmica & Déficit")
        if not df_merged.empty and 'deficit_real' in df_merged.columns:
            deficit_total = df_merged['deficit_real'].sum()
            kg_gordura = deficit_total / 7700
            peso_start = df_merged.iloc[0]['peso_kg']
            peso_curr = df_merged.iloc[-1]['peso_kg']
            perda_real = peso_start - peso_curr
            perda_teorica = deficit_total / 7700
            fator_termo = perda_real / perda_teorica if perda_teorica > 0.1 else 1.0

            st.metric("Déficit Acumulado", f"{int(deficit_total)} kcal")
            st.metric("Gordura Eliminada (Teórica)", f"{kg_gordura:.2f} kg")
            if fator_termo > 1.15: lbl, clr = "🔥 Turbo", "normal"
            elif fator_termo < 0.85: lbl, clr = "❄️ Lento", "inverse"
            else: lbl, clr = "✅ Normal", "off"
            st.metric("Índice Termodinâmico", f"{fator_termo:.2f}x", lbl, delta_color=clr)
            st.caption(f"*Baseado no fator de atividade: {fator_atividade}x*")

    st.divider()

    c_p1, c_p2 = st.columns([2, 1])

    with c_p1:
        st.markdown("##### 🎯 Projeção de Peso")
        if not df_peso.empty:
            df_peso['data_dt'] = pd.to_datetime(df_peso['data']).dt.date
            BASE_DATE = pd.to_datetime("2025-12-31").date()
            df_base = df_peso[df_peso['data_dt'] >= BASE_DATE].sort_values('data_dt')
            
            if not df_base.empty:
                peso_inicial = float(df_base.iloc[0]['peso_kg'])
                datas_proj = pd.date_range(start=BASE_DATE, end=hoje + timedelta(days=14))
                ritmo_diario = float(p['ritmo_semanal']) / 7
                pesos_estimados = [peso_inicial - (i * ritmo_diario) for i in range(len(datas_proj))]
                fig_proj = go.Figure()
                fig_proj.add_trace(go.Scatter(x=datas_proj, y=pesos_estimados, mode='lines', name='Meta Ideal', line=dict(color='#29B5E8', dash='dash')))
                fig_proj.add_trace(go.Scatter(x=df_base['data_dt'], y=df_base['peso_kg'], mode='lines+markers', name='Realizado', line=dict(color='#FF4B4B', width=3)))
                fig_proj.update_layout(height=400, margin=dict(l=10,r=10,t=20,b=10), legend=dict(orientation="h", y=1.1), template="plotly_white")
                st.plotly_chart(fig_proj, use_container_width=True)

    with c_p2:
        st.markdown("##### 🏃‍♂️ Consistência de Treino")
        if not df_merged.empty and 't_passos_trabalho' in df_merged.columns:
            fig_tr = make_subplots(specs=[[{"secondary_y": True}]])
            fig_tr.add_trace(go.Scatter(x=df_merged['data_dt'], y=df_merged['t_passos_trabalho'], name='Passos', mode='lines', line=dict(color='#8E44AD', width=2)), secondary_y=False)
            fig_tr.update_layout(height=400, margin=dict(l=10,r=10,t=20,b=10), showlegend=False, template="plotly_white")
            st.plotly_chart(fig_tr, use_container_width=True)

    st.divider()

    st.markdown("##### 🧬 Indicadores de Saúde")
    col_s1, col_s2, col_s3 = st.columns(3)

    with col_s1:
        if not df_medidas.empty:
            fig_bf = go.Figure(go.Scatter(x=df_medidas['log_date'], y=df_medidas['body_fat_est'], mode='lines+markers', name="BF%", line=dict(color='#e67e22')))
            fig_bf.update_layout(title="Gordura Corporal (%)", height=300, margin=dict(l=10,r=10,t=30,b=10))
            st.plotly_chart(fig_bf, use_container_width=True)

    with col_s2:
        if not df_bp.empty:
            fig_bp = go.Figure()
            fig_bp.add_trace(go.Scatter(x=df_bp['measurement_time'], y=df_bp['systolic'], name="Sys", line=dict(color='#c0392b')))
            fig_bp.add_trace(go.Scatter(x=df_bp['measurement_time'], y=df_bp['diastolic'], name="Dia", line=dict(color='#2980b9')))
            fig_bp.update_layout(title="Pressão Arterial", height=300, margin=dict(l=10,r=10,t=30,b=10))
            st.plotly_chart(fig_bp, use_container_width=True)

    with col_s3:
        if not df_hist.empty:
            df_macros = df_hist.copy()
            df_macros['tot'] = (df_macros['tprot']*4 + df_macros['tcarb']*4 + df_macros['tgord']*9).replace(0, 1)
            fig_stack = go.Figure()
            fig_stack.add_trace(go.Bar(x=df_macros['data'], y=(df_macros['tprot']*4/df_macros['tot'])*100, name='P', marker_color='#3366CC'))
            fig_stack.add_trace(go.Bar(x=df_macros['data'], y=(df_macros['tgord']*9/df_macros['tot'])*100, name='G', marker_color='#DC3912'))
            fig_stack.add_trace(go.Bar(x=df_macros['data'], y=(df_macros['tcarb']*4/df_macros['tot'])*100, name='C', marker_color='#FF9900'))
            fig_stack.update_layout(title="Distribuição Macros (%)", barmode='stack', height=300, margin=dict(l=10,r=10,t=30,b=10), yaxis=dict(range=[0, 100]), showlegend=False)
            st.plotly_chart(fig_stack, use_container_width=True)

    st.divider()

    st.markdown("### 📊 Análise de Tendências (Médias Móveis & Extremos)")

    if not df_merged.empty and 'deficit_real' in df_merged.columns:
        cols_eda = ['peso_kg', 'tkcal', 'tprot', 'tcarb', 'tgord', 't_min', 't_passos_trabalho', 'deficit_real']
        cols_present = [c for c in cols_eda if c in df_merged.columns]
        df_eda = df_merged[['data_dt', *cols_present]].copy().sort_values('data_dt').fillna(0)

        def calc_mean(df, days, col): 
            if col in df.columns: return df.tail(days)[col].mean()
            return 0

        metrics_list = [
            ("⚖️ Peso Médio (kg)", 'peso_kg'),
            ("🔥 Calorias (kcal)", 'tkcal'),
            ("🥩 Proteína (g)", 'tprot'),
            ("🍞 Carbo (g)", 'tcarb'),
            ("🥑 Gordura (g)", 'tgord'),
            ("⏱️ Treino (min)", 't_min'),
            ("👣 Passos", 't_passos_trabalho'),
            ("📉 Déficit Diário", 'deficit_real')
        ]

        eda_data = []
        for label, col in metrics_list:
            if col in df_eda.columns:
                row = {
                    "Indicador": label,
                    "3 Dias": f"{calc_mean(df_eda, 3, col):.1f}",
                    "7 Dias": f"{calc_mean(df_eda, 7, col):.1f}",
                    "30 Dias": f"{calc_mean(df_eda, 30, col):.1f}",
                    "Média (Total)": f"{df_eda[col].mean():.1f}",
                    "Mínimo": f"{df_eda[col].min():.1f}",
                    "Máximo": f"{df_eda[col].max():.1f}"
                }
                eda_data.append(row)

        if eda_data:
            st.table(pd.DataFrame(eda_data))

    with st.expander("📚 Metodologia e Glossário Técnico (Clique para abrir)", expanded=False):
        st.markdown("""
        ### 1. Estimativa de Gasto Energético (GET)
        * **Fórmula Base:** Equação de Mifflin-St Jeor.
        * **Ajuste:** Multiplicado pelo Fator de Atividade.
        
        ### 2. Termodinâmica e Déficit
        * **Déficit Real:** Diferença entre o Gasto Total Estimado e as Calorias Ingeridas.
        * **Perda Teórica:** Déficit Acumulado / 7700 (Considerando que 1kg de gordura ≈ 7700kcal).
        
        ### 3. Modelo Matemático (Oráculo com Avaliação Bayesiana/Akaike)
        * **Metodologia:** Regressão Linear Múltipla (OLS) com janelas móveis.
        * **Autotuning Evolutivo:** Teste genético simulando a evolução natural focado em minimizar o AIC (Critério de Informação de Akaike). O modelo é penalizado pela quantidade de parâmetros ($2k$), priorizando apenas as janelas que entregam sinal real, expurgando o ruído sistêmico (*overfitting*).
        * **Torneio El Farol:** Seleção dinâmica entre Regressão Linear e Random Forest baseada no menor MAE (Mean Absolute Error).
        """)

    st.caption("Leo Tracker Smart View v10.1 | Full ETL, AG Evaluator & Groq AI")
