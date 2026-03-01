import streamlit as st
import pandas as pd
import numpy as np
from sqlalchemy import create_engine, text
from datetime import datetime, timedelta
import json
import pytz 
from groq import Groq 
import io
import math
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# Imports para o Oráculo Preditivo
from sklearn.linear_model import LinearRegression
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error

# ============================================================================
# 1. CONFIGURAÇÃO E ACESSO
# ============================================================================
st.set_page_config(page_title="Leo Tracker Pro", page_icon="🦁", layout="wide")

# CSS Global
st.markdown("""
    <style>
    div[data-testid="stMetric"] { background-color: #f0f2f6; padding: 10px; border-radius: 10px; border: 1px solid #e0e0e0; }
    @media (prefers-color-scheme: dark) { div[data-testid="stMetric"] { background-color: #262730; border: 1px solid #464b5c; } }
    </style>
    """, unsafe_allow_html=True)

def get_now_br():
    return datetime.now(pytz.timezone('America/Sao_Paulo'))

def check_password():
    if "password_correct" not in st.session_state:
        st.session_state["password_correct"] = False
    if st.session_state["password_correct"]: return True

    st.title("🦁 Leo Tracker Pro")
    password = st.text_input("Senha de Acesso:", type="password")
    if st.button("Entrar"):
        if password == st.secrets.get("PASSWORD", "admin"): 
            st.session_state["password_correct"] = True
            st.rerun()
        else: st.error("Senha incorreta!")
    return False

if not check_password(): st.stop()

# ============================================================================
# 2. CONEXÃO BLINDADA
# ============================================================================
@st.cache_resource(ttl=600)
def get_engine():
    db_url = st.secrets["DATABASE_URL"]
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)
    return create_engine(db_url, pool_pre_ping=True)

def executar_sql(sql, params=None, is_select=False):
    engine = get_engine()
    try:
        if is_select:
            with engine.connect() as conn:
                df = pd.read_sql(text(sql), conn, params=params)
                for col in ['data', 'log_date', 'measurement_time', 'data_hora']:
                    if col in df.columns:
                        try: df[col] = pd.to_datetime(df[col])
                        except: pass
                return df
        else:
            with engine.begin() as conn:
                conn.execute(text(sql), params)
            return True
    except Exception as e:
        if is_select: return pd.DataFrame()
        return False

