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

# ============================================================================
# 1. CONFIGURAÇÃO VISUAL
# ============================================================================
st.set_page_config(page_title="Leo's Nutrition Control", page_icon="🦁", layout="wide", initial_sidebar_state="collapsed")

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
    except Exception:
        return pd.DataFrame()

if st.query_params.get("token") != st.secrets.get("DASH_ACCESS_TOKEN"):
    st.error("🔒 Acesso Restrito. Token inválido."); st.stop()

# ============================================================================
# 3. ETL (EXTRAÇÃO E TRATAMENTO)
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
        
        # O delta normal para métricas diárias brutas (para os primeiros gráficos)
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
            
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("⚖️ Variação Diária (Real)", f"{last_day['delta_peso_kg']*1000:.0f} g", help="Valores negativos indicam perda de peso na balança.")
            col2.metric("📐 Termodinâmica (Esperado)", f"{last_day['delta_esperado_kg']*1000:.0f} g", help="Gordura teórica queimada baseada no déficit.")
            col3.metric("💧 Fator Desinflamação", f"{last_day['fator_desinflamacao']*1000:.0f} g", help="Negativo = Eliminou água/Desinflamou. Positivo = Reteu líquido/glicogênio.")
            status_color = "🔴" if last_day['tipo_perda'] == 'Perda de Gordura Pura (Vermelho)' else "🔵" if "Desinflamação" in last_day['tipo_perda'] else "🟡"
            col4.markdown(f"**Qualidade da Variação (Hoje):**<br> {status_color} {last_day['tipo_perda'].split(' (')[0]}", unsafe_allow_html=True)

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
            st.markdown("### 3️⃣ Oráculo Metabólico Dinâmico (Sintonizador de Sinais)")
            st.markdown("Ajuste as janelas móveis (em dias) para sincronizar o tempo de resposta fisiológica de cada variável no seu corpo.")
            
            # Controles Interativos de Engenharia de Features - TOTALMENTE INDEPENDENTES
            st.markdown("**🎯 Variável Alvo (Filtro Anti-Ruído)**")
            win_peso = st.slider("⚖️ Filtro: Peso (Tendência da Balança)", 1, 7, 3, help="1 = Tenta prever a balança exata de amanhã. 3 a 7 = Previsão da média dos próximos dias (remove o ruído da retenção de água).")
            
            st.markdown("**⚙️ Variáveis Independentes (Atraso Fisiológico)**")
            col_f1, col_f2, col_f3, col_f4, col_f5 = st.columns(5)
            with col_f1: win_jej = st.slider("⏳ Jejum", 1, 7, 1)
            with col_f2: win_prot = st.slider("🥩 Proteína", 1, 7, 3)
            with col_f3: win_carb = st.slider("🍞 Carbo", 1, 7, 2)
            with col_f4: win_gord = st.slider("🥑 Gordura", 1, 7, 1)
            with col_f5: win_passos = st.slider("👣 Passos", 1, 7, 2)
            
            # Recalculando o dataframe de modelo com base nos sliders independentes
            df_model = df_qs.copy()
            
            # Suavizando o Target (Peso)
            df_model['peso_suav'] = df_model['peso_kg'].rolling(window=win_peso, min_periods=1).mean()
            df_model['peso_suav_amanha'] = df_model['peso_suav'].shift(-1)
            df_model['target'] = df_model['peso_suav_amanha'] - df_model['peso_suav']
            
            # Suavizando as Features (Inputs) individualmente
            df_model['gord_f'] = df_model['tgord'].rolling(window=win_gord, min_periods=1).mean()
            df_model['carb_f'] = df_model['tcarb'].rolling(window=win_carb, min_periods=1).mean()
            df_model['prot_f'] = df_model['tprot'].rolling(window=win_prot, min_periods=1).mean()
            df_model['jejum_f'] = df_model['jejum_h'].rolling(window=win_jej, min_periods=1).mean()
            df_model['passos_f'] = df_model['t_passos_trabalho'].rolling(window=win_passos, min_periods=1).mean()
            
            lista_features = ['jejum_f', 'prot_f', 'carb_f', 'gord_f', 'passos_f']
            df_model = df_model.dropna(subset=['target'] + lista_features)
            
            st.markdown("---")

            if len(df_model) > 5:
                # OLS Dinâmico
                formula = 'target ~ jejum_f + prot_f + carb_f + gord_f + passos_f'
                model = ols(formula, data=df_model).fit()
                
                r2 = model.rsquared
                params = model.params
                pvalues = model.pvalues
                
                st.markdown(f"**R² do Modelo Sintonizado:** {r2*100:.1f}% | **N amostral:** {len(df_model)} dias calibrados")
                st.latex(rf"\Delta Peso (kg) = {params['Intercept']:.3f} {params['jejum_f']:+.4f}(Jejum) {params['prot_f']:+.4f}(Prot) {params['carb_f']:+.4f}(Carbo) {params['gord_f']:+.4f}(Gord) {params['passos_f']:+.6f}(Passos)")
                
                c_stats1, c_stats2 = st.columns([1, 1.2])
                
                with c_stats1:
                    st.markdown("##### 🔬 Peso Estatístico (P-Valor)")
                    df_resumo = pd.DataFrame({'Coeficiente (kg)': params, 'P-Valor': pvalues}).drop('Intercept')
                    # Atualizando a tabela para mostrar as janelas individuais
                    df_resumo.index = [f'Jejum ({win_jej}d)', f'Proteína ({win_prot}d)', f'Carbo ({win_carb}d)', f'Gordura ({win_gord}d)', f'Passos ({win_passos}d)']
                    
                    def highlight_pval(val):
                        if val < 0.05: return 'color: #27AE60; font-weight: bold;'
                        elif val < 0.15: return 'color: #F39C12; font-weight: bold;'
                        return 'color: #7F8C8D;'
                    
                    st.dataframe(df_resumo.style.map(highlight_pval, subset=['P-Valor']).format({'Coeficiente (kg)': '{:+.5f}', 'P-Valor': '{:.3f}'}), use_container_width=True)
                    st.caption("🟢 P < 0.05: Alta Relevância | 🟠 P < 0.15: Relevância Moderada | ⚪ > 0.15: Ruído Sistêmico")
                    
                with c_stats2:
                    st.markdown("##### 🏆 Torneio El Farol (Agente no Comando)")
                    
                    vencedor, menor_erro, mod_lr, mod_rf, df_auditoria = torneio_el_farol(df_model, features=lista_features, target_col='target')
                    
                    if vencedor:
                        st.info(f"**Líder Atual:** {vencedor} | **Margem de Erro da Tendência:** {menor_erro*1000:.0f} g")
                        
                        with st.expander("🔍 Auditoria dos Agentes (Ver Histórico de Erros)", expanded=False):
                            st.markdown("Previsão vs. Variação Real (últimos 5 dias).")
                            st.dataframe(df_auditoria.style.format({
                                'Real (g)': '{:+.0f}', 'Previsto LR (g)': '{:+.0f}', 'Previsto RF (g)': '{:+.0f}',
                                'Erro LR (g)': '{:.0f}', 'Erro RF (g)': '{:.0f}'
                            }), use_container_width=True, hide_index=True)

                        st.markdown("##### 🔮 Simulador Preditivo")
                        sim_col1, sim_col2, sim_col3 = st.columns(3) 
                        with sim_col1:
                            sim_jej = st.slider(f"Jejum ({win_jej}d)", 8.0, 24.0, 16.0, 0.5)
                            sim_prot = st.slider(f"Proteína ({win_prot}d)", 50, 250, int(p['meta_proteina']), 5)
                        with sim_col2:
                            sim_carb = st.slider(f"Carbo ({win_carb}d)", 20, 300, int(p['meta_carbo']), 5)
                            sim_gord = st.slider(f"Gordura ({win_gord}d)", 20, 150, int(p['meta_gordura']), 5)
                        with sim_col3:
                            sim_passos = st.slider(f"Passos ({win_passos}d)", 0, 30000, 10000, 500)
                        
                        entrada_sim = pd.DataFrame({'jejum_f': [sim_jej], 'prot_f': [sim_prot], 'carb_f': [sim_carb], 'gord_f': [sim_gord], 'passos_f': [sim_passos]})
                        
                        if vencedor == "Random Forest": pred_delta = mod_rf.predict(entrada_sim)[0]
                        else: pred_delta = mod_lr.predict(entrada_sim)[0]
                        
                        st.metric("Tendência de Variação", f"{pred_delta*1000:+.0f} g", delta_color="inverse")
                    else:
                        st.warning("⏳ Aguardando acúmulo de dados (mínimo 10 dias) para iniciar o Torneio El Farol.")
            else:
                st.info("📊 Aguardando mais logs simultâneos para gerar o modelo matemático preditivo.")
        
        # ============================================================================
        # BOTÃO DE AUTOTUNING (GRID SEARCH COM GRÁFICO DE RADAR)
        # ============================================================================
        st.markdown("---")
        with st.expander("🤖 Otimização Combinatória (Descobrir DNA Metabólico)", expanded=False):
            st.markdown("O algoritmo testará ~15.600 combinações de filtros (de 1 a 5 dias) para encontrar a inércia fisiológica que maximiza a previsibilidade do seu peso.")
            
            if st.button("🚀 Iniciar Autotuning"):
                with st.spinner("Calculando o DNA do seu metabolismo..."):
                    range_filtros = range(1, 6) # Testando de 1 a 5 dias
                    combinacoes = list(itertools.product(range_filtros, repeat=6))
                    
                    resultados = []
                    base_df = df_qs[['peso_kg', 'jejum_h', 'tprot', 'tcarb', 'tgord', 't_passos_trabalho']].copy()
                    
                    progress_bar = st.progress(0)
                    total_comb = len(combinacoes)
                    
                    for i, (w_peso, w_jej, w_prot, w_carb, w_gord, w_passos) in enumerate(combinacoes):
                        if i % 500 == 0: progress_bar.progress(i / total_comb)
                            
                        df_temp = base_df.copy()
                        df_temp['peso_suav'] = df_temp['peso_kg'].rolling(window=w_peso, min_periods=1).mean()
                        df_temp['peso_suav_amanha'] = df_temp['peso_suav'].shift(-1)
                        df_temp['target'] = df_temp['peso_suav_amanha'] - df_temp['peso_suav']
                        
                        df_temp['gord_f'] = df_temp['tgord'].rolling(window=w_gord, min_periods=1).mean()
                        df_temp['carb_f'] = df_temp['tcarb'].rolling(window=w_carb, min_periods=1).mean()
                        df_temp['prot_f'] = df_temp['tprot'].rolling(window=w_prot, min_periods=1).mean()
                        df_temp['jejum_f'] = df_temp['jejum_h'].rolling(window=w_jej, min_periods=1).mean()
                        df_temp['passos_f'] = df_temp['t_passos_trabalho'].rolling(window=w_passos, min_periods=1).mean()
                        
                        df_model_loop = df_temp.dropna()
                        
                        if len(df_model_loop) > 10:
                            try:
                                model_loop = sm.OLS(df_model_loop['target'], sm.add_constant(df_model_loop[['jejum_f', 'prot_f', 'carb_f', 'gord_f', 'passos_f']])).fit()
                                resultados.append({
                                    'R²': model_loop.rsquared,
                                    'Filtro Peso': w_peso, 'Jejum': w_jej, 'Prot': w_prot, 
                                    'Carbo': w_carb, 'Gord': w_gord, 'Passos': w_passos
                                })
                            except: pass
                    
                    progress_bar.progress(1.0)
                    
                    if resultados:
                        df_res = pd.DataFrame(resultados).sort_values(by='R²', ascending=False).head(10)
                        st.success("Busca concluída! Visualizando os 10 melhores perfis.")
                        
                        # Tabela
                        st.dataframe(df_res.style.format({'R²': '{:.2%}'}).background_gradient(subset=['R²'], cmap='Greens'), use_container_width=True, hide_index=True)
                        
                        # Gráfico de Radar (Aranha)
                        categories = ['Filtro Peso', 'Jejum', 'Prot', 'Carbo', 'Gord', 'Passos']
                        fig_radar = go.Figure()
                        
                        colors = ['#FFD700', '#C0C0C0', '#CD7F32'] + ['#3498db'] * 7 # Ouro, Prata, Bronze, depois azul

                        for i in range(len(df_res)):
                            row = df_res.iloc[i]
                            values = row[categories].values.tolist()
                            values += values[:1] # Fechar o ciclo do radar
                            
                            fig_radar.add_trace(go.Scatterpolar(
                                r=values,
                                theta=categories + categories[:1],
                                fill='toself' if i == 0 else 'none',
                                name=f"Rank #{i+1} (R²: {row['R²']:.1%})",
                                line=dict(color=colors[i], width=3 if i == 0 else 1),
                                opacity=1.0 if i == 0 else 0.5
                            ))

                        fig_radar.update_layout(
                            polar=dict(
                                radialaxis=dict(visible=True, range=[0, 6], tickvals=[1,2,3,4,5]),
                            ),
                            showlegend=True, height=500, title="DNA Metabólico: Perfil dos Melhores Modelos"
                        )
                        st.plotly_chart(fig_radar, use_container_width=True)
                        
                        st.info("👆 O gráfico mostra o 'formato' das melhores configurações. O modelo #1 (Dourado) é o mais preciso. Ajuste os sliders acima com os valores dele!")
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
        
        ### 3. Modelo Matemático (Oráculo com Sintonizador & Autotuning)
        * **Metodologia:** Regressão Linear Múltipla (OLS) com janelas móveis independentes para cada variável.
        * **Autotuning:** Um algoritmo de busca em grade (grid search) testa mais de 15.000 combinações de filtros para encontrar a configuração que maximiza o R² (poder preditivo).
        * **Torneio El Farol & Auditoria:** Seleção dinâmica entre Regressão Linear e Random Forest baseada no menor MAE (Mean Absolute Error) dos últimos 5 dias.
        """)

    st.caption("Leo Tracker Smart View v7.1 | Autotuning & Radar Chart Edition")