# ============================================================================
# 3. SINCRONIZAÇÃO DO BANCO
# ============================================================================
def inicializar_banco():
    # Tabela consumo
    executar_sql("CREATE TABLE IF NOT EXISTS public.consumo (id SERIAL PRIMARY KEY, data DATE, alimento TEXT, quantidade REAL, kcal REAL, proteina REAL, carbo REAL, gordura REAL, gluten TEXT DEFAULT 'Não informado');")
    try: executar_sql("ALTER TABLE public.consumo ADD COLUMN IF NOT EXISTS data_hora TIMESTAMP DEFAULT CURRENT_TIMESTAMP;")
    except: pass

    executar_sql("CREATE TABLE IF NOT EXISTS public.peso (id SERIAL PRIMARY KEY, data DATE, peso_kg REAL);")
    executar_sql("""
        CREATE TABLE IF NOT EXISTS public.exercicios (
            id SERIAL PRIMARY KEY, data DATE, tipo TEXT, duracao_min INT, passos INT, distancia_km REAL, calorias REAL, bpm_medio INT, observacoes TEXT
        );
    """)
    try: 
        executar_sql("ALTER TABLE public.exercicios ADD COLUMN IF NOT EXISTS passos_trabalho INT DEFAULT 0;")
        executar_sql("ALTER TABLE public.exercicios ADD COLUMN IF NOT EXISTS passos_total_dia INT DEFAULT 0;")
    except: pass

    executar_sql("""
        CREATE TABLE IF NOT EXISTS public.perfil (
            id SERIAL PRIMARY KEY, genero TEXT, idade INT, altura_cm INT, atividade TEXT, objetivo TEXT, ritmo_semanal REAL, 
            meta_kcal REAL, meta_proteina REAL, meta_carbo REAL, meta_gordura REAL, meta_peso_alvo REAL
        );
    """)
    try: executar_sql("ALTER TABLE public.perfil ADD COLUMN IF NOT EXISTS fator_atividade REAL DEFAULT 1.2;")
    except: pass

    for c in ['ultimo_pescoco', 'ultima_cintura', 'ultimo_quadril']:
        try: executar_sql(f"ALTER TABLE public.perfil ADD COLUMN IF NOT EXISTS {c} REAL;")
        except: pass
    for c in ['fold_chest', 'fold_abdominal', 'fold_thigh', 'fold_triceps', 'body_fat_pollock', 'body_fat_est', 'body_fat_weltman', 'weight_kg']:
        try: executar_sql(f"ALTER TABLE public.body_measurements ADD COLUMN IF NOT EXISTS {c} REAL;")
        except: pass

    executar_sql("""
        CREATE TABLE IF NOT EXISTS public.body_measurements (
            id SERIAL PRIMARY KEY, log_date DATE NOT NULL,
            weight_kg REAL, waist_cm REAL, neck_cm REAL, hip_cm REAL, body_fat_est REAL, notes TEXT,
            fold_chest REAL, fold_abdominal REAL, fold_thigh REAL, fold_triceps REAL, body_fat_pollock REAL, body_fat_weltman REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    executar_sql("""
        CREATE TABLE IF NOT EXISTS public.blood_pressure (
            id SERIAL PRIMARY KEY, measurement_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP, systolic INT, diastolic INT, pulse INT, notes TEXT
        );
    """)

def get_metas_do_banco():
    try:
        df = executar_sql("SELECT * FROM public.perfil WHERE id = 1", is_select=True)
        if not df.empty:
            row = df.iloc[0]
            return {
                "kcal": int(row.get('meta_kcal', 1638)), "prot": int(row.get('meta_proteina', 108)),
                "carb": int(row.get('meta_carbo', 164)), "gord": int(row.get('meta_gordura', 67)),
                "peso_alvo": float(row.get('meta_peso_alvo', 120.0)), "ritmo": float(row.get('ritmo_semanal', 0.8)),
                "altura": int(row.get('altura_cm', 178)), "idade": int(row.get('idade', 41)),
                "genero": row.get('genero', 'Masculino'),
                "fator": float(row.get('fator_atividade') or 1.2),
                "last_waist": float(row.get('ultima_cintura') or 133.0),
                "last_neck": float(row.get('ultimo_pescoco') or 53.0),
                "last_hip": float(row.get('ultimo_quadril') or 122.0)
            }
    except: pass
    return {"kcal": 1638, "prot": 108, "carb": 164, "gord": 67, "peso_alvo": 120.0, "ritmo": 0.8, "altura": 178, "idade": 41, "genero": "Masculino", "fator": 1.2, "last_waist": 133.0, "last_neck": 53.0, "last_hip": 122.0}

inicializar_banco()
METAS = get_metas_do_banco()
p = METAS 

def calc_bf_weltman_obese(waist, weight_kg, height_cm, gender):
    if waist <= 0 or weight_kg <= 0: return 0.0
    try:
        if gender == 'Masculino': return (0.31457 * waist) - (0.10969 * weight_kg) + 10.8336
        else: return (0.11077 * waist) - (0.17666 * height_cm) + (0.14354 * weight_kg) + 51.03301
    except: return 0.0

# ============================================================================
# 4. INTELIGÊNCIA ARTIFICIAL E PREDITORES
# ============================================================================
def processar_texto_ia(texto_usuario, api_key):
    client = Groq(api_key=api_key)
    prompt_system = f"""
    Aja como Nutricionista Matemático. Hoje: {get_now_br().strftime('%Y-%m-%d')}.
    DIRETRIZES RÍGIDAS DE CÁLCULO:
    1. Identifique o alimento e sua densidade calórica padrão (kcal/g).
       - Vegetais: ~0.3 kcal/g
       - Arroz/Massas cozidos: ~1.3 kcal/g
       - Carnes magras: ~1.5 kcal/g
       - Bolos simples: ~3.0 kcal/g
       - Queijos/Gorduras: ~4.0 a 9.0 kcal/g
    2. MULTIPLIQUE a densidade pelo peso informado pelo usuário.
    3. GORDURA OCULTA: Se for fritura/grelhado de restaurante, adicione +5g a +10g de gordura.
    SAÍDA: Retorne APENAS um JSON válido.
    Formato: {{ "analise": "Texto curto explicando o cálculo", "alimentos": [ {{ "data": "YYYY-MM-DD", "alimento": "Nome", "quantidade_g": 0, "kcal": 0, "p": 0, "c": 0, "g": 0, "gluten": "txt" }} ] }}
    """
    try:
        completion = client.chat.completions.create(messages=[{"role": "system", "content": prompt_system}, {"role": "user", "content": texto_usuario}], model="llama-3.3-70b-versatile", response_format={"type": "json_object"})
        raw_content = completion.choices[0].message.content
        cleaned_content = raw_content.replace("```json", "").replace("```", "").strip()
        start_idx = cleaned_content.find('{'); end_idx = cleaned_content.rfind('}')
        if start_idx != -1 and end_idx != -1: cleaned_content = cleaned_content[start_idx:end_idx+1]
        content = json.loads(cleaned_content)
        if isinstance(content, list): content = {"analise": "Processado", "alimentos": content}
        return True, content
    except Exception as e: return False, f"Erro: {str(e)}"

def torneio_el_farol(df_modelo):
    X = df_modelo[['jejum_h', 'tprot', 'tcarb', 'tgord']]
    y = df_modelo['delta_peso_kg']
    
    if len(df_modelo) < 10: return None, None, None, None
        
    X_treino, X_teste = X[:-5], X[-5:]
    y_treino, y_teste = y[:-5], y[-5:]
    
    agente_lr = LinearRegression().fit(X_treino, y_treino)
    agente_rf = RandomForestRegressor(n_estimators=10, random_state=42).fit(X_treino, y_treino)
    
    preds_lr = agente_lr.predict(X_teste)
    preds_rf = agente_rf.predict(X_teste)
    
    erro_lr = mean_absolute_error(y_teste, preds_lr)
    erro_rf = mean_absolute_error(y_teste, preds_rf)
    
    vencedor = "Random Forest" if erro_rf < erro_lr else "Regressão Linear Múltipla"
    menor_erro = min(erro_rf, erro_lr)
    return vencedor, menor_erro, agente_lr, agente_rf

# ============================================================================
# 5. GERADOR DE EXCEL
# ============================================================================
def gerar_excel_nutri(dt_ini, dt_fim):
    output = io.BytesIO()
    params = {'d1': dt_ini, 'd2': dt_fim}
    df_detalhado = executar_sql("SELECT data, data_hora, alimento, quantidade, kcal, proteina, carbo, gordura FROM public.consumo WHERE data >= :d1 AND data <= :d2 ORDER BY data DESC", params, is_select=True)
    df_peso = executar_sql("SELECT data, peso_kg FROM public.peso WHERE data >= :d1 AND data <= :d2 ORDER BY data ASC", params, is_select=True)
    df_medidas = executar_sql("SELECT log_date as data, weight_kg as peso, waist_cm as cintura, body_fat_est as bf_estimado, notes FROM public.body_measurements WHERE log_date >= :d1 AND log_date <= :d2 ORDER BY log_date DESC", params, is_select=True)
    df_pressao = executar_sql("SELECT measurement_time as data_hora, systolic, diastolic, pulse FROM public.blood_pressure WHERE measurement_time >= :d1 AND measurement_time <= :d2 ORDER BY measurement_time DESC", params, is_select=True)
    df_treinos_raw = executar_sql("SELECT data, tipo, duracao_min, passos, passos_trabalho, passos_total_dia, distancia_km, calorias, bpm_medio FROM public.exercicios WHERE data >= :d1 AND data <= :d2 ORDER BY data DESC", params, is_select=True)

    if not df_detalhado.empty: df_macros = df_detalhado.groupby('data')[['kcal', 'proteina', 'carbo', 'gordura']].sum().reset_index()
    else: df_macros = pd.DataFrame(columns=['data', 'kcal', 'proteina', 'carbo', 'gordura'])

    if not df_treinos_raw.empty:
        df_treinos_agg = df_treinos_raw.groupby('data').agg({'duracao_min': 'sum', 'passos_total_dia': 'max', 'passos_trabalho': 'max', 'calorias': 'sum'}).reset_index()
        df_treinos_agg.columns = ['data', 'treino_min', 'passos_dia', 'passos_prof', 'treino_kcal']
    else: df_treinos_agg = pd.DataFrame(columns=['data', 'treino_min', 'passos_dia', 'passos_prof', 'treino_kcal'])

    if not df_macros.empty: df_macros['data'] = pd.to_datetime(df_macros['data']).dt.normalize()
    if not df_peso.empty:
        df_peso['data'] = pd.to_datetime(df_peso['data']).dt.normalize()
        df_peso = df_peso.drop_duplicates(subset='data', keep='last')
    if not df_treinos_agg.empty: df_treinos_agg['data'] = pd.to_datetime(df_treinos_agg['data']).dt.normalize()

    if not df_macros.empty or not df_peso.empty:
        df_resumo = pd.merge(df_macros, df_peso, on='data', how='outer')
        df_resumo = pd.merge(df_resumo, df_treinos_agg, on='data', how='left')
        df_resumo = df_resumo.sort_values('data', ascending=False)
        cols_order = ['data', 'peso_kg', 'kcal', 'proteina', 'carbo', 'gordura', 'treino_min', 'passos_dia', 'passos_prof', 'treino_kcal']
        for c in cols_order: 
            if c not in df_resumo.columns: df_resumo[c] = 0
        df_resumo = df_resumo[cols_order]
        df_resumo.columns = ['Data', 'Peso (kg)', 'Comida (kcal)', 'Prot (g)', 'Carb (g)', 'Gord (g)', 'Treino (min)', 'Passos Totais', 'Passos Prof', 'Gasto Treino (kcal)']
        df_resumo = df_resumo.dropna(subset=['Data'])
        df_resumo['Data'] = df_resumo['Data'].dt.strftime('%d/%m/%Y')
    else: df_resumo = pd.DataFrame(columns=['Data', 'Peso', 'Kcal', '...'])

    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df_resumo.to_excel(writer, sheet_name='1. Resumo Completo', index=False)
        df_detalhado.to_excel(writer, sheet_name='2. Alimentação Detalhada', index=False)
        df_treinos_raw.to_excel(writer, sheet_name='3. Treinos Brutos', index=False)
        df_medidas.to_excel(writer, sheet_name='4. Medidas', index=False)
        df_pressao.to_excel(writer, sheet_name='5. Pressão', index=False)
    return output.getvalue()

# ============================================================================
# 6. INTERFACE
# ============================================================================
st.title("🦁 Leo Tracker Pro")
data_hoje = get_now_br().date()
df_hoje = executar_sql("SELECT * FROM public.consumo WHERE data = :d", {'d': data_hoje}, is_select=True)

# SIDEBAR
st.sidebar.header("🎯 Status")

df_last_meal = executar_sql("SELECT data_hora FROM public.consumo ORDER BY data_hora DESC LIMIT 1", is_select=True)
tempo_jejum = "0h 0m"
if not df_last_meal.empty:
    last_dt = df_last_meal.iloc[0]['data_hora']
    if pd.notnull(last_dt):
        now_naive = get_now_br().replace(tzinfo=None)
        last_naive = last_dt.replace(tzinfo=None) if last_dt.tzinfo else last_dt
        diff_secs = (now_naive - last_naive).total_seconds()
        if diff_secs > 0:
            h = int(diff_secs // 3600)
            m = int((diff_secs % 3600) // 60)
            tempo_jejum = f"{h}h {m}m"

st.sidebar.metric("⏱️ Jejum Atual", tempo_jejum)

ultimo_peso_df = executar_sql("SELECT peso_kg FROM public.peso ORDER BY data DESC LIMIT 1", is_select=True)
peso_atual_sidebar = float(ultimo_peso_df.iloc[0]['peso_kg']) if not ultimo_peso_df.empty else 140.0
st.sidebar.metric("Peso Atual", f"{peso_atual_sidebar} kg", f"Meta: {METAS['peso_alvo']} kg")
st.sidebar.caption(f"Fator Ativ: {METAS['fator']}x")
st.sidebar.progress(min(max(0.0, (150 - peso_atual_sidebar) / (150 - METAS['peso_alvo'])), 1.0))

k_hoje = float(df_hoje['kcal'].sum()) if not df_hoje.empty else 0.0
p_hoje = float(df_hoje['proteina'].sum()) if not df_hoje.empty else 0.0
c_hoje = float(df_hoje['carbo'].sum()) if not df_hoje.empty else 0.0
g_hoje = float(df_hoje['gordura'].sum()) if not df_hoje.empty else 0.0

c1, c2, c3, c4 = st.columns(4)
c1.metric("🔥 Calorias", f"{int(k_hoje)}", f"Meta: {METAS['kcal']}")
c2.metric("🥩 Proteína", f"{int(p_hoje)}g", f"Meta: {METAS['prot']}g")
c3.metric("🍞 Carbo", f"{int(c_hoje)}g", f"Meta: {METAS['carb']}g")
c4.metric("🥑 Gordura", f"{int(g_hoje)}g", f"Meta: {METAS['gord']}g")
st.progress(min(k_hoje/METAS['kcal'], 1.0))
st.divider()

# ABAS
tab_dash, tab_daily, tab_treino, tab_hist, tab_medidas, tab_rel, tab_admin = st.tabs(["📊 Dash Pro", "📝 Diário", "🏃‍♂️ Treino", "📜 Histórico", "❤️ Saúde", "📄 Relatórios", "⚙️ Configurações"])

# --- ABA DASH PRO ---
with tab_dash:
    st.markdown("### 🧬 Leo's Analytics Hub (Visão Gerencial)")

    # FETCH DADOS AMPLIADO PARA O ORÁCULO
    DATA_INICIO_D = pd.to_datetime("2025-12-30").date()
    df_hist_d = executar_sql("""
        SELECT data, SUM(kcal) as tkcal, SUM(proteina) as tprot, SUM(carbo) as tcarb, SUM(gordura) as tgord,
               MIN(data_hora) as primeira_refeicao_dt, 
               MAX(data_hora) as ultima_refeicao_dt
        FROM public.consumo WHERE data >= :d GROUP BY data ORDER BY data ASC
    """, {"d": DATA_INICIO_D}, is_select=True)
    
    df_peso_d = executar_sql("SELECT * FROM public.peso ORDER BY data ASC", is_select=True)
    df_treino_d = executar_sql("""
        SELECT data, SUM(duracao_min) as t_min, MAX(passos_total_dia) as t_passos_total, SUM(passos) as t_passos_treino
        FROM public.exercicios WHERE data >= :d GROUP BY data ORDER BY data ASC
    """, {"d": DATA_INICIO_D}, is_select=True)
    df_bp_d = executar_sql("SELECT measurement_time, systolic, diastolic FROM public.blood_pressure WHERE measurement_time >= :d ORDER BY measurement_time ASC", {"d": DATA_INICIO_D}, is_select=True)

    if not df_peso_d.empty:
        df_peso_d['data_dt'] = pd.to_datetime(df_peso_d['data']).dt.date
        df_peso_d['media_movel_7d'] = df_peso_d['peso_kg'].rolling(window=7, min_periods=1).mean()
    
    if not df_hist_d.empty:
        df_hist_d['data_dt'] = pd.to_datetime(df_hist_d['data']).dt.date
        
    if not df_treino_d.empty:
        df_treino_d['data_dt'] = pd.to_datetime(df_treino_d['data']).dt.date
        df_treino_d['t_passos_rotina'] = df_treino_d['t_passos_total'] - df_treino_d['t_passos_treino']
        df_treino_d['t_passos_rotina'] = df_treino_d['t_passos_rotina'].clip(lower=0)

    st.subheader("📉 Tendência de Peso (Média 7 Dias)")
    if not df_peso_d.empty:
        fig_peso = go.Figure()
        fig_peso.add_trace(go.Scatter(x=df_peso_d['data'], y=df_peso_d['peso_kg'], mode='markers', name='Diário', marker=dict(color='#bdc3c7', size=6, opacity=0.5)))
        fig_peso.add_trace(go.Scatter(x=df_peso_d['data'], y=df_peso_d['media_movel_7d'], mode='lines', name='Média 7d', line=dict(color='#2c3e50', width=4)))
        fig_peso.add_hline(y=METAS['peso_alvo'], line_dash="dash", line_color="#27ae60", annotation_text="Meta Alvo")
        fig_peso.update_layout(height=350, margin=dict(l=10,r=10,t=30,b=10), showlegend=True, legend=dict(orientation="h", y=1.1))
        st.plotly_chart(fig_peso, use_container_width=True)
    else: st.info("Sem dados de peso suficientes.")
    
    st.divider()

    col_g2, col_g3 = st.columns(2)
    with col_g2:
        st.subheader("🍽️ Consumo Calórico vs Meta")
        if not df_hist_d.empty:
            colors = ['#27ae60' if k <= METAS['kcal'] else '#c0392b' for k in df_hist_d['tkcal']]
            fig_nutri = go.Figure()
            fig_nutri.add_trace(go.Bar(x=df_hist_d['data'], y=df_hist_d['tkcal'], name='Kcal', marker_color=colors))
            fig_nutri.add_hline(y=METAS['kcal'], line_dash="dash", line_color="#2c3e50", annotation_text="Teto")
            fig_nutri.update_layout(height=300, margin=dict(l=10,r=10,t=30,b=10), showlegend=False)
            st.plotly_chart(fig_nutri, use_container_width=True)
        else: st.info("Sem dados de consumo.")

    with col_g3:
        st.subheader("👟 Atividade Física")
        if not df_treino_d.empty:
            fig_treino = make_subplots(specs=[[{"secondary_y": True}]])
            fig_treino.add_trace(go.Bar(x=df_treino_d['data'], y=df_treino_d['t_passos_rotina'], name='Rotina', marker_color='#e67e22'), secondary_y=False)
            fig_treino.add_trace(go.Bar(x=df_treino_d['data'], y=df_treino_d['t_passos_treino'], name='Treino', marker_color='#8e44ad'), secondary_y=False)
            fig_treino.add_trace(go.Scatter(x=df_treino_d['data'], y=df_treino_d['t_min'], name='Minutos', mode='lines', line=dict(color='#f1c40f', width=2)), secondary_y=True)
            fig_treino.update_layout(barmode='stack', height=300, margin=dict(l=10,r=10,t=30,b=10), legend=dict(orientation="h", y=1.1, font=dict(size=10)))
            st.plotly_chart(fig_treino, use_container_width=True)
        else: st.info("Sem dados de treino.")

    st.divider()
    st.subheader("❤️ Pressão Arterial (Histórico)")
    if not df_bp_d.empty:
        fig_bp = go.Figure()
        fig_bp.add_trace(go.Scatter(x=df_bp_d['measurement_time'], y=df_bp_d['systolic'], name='Sistólica', line=dict(color='#e74c3c')))
        fig_bp.add_trace(go.Scatter(x=df_bp_d['measurement_time'], y=df_bp_d['diastolic'], name='Diastólica', line=dict(color='#3498db')))
        fig_bp.add_hrect(y0=120, y1=80, line_width=0, fillcolor="green", opacity=0.1, annotation_text="Ideal")
        fig_bp.update_layout(height=300, margin=dict(l=10,r=10,t=30,b=10), legend=dict(orientation="h", y=1.1))
        st.plotly_chart(fig_bp, use_container_width=True)
    else: st.info("Registre sua pressão na aba Saúde.")

    # --------------------------------------------------------
    # 🔮 O ORÁCULO METABÓLICO EMBUTIDO (Nova Feature)
    # --------------------------------------------------------
    st.divider()
    st.markdown("### 🔮 Oráculo Metabólico (Machine Learning)")
    
    if not df_hist_d.empty and not df_peso_d.empty:
        # Prepara a base de dados do oráculo (mescla consumo e pesos)
        df_peso_unico = df_peso_d.drop_duplicates(subset=['data_dt'], keep='last').copy()
        df_merged_pred = pd.merge(df_hist_d, df_peso_unico[['data_dt', 'peso_kg']], on='data_dt', how='inner')
        
        # Calcula horas de jejum para o modelo preditivo
        df_merged_pred['primeira_refeicao_dt'] = pd.to_datetime(df_merged_pred['primeira_refeicao_dt'])
        df_merged_pred['ultima_refeicao_dt'] = pd.to_datetime(df_merged_pred['ultima_refeicao_dt'])
        df_merged_pred['ultima_ref_ontem'] = df_merged_pred['ultima_refeicao_dt'].shift(1)
        df_merged_pred['jejum_h'] = (df_merged_pred['primeira_refeicao_dt'] - df_merged_pred['ultima_ref_ontem']).dt.total_seconds() / 3600
        df_merged_pred['jejum_h'] = df_merged_pred['jejum_h'].apply(lambda x: x if 8 <= x <= 48 else np.nan)
        
        # O Delta que queremos prever: quanto o peso varia de um dia pro outro
        df_merged_pred['peso_amanha'] = df_merged_pred['peso_kg'].shift(-1)
        df_merged_pred['delta_peso_kg'] = df_merged_pred['peso_amanha'] - df_merged_pred['peso_kg']
        
        df_model = df_merged_pred.dropna(subset=['delta_peso_kg', 'jejum_h', 'tprot', 'tcarb', 'tgord']).copy()
        
        if len(df_model) > 5:
            vencedor, menor_erro, mod_lr, mod_rf = torneio_el_farol(df_model)
            if vencedor:
                st.info(f"**Agente Preditivo Ativo:** {vencedor} (Margem de erro: ±{menor_erro*1000:.0f}g)")
                
                c_p1, c_p2, c_p3, c_p4 = st.columns(4)
                sim_jej = c_p1.slider("Jejum (h)", 8.0, 24.0, 16.0, 0.5)
                sim_prot = c_p2.number_input("Prot (g)", value=int(METAS['prot']))
                sim_carb = c_p3.number_input("Carbo (g)", value=int(METAS['carb']))
                sim_gord = c_p4.number_input("Gord (g)", value=int(METAS['gord']))
                
                entrada_sim = pd.DataFrame({'jejum_h': [sim_jej], 'tprot': [sim_prot], 'tcarb': [sim_carb], 'tgord': [sim_gord]})
                pred_delta = mod_rf.predict(entrada_sim)[0] if vencedor == "Random Forest" else mod_lr.predict(entrada_sim)[0]
                
                st.metric("Predição de Peso para Amanhã (Balança)", f"{pred_delta*1000:+.0f} g", delta_color="inverse")
        else:
            st.caption("⏳ O Oráculo precisa de pelo menos 10 dias consecutivos de dados (Consumo + Jejum + Peso) para iniciar as previsões preditivas.")
    else:
        st.caption("⏳ Base de dados insuficiente para o Oráculo.")

# --- ABA DIÁRIO ---
with tab_daily:
    with st.container():
        st.markdown("##### ⚖️ Peso de Hoje")
        with st.form("form_peso_diario_top"):
            cp1, cp2, cp3 = st.columns([1, 1, 2])
            d_peso = cp1.date_input("Data", value=data_hoje, label_visibility="collapsed")
            p_val = cp2.number_input("Peso (kg)", 40.0, 200.0, step=0.1, value=peso_atual_sidebar, label_visibility="collapsed")
            if cp3.form_submit_button("💾 Salvar Peso", use_container_width=True):
                ok = executar_sql("INSERT INTO public.peso (data, peso_kg) VALUES (:d, :p)", {'d': d_peso, 'p': p_val})
                if ok: st.cache_resource.clear(); st.rerun()
    st.divider()

    # --------------------------------------------------------
    # 🍎 O SMART BOX (Input Unificado IA / JSON)
    # --------------------------------------------------------
    st.write("### 🍎 O que você comeu?")
    st.info("Digite o que comeu ou cole diretamente o JSON no campo abaixo. O sistema saberá o que fazer.")
    texto_input = st.text_area("Descrição ou cole o JSON", height=120, label_visibility="collapsed", placeholder="Ex: 2 ovos com queijo e café preto\n\nOU cole um JSON como:\n[\n  {\"alimento\": \"Carne\", \"quantidade_g\": 100...}\n]")
    
    if st.button("🚀 Processar Alimentação", use_container_width=True):
        if texto_input:
            is_json = False
            lista = None
            
            # Tenta decodificar como JSON primeiro
            try:
                cleaned = texto_input.replace('```json', '').replace('```', '').strip()
                # Localiza se é uma lista [...] ou objeto {...}
                start, end = cleaned.find('['), cleaned.rfind(']')
                if start == -1 and cleaned.startswith('{'): 
                    start, end = cleaned.find('{'), cleaned.rfind('}')
                
                if start != -1 and end != -1: 
                    cleaned = cleaned[start:end+1]
                
                lista = json.loads(cleaned)
                is_json = True
            except:
                pass # Se falhar, é texto normal e vai pra IA

            if is_json:
                with st.spinner("📦 Formato JSON detectado! Registrando direto no banco..."):
                    try:
                        for item in (lista if isinstance(lista, list) else [lista]):
                            dt = item.get('data') if item.get('data') else data_hoje
                            k_final = max((float(item.get('p',0))*4 + float(item.get('c',0))*4 + float(item.get('g',0))*9), float(item.get('kcal', 0)))
                            params = {'dt': dt, 'ali': item.get('alimento'), 'qtd': item.get('quantidade_g'), 'kcal': k_final, 'prot': item.get('p'), 'carb': item.get('c'), 'gord': item.get('g'), 'glut': item.get('gluten')}
                            executar_sql("INSERT INTO public.consumo (data, alimento, quantidade, kcal, proteina, carbo, gordura, gluten) VALUES (:dt, :ali, :qtd, :kcal, :prot, :carb, :gord, :glut)", params)
                        st.success("Refeição(ões) salva(s) com sucesso!"); st.cache_resource.clear(); st.rerun()
                    except Exception as e: 
                        st.error(f"Erro ao processar JSON: {e}")
            else:
                api_key = st.secrets.get("GROQ_API_KEY")
                if not api_key: 
                    st.error("Chave da API GROQ não configurada no Secrets!")
                else:
                    with st.spinner("🧠 Texto comum detectado! Consultando a IA Llama..."):
                        ok_ia, res = processar_texto_ia(texto_input, api_key)
                        if ok_ia:
                            st.success(res.get('analise'))
                            for item in res.get('alimentos', []):
                                k_final = max((item.get('p',0)*4 + item.get('c',0)*4 + item.get('g',0)*9), float(item.get('kcal', 0)))
                                params = {'dt': item.get('data') or data_hoje, 'ali': item.get('alimento'), 'qtd': item.get('quantidade_g'), 'kc': k_final, 'pr': item.get('p'), 'ca': item.get('c'), 'go': item.get('g'), 'gl': item.get('gluten')}
                                executar_sql("INSERT INTO public.consumo (data, alimento, quantidade, kcal, proteina, carbo, gordura, gluten) VALUES (:dt, :ali, :qtd, :kc, :pr, :ca, :go, :gl)", params)
                            st.cache_resource.clear(); st.rerun()
                        else:
                            st.error(res)

    st.subheader("Hoje")
    if not df_hoje.empty:
        for i, row in df_hoje.iterrows():
            c1, c2, c3 = st.columns([3, 2, 0.5])
            c1.markdown(f"**{row['alimento']}**")
            c2.caption(f"{int(row['kcal'])} kcal | P:{int(row['proteina'])} G:{int(row['gordura'])}")
            if c3.button("❌", key=f"d_{row['id']}"):
                executar_sql("DELETE FROM public.consumo WHERE id=:id", {'id': row['id']})
                st.cache_resource.clear(); st.rerun()
            st.markdown("---")
    else: st.info("Nada registrado hoje.")

# --- ABA TREINO ---
with tab_treino:
    st.markdown("### 🏃‍♂️ Monitoramento de Treino (Iron N1)")
    df_treino_hoje = executar_sql("SELECT * FROM public.exercicios WHERE data = :d ORDER BY id DESC", {'d': data_hoje}, is_select=True)
    df_fechamento = df_treino_hoje[df_treino_hoje['tipo'] == 'Fechamento Diário']
    df_atividades = df_treino_hoje[df_treino_hoje['tipo'] != 'Fechamento Diário']

    min_treino_hoje = int(df_atividades['duracao_min'].sum())
    cal_treino_hoje = int(df_atividades['calorias'].sum())
    passos_treino_hoje = int(df_atividades['passos'].sum())

    if not df_fechamento.empty: passos_total_n1 = int(df_fechamento.iloc[0]['passos_total_dia'])
    else: passos_total_n1 = 0

    if passos_total_n1 > 0: passos_prof_rotina = max(0, passos_total_n1 - passos_treino_hoje)
    else: passos_prof_rotina = 0

    pct_treino = min(min_treino_hoje / 120.0, 1.0)
    c_m1, c_m2, c_m3 = st.columns(3)
    c_m1.metric("⏱️ Tempo Treino", f"{min_treino_hoje} min", "Meta: 120 min")
    c_m2.metric("👣 Passos Treino", f"{passos_treino_hoje}", f"Atividades registradas")
    c_m3.metric("🏫 Passos Rotina (Prof)", f"{passos_prof_rotina}", f"Total Dia: {passos_total_n1}")
    st.progress(pct_treino)
    st.divider()

    st.subheader("🏁 Fechamento do Dia")
    st.info("Insira apenas o valor final que aparece no seu relógio.")
    with st.form("form_fechamento_simples"):
        col_f1, col_f2 = st.columns([2, 1])
        with col_f1: input_total_dia = st.number_input("Total de Passos (Iron N1)", 0, 60000, passos_total_n1, help="Olhe o relógio antes de dormir.")
        with col_f2:
            st.write(""); st.write("") 
            btn_save = st.form_submit_button("💾 Salvar Fechamento", use_container_width=True)

        if btn_save:
            resto_calculado = max(0, input_total_dia - passos_treino_hoje)
            executar_sql("DELETE FROM public.exercicios WHERE data = :d AND tipo = 'Fechamento Diário'", {'d': data_hoje})
            executar_sql("""
                INSERT INTO public.exercicios (data, tipo, duracao_min, passos, passos_total_dia, passos_trabalho, calorias, observacoes)
                VALUES (:d, 'Fechamento Diário', 0, 0, :pt, :ptr, 0, 'Total Relógio')
            """, {'d': data_hoje, 'pt': input_total_dia, 'ptr': resto_calculado})
            st.success(f"Fechado! Total: {input_total_dia} (Sendo {resto_calculado} de Rotina)"); st.rerun()

    st.markdown("---")

    st.subheader("➕ Adicionar Treino / Caminhada")
    with st.form("form_treino"):
        c_tr1, c_tr2 = st.columns(2)
        tipo = c_tr1.selectbox("Atividade", ["Caminhada Indoor", "Caminhada Rua (Transporte)", "Musculação", "Bicicleta Ergométrica", "Outro"])
        duracao = c_tr2.number_input("Duração (min)", 0, 300, 30)
        c_tr3, c_tr4, c_tr5 = st.columns(3)
        passos = c_tr3.number_input("Passos (Desta atividade)", 0, 20000, 0)
        dist_est = c_tr4.number_input("Distância (km)", 0.0, 50.0, 0.0)
        cal = c_tr5.number_input("Calorias (Relógio)", 0, 2000, 0)
        bpm = st.number_input("BPM Médio (Opcional)", 0, 200, 0)
        obs = st.text_input("Observações")

        if st.form_submit_button("💾 Registrar Atividade", use_container_width=True):
            executar_sql("""
                INSERT INTO public.exercicios (data, tipo, duracao_min, passos, distancia_km, calorias, bpm_medio, observacoes)
                VALUES (:d, :t, :dm, :p, :dk, :c, :bpm, :o)
            """, {'d': data_hoje, 't': tipo, 'dm': duracao, 'p': passos, 'dk': dist_est, 'c': cal, 'bpm': bpm, 'o': obs})
            st.success("Atividade registrada!"); st.rerun()

    if not df_treino_hoje.empty:
        st.write("#### 📝 Registros de Hoje")
        for i, row in df_treino_hoje.iterrows():
            with st.container():
                ct1, ct2, ct3 = st.columns([3, 2, 0.5])
                if row['tipo'] == 'Fechamento Diário':
                    ct1.markdown(f"🏁 **TOTAL DO DIA**")
                    ct2.caption(f"Relógio: **{row['passos_total_dia']}** | Rotina (Calc): **{row['passos_trabalho']}**")
                else:
                    ct1.markdown(f"🏃‍♂️ **{row['tipo']}**")
                    ct2.caption(f"{row['duracao_min']} min | {row['passos']} passos | {row['calorias']} kcal")

                if ct3.button("🗑️", key=f"del_tr_{row['id']}"):
                    executar_sql("DELETE FROM public.exercicios WHERE id=:id", {'id': row['id']})
                    st.rerun()
                st.markdown("---")

# --- ABA HISTÓRICO ---
with tab_hist:
    st.header("Histórico Completo")
    df_all = executar_sql("SELECT * FROM public.consumo ORDER BY data DESC LIMIT 50", is_select=True)
    if not df_all.empty: st.dataframe(df_all)

# --- ABA SAÚDE ---
with tab_medidas:
    st.subheader("🫀 Pressão Arterial")
    with st.form("bp_form"):
        c1, c2, c3 = st.columns(3)
        sys = c1.number_input("Sistólica", 90, 200, 120); dia = c2.number_input("Diastólica", 50, 130, 80); pul = c3.number_input("Pulso", 40, 200, 75)
        if st.form_submit_button("Salvar Pressão"):
            ok = executar_sql("INSERT INTO public.blood_pressure (systolic, diastolic, pulse, notes) VALUES (:s, :d, :p, 'App')", {'s': sys, 'd': dia, 'p': pul})
            if ok: st.rerun()
    st.divider(); st.subheader("📏 Avaliação Corporal")
    with st.form("medidas_form"):
        d_med = st.date_input("Data", value=data_hoje)
        p_input = st.number_input("Peso Atual (kg)", 40.0, 200.0, step=0.1, value=peso_atual_sidebar)
        waist = st.number_input("Cintura (cm)", 50.0, 200.0, step=0.5, value=METAS['last_waist'])
        bf_weltman = calc_bf_weltman_obese(waist, p_input, METAS['altura'], METAS['genero'])
        st.info(f"🧬 **BF Weltman: {bf_weltman:.1f}%**")
        if st.form_submit_button("Salvar Avaliação"):
            params = {'dt': d_med, 'w': p_input, 'wa': waist, 'ne': METAS['last_neck'], 'hi': METAS['last_hip'], 'bf_est': bf_weltman, 'f_pec': 0, 'f_abd': 0, 'f_thi': 0, 'f_tri': 0, 'bf_pol': 0, 'bf_wel': bf_weltman, 'nt': 'Weltman Simples'}
            executar_sql("INSERT INTO public.body_measurements (log_date, weight_kg, waist_cm, neck_cm, hip_cm, body_fat_est, fold_chest, fold_abdominal, fold_thigh, fold_triceps, body_fat_pollock, body_fat_weltman, notes) VALUES (:dt, :w, :wa, :ne, :hi, :bf_est, :f_pec, :f_abd, :f_thi, :f_tri, :bf_pol, :bf_wel, :nt)", params)
            executar_sql("INSERT INTO public.peso (data, peso_kg) VALUES (:dt, :w)", {'dt': d_med, 'w': p_input})
            executar_sql("UPDATE public.perfil SET ultima_cintura=:wa WHERE id=1", {'wa': waist})
            st.cache_resource.clear(); st.rerun()

# --- ABA RELATÓRIOS ---
with tab_rel:
    st.header("📄 Relatórios")
    col_d1, col_d2 = st.columns(2)
    dt_ini = col_d1.date_input("Data Inicial", value=data_hoje - timedelta(days=30)); dt_fim = col_d2.date_input("Data Final", value=data_hoje)
    if st.button("📊 Baixar Relatório Completo (.xlsx)"):
        try:
            excel_data = gerar_excel_nutri(dt_ini, dt_fim)
            st.download_button(label="📥 Download", data=excel_data, file_name=f"Relatorio_Nutri_Leo.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        except Exception as e: st.error(f"Erro: {e}")

# --- ABA ADMIN ---
with tab_admin:
    st.header("⚙️ Configurações")
    with st.form("form_metas_completo"):
        st.subheader("Fator de Atividade (Basal Multiplier)")
        st.caption("1.2 = Sedentário/Férias | 1.35 = Leve/Aulas | 1.55 = Moderado/Treino Pesado")
        n_fator = st.number_input("Fator Atual", 1.0, 2.0, METAS['fator'], 0.05)
        st.divider()
        c_k1, c_k2 = st.columns(2); n_kcal = c_k1.number_input("Calorias", value=METAS['kcal']); n_prot = c_k2.number_input("Proteína", value=METAS['prot'])
        c_k3, c_k4 = st.columns(2); n_carb = c_k3.number_input("Carbo", value=METAS['carb']); n_gord = c_k4.number_input("Gordura", value=METAS['gord'])
        c_p1, c_p2 = st.columns(2); n_peso_alvo = c_p1.number_input("Peso Alvo", value=METAS['peso_alvo']); n_ritmo = c_p2.number_input("Ritmo", value=METAS['ritmo'])
        if st.form_submit_button("💾 Salvar Metas"):
            executar_sql("UPDATE public.perfil SET meta_kcal=:mk, meta_proteina=:mp, meta_carbo=:mc, meta_gordura=:mg, meta_peso_alvo=:mpa, ritmo_semanal=:rit, fator_atividade=:fat WHERE id=1", {'mk': n_kcal, 'mp': n_prot, 'mc': n_carb, 'mg': n_gord, 'mpa': n_peso_alvo, 'rit': n_ritmo, 'fat': n_fator})
            st.cache_resource.clear(); st.rerun()

st.caption("Leo Tracker Pro v8.8 | ML Prediction & Smart JSON Flow 🚀")
