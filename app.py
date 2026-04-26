import streamlit as st
import pandas as pd
import numpy as np
from sqlalchemy import create_engine, text
from datetime import datetime, timedelta
import json
import pytz
from groq import Groq
import io
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import statsmodels.api as sm
from statsmodels.formula.api import ols
from sklearn.linear_model import LinearRegression
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error
import random

# ============================================================================
# 1. CONFIGURAÇÃO GLOBAL
# ============================================================================
st.set_page_config(page_title="Leo Tracker Pro", page_icon="🦁", layout="wide")

# Session State — defaults do AG (deve estar no topo, antes do auth)
_AG_DEFAULTS = {
    'win_peso': 3, 'win_jej': 1, 'win_prot': 3, 'win_carb': 2,
    'win_gord': 1, 'win_passos': 2, 'win_agua': 2, 'win_int': 1,
    'win_bristol': 1, 'win_sono_h': 1, 'win_sono_q': 1
}
for _k, _v in _AG_DEFAULTS.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v

st.markdown("""
    <style>
    div[data-testid="stMetric"] {
        background-color: #f0f2f6; padding: 15px; border-radius: 12px;
        border: 1px solid #e0e0e0; box-shadow: 2px 2px 5px rgba(0,0,0,0.05);
    }
    @media (prefers-color-scheme: dark) {
        div[data-testid="stMetric"] { background-color: #262730; border: 1px solid #464b5c; }
    }
    h1, h2, h3 { font-family: 'Helvetica', sans-serif; font-weight: 700; }
    </style>
""", unsafe_allow_html=True)

def get_now_br():
    return datetime.now(pytz.timezone('America/Sao_Paulo'))

# ============================================================================
# 2. AUTENTICAÇÃO (ÚNICA — COBRE TODA A APLICAÇÃO)
# ============================================================================
def check_password():
    if st.session_state.get("password_correct", False):
        return True
    st.title("🦁 Leo Tracker Pro")
    password = st.text_input("Senha de Acesso:", type="password")
    if st.button("Entrar"):
        if password == st.secrets.get("PASSWORD", "admin"):
            st.session_state["password_correct"] = True
            st.rerun()
        else:
            st.error("Senha incorreta!")
    return False

if not check_password():
    st.stop()

# ============================================================================
# 3. CONEXÃO — ÚNICO ENGINE COMPARTILHADO
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
# 4. HELPERS & CÁLCULOS
# ============================================================================
def calc_bf_weltman(waist, weight_kg, height_cm, gender):
    if waist <= 0 or weight_kg <= 0: return 0.0
    try:
        if gender == 'Masculino':
            return (0.31457 * waist) - (0.10969 * weight_kg) + 10.8336
        return (0.11077 * waist) - (0.17666 * height_cm) + (0.14354 * weight_kg) + 51.03301
    except: return 0.0

def processar_texto_ia(texto_usuario, api_key):
    client = Groq(api_key=api_key)
    prompt_system = f"""
Aja como Nutricionista Matemático. Hoje: {get_now_br().strftime('%Y-%m-%d')}.
DIRETRIZES:
1. Identifique o alimento e sua densidade calórica padrão (kcal/g).
2. MULTIPLIQUE a densidade pelo peso informado.
3. GORDURA OCULTA: Se for fritura/grelhado, adicione gordura extra.
4. MICRONUTRIENTES: Estime Ferro, B12, Zinco e Magnésio por engenharia reversa.
SAÍDA: Retorne APENAS JSON válido.
Formato: {{"analise": "Texto curto", "alimentos": [{{"data": "YYYY-MM-DD", "alimento": "Nome",
"quantidade_g": 0, "kcal": 0, "p": 0, "c": 0, "g": 0, "gluten": "txt",
"ferro_mg": 0, "b12_mcg": 0, "zinco_mg": 0, "magnesio_mg": 0}}]}}
"""
    try:
        completion = client.chat.completions.create(
            messages=[{"role": "system", "content": prompt_system},
                      {"role": "user", "content": texto_usuario}],
            model="llama-3.3-70b-versatile",
            response_format={"type": "json_object"}
        )
        raw = completion.choices[0].message.content.replace("```json","").replace("```","").strip()
        s, e = raw.find('{'), raw.rfind('}')
        if s != -1 and e != -1: raw = raw[s:e+1]
        content = json.loads(raw)
        if isinstance(content, list): content = {"analise": "Processado", "alimentos": content}
        return True, content
    except Exception as ex:
        return False, f"Erro: {str(ex)}"

def torneio_el_farol(df_modelo, features, target_col):
    """Versão completa com tabela de transparência (auditoria dos agentes)."""
    X = df_modelo[features]
    y = df_modelo[target_col]
    if len(df_modelo) < 10:
        return None, None, None, None, None
    X_tr, X_te = X[:-5], X[-5:]
    y_tr, y_te = y[:-5], y[-5:]
    datas_te = df_modelo['data_dt'].iloc[-5:] if 'data_dt' in df_modelo.columns else df_modelo.index[-5:]

    mod_lr = LinearRegression().fit(X_tr, y_tr)
    mod_rf = RandomForestRegressor(n_estimators=10, random_state=42).fit(X_tr, y_tr)

    preds_lr = mod_lr.predict(X_te)
    preds_rf = mod_rf.predict(X_te)
    erro_lr  = mean_absolute_error(y_te, preds_lr)
    erro_rf  = mean_absolute_error(y_te, preds_rf)

    vencedor   = "Random Forest" if erro_rf < erro_lr else "Regressão Linear Múltipla"
    menor_erro = min(erro_rf, erro_lr)

    df_transp = pd.DataFrame({
        'Data':            datas_te,
        'Real (g)':        y_te.values * 1000,
        'Previsto LR (g)': preds_lr * 1000,
        'Previsto RF (g)': preds_rf * 1000,
    })
    df_transp['Erro LR (g)'] = abs(df_transp['Real (g)'] - df_transp['Previsto LR (g)'])
    df_transp['Erro RF (g)'] = abs(df_transp['Real (g)'] - df_transp['Previsto RF (g)'])
    return vencedor, menor_erro, mod_lr, mod_rf, df_transp

# ============================================================================
# 5. INICIALIZAÇÃO DO BANCO
# ============================================================================
def inicializar_banco():
    executar_sql("""CREATE TABLE IF NOT EXISTS public.consumo (
        id SERIAL PRIMARY KEY, data DATE, alimento TEXT, quantidade REAL,
        kcal REAL, proteina REAL, carbo REAL, gordura REAL,
        gluten TEXT DEFAULT 'Não informado'
    );""")
    try: executar_sql("ALTER TABLE public.consumo ADD COLUMN IF NOT EXISTS data_hora TIMESTAMP DEFAULT CURRENT_TIMESTAMP;")
    except: pass
    for c in ['ferro_mg', 'b12_mcg', 'zinco_mg', 'magnesio_mg']:
        try: executar_sql(f"ALTER TABLE public.consumo ADD COLUMN IF NOT EXISTS {c} REAL DEFAULT 0;")
        except: pass

    executar_sql("CREATE TABLE IF NOT EXISTS public.peso (id SERIAL PRIMARY KEY, data DATE, peso_kg REAL);")

    executar_sql("""CREATE TABLE IF NOT EXISTS public.exercicios (
        id SERIAL PRIMARY KEY, data DATE, tipo TEXT, duracao_min INT, passos INT,
        distancia_km REAL, calorias REAL, bpm_medio INT, observacoes TEXT
    );""")
    try:
        executar_sql("ALTER TABLE public.exercicios ADD COLUMN IF NOT EXISTS passos_trabalho INT DEFAULT 0;")
        executar_sql("ALTER TABLE public.exercicios ADD COLUMN IF NOT EXISTS passos_total_dia INT DEFAULT 0;")
    except: pass

    executar_sql("""CREATE TABLE IF NOT EXISTS public.perfil (
        id SERIAL PRIMARY KEY, genero TEXT, idade INT, altura_cm INT, atividade TEXT,
        objetivo TEXT, ritmo_semanal REAL, meta_kcal REAL, meta_proteina REAL,
        meta_carbo REAL, meta_gordura REAL, meta_peso_alvo REAL
    );""")
    try: executar_sql("ALTER TABLE public.perfil ADD COLUMN IF NOT EXISTS fator_atividade REAL DEFAULT 1.2;")
    except: pass
    for c in ['ultimo_pescoco', 'ultima_cintura', 'ultimo_quadril']:
        try: executar_sql(f"ALTER TABLE public.perfil ADD COLUMN IF NOT EXISTS {c} REAL;")
        except: pass

    executar_sql("""CREATE TABLE IF NOT EXISTS public.body_measurements (
        id SERIAL PRIMARY KEY, log_date DATE NOT NULL, weight_kg REAL, waist_cm REAL,
        neck_cm REAL, hip_cm REAL, body_fat_est REAL, notes TEXT,
        fold_chest REAL, fold_abdominal REAL, fold_thigh REAL, fold_triceps REAL,
        body_fat_pollock REAL, body_fat_weltman REAL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );""")
    executar_sql("""CREATE TABLE IF NOT EXISTS public.blood_pressure (
        id SERIAL PRIMARY KEY, measurement_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        systolic INT, diastolic INT, pulse INT, notes TEXT
    );""")
    executar_sql("CREATE TABLE IF NOT EXISTS public.sono (data DATE PRIMARY KEY, horas REAL, qualidade INT);")
    executar_sql("CREATE TABLE IF NOT EXISTS public.hidratacao (data DATE PRIMARY KEY, agua_ml INT DEFAULT 0, cafe_ml INT DEFAULT 0);")
    executar_sql("CREATE TABLE IF NOT EXISTS public.evacuacao (data DATE PRIMARY KEY, vezes INT DEFAULT 0, bristol INT DEFAULT 4);")

def get_metas_do_banco():
    try:
        df = executar_sql("SELECT * FROM public.perfil WHERE id = 1", is_select=True)
        if not df.empty:
            r = df.iloc[0]
            return {
                "kcal": int(r.get('meta_kcal', 1638)),      "prot": int(r.get('meta_proteina', 108)),
                "carb": int(r.get('meta_carbo', 164)),       "gord": int(r.get('meta_gordura', 67)),
                "peso_alvo": float(r.get('meta_peso_alvo', 120.0)),
                "ritmo":     float(r.get('ritmo_semanal', 0.8)),
                "altura":    int(r.get('altura_cm', 178)),   "idade": int(r.get('idade', 41)),
                "genero":    r.get('genero', 'Masculino'),
                "fator":     float(r.get('fator_atividade') or 1.2),
                "last_waist": float(r.get('ultima_cintura') or 133.0),
                "last_neck":  float(r.get('ultimo_pescoco') or 53.0),
                "last_hip":   float(r.get('ultimo_quadril') or 122.0),
            }
    except: pass
    return {"kcal":1638,"prot":108,"carb":164,"gord":67,"peso_alvo":120.0,"ritmo":0.8,
            "altura":178,"idade":41,"genero":"Masculino","fator":1.2,
            "last_waist":133.0,"last_neck":53.0,"last_hip":122.0}

inicializar_banco()
METAS = get_metas_do_banco()

# ============================================================================
# 6. ETL COMPARTILHADO — roda uma vez após auth
# ============================================================================
hoje         = get_now_br().date()
DATA_INICIO  = pd.to_datetime("2025-12-30").date()
fator_atv    = METAS['fator']

df_peso_raw  = executar_sql("SELECT * FROM public.peso ORDER BY data ASC", is_select=True)
df_medidas   = executar_sql("SELECT * FROM public.body_measurements ORDER BY log_date ASC", is_select=True)
df_bp        = executar_sql("SELECT * FROM public.blood_pressure ORDER BY measurement_time ASC", is_select=True)

df_hist = executar_sql("""
    SELECT data,
           SUM(kcal)       AS tkcal,  SUM(proteina) AS tprot,
           SUM(carbo)      AS tcarb,  SUM(gordura)  AS tgord,
           SUM(quantidade) AS tqtd,
           MIN(data_hora)  AS primeira_refeicao_dt,
           MAX(data_hora)  AS ultima_refeicao_dt
    FROM public.consumo WHERE data >= :d GROUP BY data ORDER BY data ASC
""", {"d": DATA_INICIO}, is_select=True)

df_treino_etl = executar_sql("""
    SELECT data,
           SUM(duracao_min)       AS t_min,
           SUM(passos_trabalho)   AS t_passos_trabalho,
           SUM(calorias)          AS t_cal_out
    FROM public.exercicios WHERE data >= :d GROUP BY data ORDER BY data ASC
""", {"d": DATA_INICIO}, is_select=True)

df_hidra_etl = executar_sql(
    "SELECT data, SUM(agua_ml) AS tagua FROM public.hidratacao WHERE data >= :d GROUP BY data ORDER BY data ASC",
    {"d": DATA_INICIO}, is_select=True)
df_evac_etl = executar_sql(
    "SELECT data, SUM(vezes) AS tintestino, MAX(bristol) AS tbristol FROM public.evacuacao WHERE data >= :d GROUP BY data ORDER BY data ASC",
    {"d": DATA_INICIO}, is_select=True)
df_sono_etl = executar_sql(
    "SELECT data, MAX(horas) AS sono_h, MAX(qualidade) AS sono_q FROM public.sono WHERE data >= :d GROUP BY data ORDER BY data ASC",
    {"d": DATA_INICIO}, is_select=True)

df_hoje_comida = executar_sql("SELECT * FROM public.consumo WHERE data = :d", {"d": hoje}, is_select=True)
df_hoje_treino = executar_sql("SELECT * FROM public.exercicios WHERE data = :d", {"d": hoje}, is_select=True)

peso_atual = float(df_peso_raw.iloc[-1]['peso_kg']) if not df_peso_raw.empty else 140.0

# ── Pipeline de merge ────────────────────────────────────────────────────────
df_merged = pd.DataFrame()

if not df_hist.empty and not df_peso_raw.empty:
    df_hist['data_dt']     = pd.to_datetime(df_hist['data']).dt.date
    df_peso_raw['data_dt'] = pd.to_datetime(df_peso_raw['data']).dt.date
    df_peso_unico          = df_peso_raw.drop_duplicates(subset=['data_dt'], keep='last')
    df_merged              = pd.merge(df_hist, df_peso_unico[['data_dt','peso_kg']], on='data_dt', how='left').ffill()

    if df_merged['peso_kg'].isnull().any():
        df_merged['peso_kg'] = df_merged['peso_kg'].bfill().fillna(peso_atual)

    # Treino
    if not df_treino_etl.empty:
        df_treino_etl['data_dt'] = pd.to_datetime(df_treino_etl['data']).dt.date
        agg_tr = df_treino_etl.groupby('data_dt')[['t_min','t_passos_trabalho','t_cal_out']].sum().reset_index()
        df_merged = pd.merge(df_merged, agg_tr, on='data_dt', how='left')
    for c in ['t_min','t_passos_trabalho','t_cal_out']:
        if c not in df_merged.columns: df_merged[c] = 0
        df_merged[c] = df_merged[c].fillna(0)

    # Hidratação
    if not df_hidra_etl.empty:
        df_hidra_etl['data_dt'] = pd.to_datetime(df_hidra_etl['data']).dt.date
        agg_ag = df_hidra_etl.groupby('data_dt')[['tagua']].sum().reset_index()
        df_merged = pd.merge(df_merged, agg_ag, on='data_dt', how='left')
    if 'tagua' not in df_merged.columns: df_merged['tagua'] = 0
    df_merged['tagua'] = df_merged['tagua'].fillna(0)

    # Evacuação
    if not df_evac_etl.empty:
        df_evac_etl['data_dt'] = pd.to_datetime(df_evac_etl['data']).dt.date
        agg_ev = df_evac_etl.groupby('data_dt').agg({'tintestino':'sum','tbristol':'max'}).reset_index()
        df_merged = pd.merge(df_merged, agg_ev, on='data_dt', how='left')
    for c in ['tintestino','tbristol']:
        if c not in df_merged.columns: df_merged[c] = 0
        df_merged[c] = df_merged[c].fillna(0)

    # Sono
    if not df_sono_etl.empty:
        df_sono_etl['data_dt'] = pd.to_datetime(df_sono_etl['data']).dt.date
        agg_sn = df_sono_etl.groupby('data_dt')[['sono_h','sono_q']].max().reset_index()
        df_merged = pd.merge(df_merged, agg_sn, on='data_dt', how='left')
    if 'sono_h' not in df_merged.columns: df_merged['sono_h'] = 7.0
    if 'sono_q' not in df_merged.columns: df_merged['sono_q'] = 3
    df_merged['sono_h'] = df_merged['sono_h'].fillna(7.0)
    df_merged['sono_q'] = df_merged['sono_q'].fillna(3)

    # Cálculos energéticos
    idade, altura = METAS['idade'], METAS['altura']
    df_merged['get_basal']    = ((10 * df_merged['peso_kg']) + (6.25 * altura) - (5 * idade) + 5) * fator_atv
    df_merged['get_total']    = df_merged['get_basal'] + df_merged['t_cal_out']
    df_merged['deficit_real'] = df_merged['get_total'] - df_merged['tkcal']

    # Hacker's Diet — EWMA (sinal vs ruído)
    df_merged['peso_tendencia'] = df_merged['peso_kg'].ewm(span=10, adjust=False).mean()

    # Cintura
    if not df_medidas.empty:
        df_medidas['data_dt'] = pd.to_datetime(df_medidas['log_date']).dt.date
        df_med_agg = df_medidas.groupby('data_dt')[['waist_cm']].last().reset_index()
        df_merged  = pd.merge(df_merged, df_med_agg, on='data_dt', how='left')
        df_merged['waist_cm'] = df_merged['waist_cm'].ffill()
    else:
        df_merged['waist_cm'] = np.nan

# ============================================================================
# 7. GERADOR DE EXCEL
# ============================================================================
def gerar_excel_nutri(dt_ini, dt_fim):
    output = io.BytesIO()
    p = {'d1': dt_ini, 'd2': dt_fim}
    df_det  = executar_sql("SELECT data, data_hora, alimento, quantidade, kcal, proteina, carbo, gordura, ferro_mg, b12_mcg, zinco_mg, magnesio_mg FROM public.consumo WHERE data >= :d1 AND data <= :d2 ORDER BY data DESC", p, is_select=True)
    df_pe   = executar_sql("SELECT data, peso_kg FROM public.peso WHERE data >= :d1 AND data <= :d2 ORDER BY data ASC", p, is_select=True)
    df_med  = executar_sql("SELECT log_date AS data, weight_kg AS peso, waist_cm AS cintura, body_fat_est AS bf_estimado, notes FROM public.body_measurements WHERE log_date >= :d1 AND log_date <= :d2 ORDER BY log_date DESC", p, is_select=True)
    df_pre  = executar_sql("SELECT measurement_time AS data_hora, systolic, diastolic, pulse FROM public.blood_pressure WHERE measurement_time >= :d1 AND measurement_time <= :d2 ORDER BY measurement_time DESC", p, is_select=True)
    df_trr  = executar_sql("SELECT data, tipo, duracao_min, passos, passos_trabalho, passos_total_dia, distancia_km, calorias, bpm_medio FROM public.exercicios WHERE data >= :d1 AND data <= :d2 ORDER BY data DESC", p, is_select=True)
    df_sn   = executar_sql("SELECT data, horas AS sono_horas, qualidade AS sono_qualidade FROM public.sono WHERE data >= :d1 AND data <= :d2", p, is_select=True)
    df_ag   = executar_sql("SELECT data, agua_ml, cafe_ml FROM public.hidratacao WHERE data >= :d1 AND data <= :d2", p, is_select=True)
    df_ev   = executar_sql("SELECT data, vezes AS evac_vezes, bristol AS evac_bristol FROM public.evacuacao WHERE data >= :d1 AND data <= :d2", p, is_select=True)

    df_mac = df_det.groupby('data')[['kcal','proteina','carbo','gordura']].sum().reset_index() if not df_det.empty else pd.DataFrame(columns=['data','kcal','proteina','carbo','gordura'])
    if not df_trr.empty:
        df_ta = df_trr.groupby('data').agg({'duracao_min':'sum','passos_total_dia':'max','passos_trabalho':'max','calorias':'sum'}).reset_index()
        df_ta.columns = ['data','treino_min','passos_dia','passos_prof','treino_kcal']
    else:
        df_ta = pd.DataFrame(columns=['data','treino_min','passos_dia','passos_prof','treino_kcal'])

    for df in [df_mac, df_pe, df_ta, df_sn, df_ag, df_ev]:
        if not df.empty and 'data' in df.columns:
            df['data'] = pd.to_datetime(df['data']).dt.normalize()
    if not df_pe.empty:
        df_pe = df_pe.drop_duplicates(subset='data', keep='last')

    df_res = pd.merge(df_mac, df_pe, on='data', how='outer')
    df_res = pd.merge(df_res, df_ta, on='data', how='left')
    for src in [df_sn, df_ag, df_ev]:
        if not src.empty:
            df_res = pd.merge(df_res, src, on='data', how='left')

    cols = ['data','peso_kg','kcal','proteina','carbo','gordura','treino_min','passos_dia','passos_prof','treino_kcal','sono_horas','agua_ml','cafe_ml','evac_vezes','evac_bristol']
    for c in cols:
        if c not in df_res.columns: df_res[c] = 0
    df_res = df_res[cols].sort_values('data', ascending=False).dropna(subset=['data'])
    df_res.columns = ['Data','Peso (kg)','Comida (kcal)','Prot (g)','Carb (g)','Gord (g)','Treino (min)','Passos Totais','Passos Prof','Gasto Treino (kcal)','Sono (h)','Água (ml)','Café (ml)','Intestino (Vezes)','Bristol (Qualidade)']
    df_res['Data'] = df_res['Data'].dt.strftime('%d/%m/%Y')

    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df_res.to_excel(writer,  sheet_name='1. Resumo Completo',       index=False)
        df_det.to_excel(writer,  sheet_name='2. Alimentação Detalhada',  index=False)
        df_trr.to_excel(writer,  sheet_name='3. Treinos Brutos',         index=False)
        df_med.to_excel(writer,  sheet_name='4. Medidas',                index=False)
        df_pre.to_excel(writer,  sheet_name='5. Pressão',                index=False)
    return output.getvalue()

# ============================================================================
# 8. INTERFACE PRINCIPAL
# ============================================================================
st.title("🦁 Leo Tracker Pro")
data_hoje = hoje

# ── SIDEBAR ──────────────────────────────────────────────────────────────────
st.sidebar.header("🎯 Status do Dia")

df_last_meal = executar_sql("SELECT data_hora FROM public.consumo ORDER BY data_hora DESC LIMIT 1", is_select=True)
tempo_jejum  = "0h 0m"
if not df_last_meal.empty:
    last_dt = df_last_meal.iloc[0]['data_hora']
    if pd.notnull(last_dt):
        now_naive  = get_now_br().replace(tzinfo=None)
        last_naive = last_dt.replace(tzinfo=None) if last_dt.tzinfo else last_dt
        diff       = (now_naive - last_naive).total_seconds()
        if diff > 0:
            tempo_jejum = f"{int(diff//3600)}h {int((diff%3600)//60)}m"

st.sidebar.metric("⏱️ Jejum Atual", tempo_jejum)
st.sidebar.metric("⚖️ Peso Atual", f"{peso_atual} kg", f"Meta: {METAS['peso_alvo']} kg")
st.sidebar.caption(f"Fator Ativ: {METAS['fator']}x")
st.sidebar.progress(min(max(0.0, (150 - peso_atual) / (150 - METAS['peso_alvo'])), 1.0))

st.sidebar.divider()
st.sidebar.markdown("#### 📅 Auditoria (30 dias)")
dt_30d = data_hoje - timedelta(days=30)
df_aud = executar_sql("SELECT DISTINCT data FROM public.consumo WHERE data >= :d", {'d': dt_30d}, is_select=True)
dias_ok  = pd.to_datetime(df_aud['data']).dt.date.tolist() if not df_aud.empty else []
dias_nok = [dt_30d + timedelta(days=i) for i in range(30) if dt_30d + timedelta(days=i) not in dias_ok]
if dias_nok:
    with st.sidebar.expander(f"⚠️ {len(dias_nok)} Dias Pendentes"):
        for d in sorted(dias_nok, reverse=True):
            st.markdown(f"❌ {d.strftime('%d/%m')}")
else:
    st.sidebar.success("✅ Histórico blindado!")

# ── MÉTRICAS DO DIA (TOPO) ────────────────────────────────────────────────────
df_hoje    = executar_sql("SELECT * FROM public.consumo WHERE data = :d", {'d': data_hoje}, is_select=True)
k_hoje     = float(df_hoje['kcal'].sum())     if not df_hoje.empty else 0.0
p_hoje     = float(df_hoje['proteina'].sum()) if not df_hoje.empty else 0.0
c_hoje     = float(df_hoje['carbo'].sum())    if not df_hoje.empty else 0.0
g_hoje     = float(df_hoje['gordura'].sum())  if not df_hoje.empty else 0.0

df_hid_hj  = executar_sql("SELECT agua_ml, cafe_ml FROM public.hidratacao WHERE data = :d", {'d': data_hoje}, is_select=True)
df_sno_hj  = executar_sql("SELECT horas, qualidade FROM public.sono WHERE data = :d", {'d': data_hoje}, is_select=True)
df_evc_hj  = executar_sql("SELECT vezes FROM public.evacuacao WHERE data = :d", {'d': data_hoje}, is_select=True)

agua_hj  = int(df_hid_hj.iloc[0]['agua_ml'])  if not df_hid_hj.empty else 0
cafe_hj  = int(df_hid_hj.iloc[0]['cafe_ml'])  if not df_hid_hj.empty else 0
sono_hj  = float(df_sno_hj.iloc[0]['horas'])  if not df_sno_hj.empty else 0.0
evac_hj  = int(df_evc_hj.iloc[0]['vezes'])    if not df_evc_hj.empty else 0

c1, c2, c3, c4 = st.columns(4)
c1.metric("🔥 Calorias",   f"{int(k_hoje)}",   f"Meta: {METAS['kcal']}")
c2.metric("🥩 Proteína",   f"{int(p_hoje)}g",  f"Meta: {METAS['prot']}g")
c3.metric("🍞 Carbo",      f"{int(c_hoje)}g",  f"Meta: {METAS['carb']}g")
c4.metric("🥑 Gordura",    f"{int(g_hoje)}g",  f"Meta: {METAS['gord']}g")
st.progress(min(k_hoje / METAS['kcal'], 1.0))

c5, c6, c7, c8 = st.columns(4)
c5.metric("💧 Água",       f"{agua_hj} ml")
c6.metric("☕ Café",       f"{cafe_hj} ml")
c7.metric("💤 Sono",       f"{sono_hj} h")
c8.metric("💩 Intestino",  f"{evac_hj}x")
st.divider()

# ── ABAS ──────────────────────────────────────────────────────────────────────
(tab_daily, tab_treino, tab_qs,
 tab_hist, tab_medidas, tab_micros,
 tab_rel, tab_admin) = st.tabs([
    "📝 Diário", "🏃‍♂️ Treino", "🧠 QS Lab",
    "📜 Histórico", "❤️ Saúde", "🥦 Micronutrientes",
    "📄 Relatórios", "⚙️ Configurações"
])

# ============================================================================
# TAB: DIÁRIO
# ============================================================================
with tab_daily:
    st.markdown("##### ⚖️ Peso de Hoje")
    with st.form("form_peso"):
        cp1, cp2, cp3 = st.columns([1, 1, 2])
        d_peso = cp1.date_input("Data", value=data_hoje, label_visibility="collapsed")
        p_val  = cp2.number_input("Peso (kg)", 40.0, 200.0, step=0.1, value=peso_atual, label_visibility="collapsed")
        if cp3.form_submit_button("💾 Salvar Peso", use_container_width=True):
            executar_sql("INSERT INTO public.peso (data, peso_kg) VALUES (:d, :p)", {'d': d_peso, 'p': p_val})
            st.cache_resource.clear(); st.rerun()
    st.divider()

    st.markdown("### 💧 Hidratação e ☕ Café")
    st.info("O sistema vai SOMANDO o valor ao longo do dia.")
    cw1, cw2 = st.columns(2)
    with cw1:
        with st.form("form_agua"):
            add_agua = st.number_input("➕ Água (ml)", 0, 2000, 250, step=50)
            if st.form_submit_button("💧 Somar Água", use_container_width=True):
                executar_sql("""INSERT INTO public.hidratacao (data, agua_ml, cafe_ml) VALUES (:d, :a, 0)
                    ON CONFLICT (data) DO UPDATE SET agua_ml = public.hidratacao.agua_ml + EXCLUDED.agua_ml""",
                    {'d': data_hoje, 'a': add_agua})
                st.success(f"+{add_agua}ml"); st.rerun()
    with cw2:
        with st.form("form_cafe"):
            add_cafe = st.number_input("➕ Café (ml)", 0, 1000, 50, step=10)
            if st.form_submit_button("☕ Somar Café", use_container_width=True):
                executar_sql("""INSERT INTO public.hidratacao (data, agua_ml, cafe_ml) VALUES (:d, 0, :c)
                    ON CONFLICT (data) DO UPDATE SET cafe_ml = public.hidratacao.cafe_ml + EXCLUDED.cafe_ml""",
                    {'d': data_hoje, 'c': add_cafe})
                st.success(f"+{add_cafe}ml"); st.rerun()

    st.markdown("### 💩 Trânsito Intestinal")
    with st.form("form_evac"):
        ce1, ce2, ce3 = st.columns([1, 2, 1])
        d_evac  = ce1.date_input("Data", value=data_hoje)
        bristol = ce2.select_slider("Escala de Bristol", options=[1,2,3,4,5,6,7], value=4,
                                    help="1-2: Constipação | 3-4: Ideal | 5-7: Diarreia")
        if ce3.form_submit_button("🚽 +1 Ida", use_container_width=True):
            executar_sql("""INSERT INTO public.evacuacao (data, vezes, bristol) VALUES (:d, 1, :b)
                ON CONFLICT (data) DO UPDATE SET vezes = public.evacuacao.vezes + 1, bristol = EXCLUDED.bristol""",
                {'d': d_evac, 'b': bristol})
            st.success("Registrado!"); st.rerun()

    st.markdown("### 💤 Sono")
    with st.form("form_sono"):
        cs1, cs2, cs3 = st.columns([1, 1, 2])
        d_sono = cs1.date_input("Noite de:", value=data_hoje - timedelta(days=1))
        h_sono = cs2.slider("Horas", 0.0, 14.0, 7.5, 0.5)
        q_sono = cs3.select_slider("Qualidade", options=[1,2,3,4,5], value=3,
                                   help="1=Péssima | 5=Fantástica")
        if st.form_submit_button("💾 Salvar Sono", use_container_width=True):
            executar_sql("""INSERT INTO public.sono (data, horas, qualidade) VALUES (:d, :h, :q)
                ON CONFLICT (data) DO UPDATE SET horas = EXCLUDED.horas, qualidade = EXCLUDED.qualidade""",
                {'d': d_sono, 'h': h_sono, 'q': q_sono})
            st.success("Sono registrado!"); st.rerun()

    st.divider()
    st.write("### 🍎 O que você comeu?")
    st.info("Digite o que comeu ou cole diretamente o JSON.")
    texto_input = st.text_area("Descrição ou JSON", height=120, label_visibility="collapsed",
                               placeholder="Ex: 2 ovos mexidos com queijo")

    if st.button("🚀 Processar Alimentação", use_container_width=True):
        if texto_input:
            is_json, lista = False, None
            try:
                cleaned = texto_input.replace('```json','').replace('```','').strip()
                s, e = cleaned.find('['), cleaned.rfind(']')
                if s == -1 and cleaned.startswith('{'): s, e = cleaned.find('{'), cleaned.rfind('}')
                if s != -1 and e != -1: cleaned = cleaned[s:e+1]
                lista = json.loads(cleaned); is_json = True
            except: pass

            if is_json:
                with st.spinner("📦 JSON detectado! Registrando..."):
                    try:
                        for item in (lista if isinstance(lista, list) else [lista]):
                            dt = item.get('data') or data_hoje
                            kf = max((float(item.get('p',0))*4 + float(item.get('c',0))*4 + float(item.get('g',0))*9), float(item.get('kcal',0)))
                            executar_sql("""INSERT INTO public.consumo
                                (data,alimento,quantidade,kcal,proteina,carbo,gordura,gluten,ferro_mg,b12_mcg,zinco_mg,magnesio_mg)
                                VALUES (:dt,:ali,:qtd,:kc,:pr,:ca,:go,:gl,:fe,:b12,:zn,:mg)""",
                                {'dt':dt,'ali':item.get('alimento'),'qtd':item.get('quantidade_g'),'kc':kf,
                                 'pr':item.get('p'),'ca':item.get('c'),'go':item.get('g'),'gl':item.get('gluten'),
                                 'fe':item.get('ferro_mg',0),'b12':item.get('b12_mcg',0),'zn':item.get('zinco_mg',0),'mg':item.get('magnesio_mg',0)})
                        st.success("Refeição salva!"); st.cache_resource.clear(); st.rerun()
                    except Exception as ex: st.error(f"Erro: {ex}")
            else:
                api_key = st.secrets.get("GROQ_API_KEY")
                if not api_key: st.error("GROQ_API_KEY não configurada!")
                else:
                    with st.spinner("🧠 Consultando IA Llama..."):
                        ok, res = processar_texto_ia(texto_input, api_key)
                        if ok:
                            st.success(res.get('analise'))
                            for item in res.get('alimentos', []):
                                kf = max((item.get('p',0)*4 + item.get('c',0)*4 + item.get('g',0)*9), float(item.get('kcal',0)))
                                executar_sql("""INSERT INTO public.consumo
                                    (data,alimento,quantidade,kcal,proteina,carbo,gordura,gluten,ferro_mg,b12_mcg,zinco_mg,magnesio_mg)
                                    VALUES (:dt,:ali,:qtd,:kc,:pr,:ca,:go,:gl,:fe,:b12,:zn,:mg)""",
                                    {'dt':item.get('data') or data_hoje,'ali':item.get('alimento'),'qtd':item.get('quantidade_g'),'kc':kf,
                                     'pr':item.get('p'),'ca':item.get('c'),'go':item.get('g'),'gl':item.get('gluten'),
                                     'fe':item.get('ferro_mg',0),'b12':item.get('b12_mcg',0),'zn':item.get('zinco_mg',0),'mg':item.get('magnesio_mg',0)})
                            st.cache_resource.clear(); st.rerun()
                        else: st.error(res)

    st.subheader("Registros de Hoje")
    if not df_hoje.empty:
        for _, row in df_hoje.iterrows():
            c1, c2, c3 = st.columns([3, 2, 0.5])
            c1.markdown(f"**{row['alimento']}**")
            c2.caption(f"{int(row['kcal'])} kcal | P:{int(row['proteina'])}g G:{int(row['gordura'])}g")
            if c3.button("❌", key=f"del_{row['id']}"):
                executar_sql("DELETE FROM public.consumo WHERE id=:id", {'id': row['id']})
                st.cache_resource.clear(); st.rerun()
            st.markdown("---")
    else: st.info("Nada registrado hoje.")

# ============================================================================
# TAB: TREINO
# ============================================================================
with tab_treino:
    st.markdown("### 🏃‍♂️ Monitoramento de Treino (Iron N1)")
    dt_alvo = st.date_input("📅 Data do Treino:", value=data_hoje, key="dt_treino")

    df_tr_alvo  = executar_sql("SELECT * FROM public.exercicios WHERE data = :d ORDER BY id DESC", {'d': dt_alvo}, is_select=True)
    df_fech     = df_tr_alvo[df_tr_alvo['tipo'] == 'Fechamento Diário'] if not df_tr_alvo.empty else pd.DataFrame()
    df_atv      = df_tr_alvo[df_tr_alvo['tipo'] != 'Fechamento Diário'] if not df_tr_alvo.empty else pd.DataFrame()

    min_treino  = int(df_atv['duracao_min'].sum())  if not df_atv.empty else 0
    passos_atv  = int(df_atv['passos'].sum())       if not df_atv.empty else 0
    total_rel   = int(df_fech.iloc[0]['passos_total_dia']) if not df_fech.empty else 0
    passos_rot  = max(0, total_rel - passos_atv)

    cm1, cm2, cm3 = st.columns(3)
    cm1.metric("⏱️ Tempo Treino",  f"{min_treino} min",   "Meta: 120 min")
    cm2.metric("👣 Passos Treino", f"{passos_atv}",        "Atividades registradas")
    cm3.metric("🏫 Passos Rotina", f"{passos_rot}",        f"Total Dia: {total_rel}")
    st.progress(min(min_treino / 120.0, 1.0))
    st.divider()

    st.subheader("🏁 Fechamento do Dia")
    with st.form("form_fech"):
        cf1, cf2 = st.columns([2, 1])
        input_total = cf1.number_input("Total de Passos (Relógio)", 0, 60000, total_rel)
        cf2.write(""); cf2.write("")
        if cf2.form_submit_button("💾 Salvar Fechamento", use_container_width=True):
            executar_sql("DELETE FROM public.exercicios WHERE data=:d AND tipo='Fechamento Diário'", {'d': dt_alvo})
            executar_sql("""INSERT INTO public.exercicios
                (data,tipo,duracao_min,passos,passos_total_dia,passos_trabalho,calorias,observacoes)
                VALUES (:d,'Fechamento Diário',0,0,:pt,:ptr,0,'Total Relógio')""",
                {'d': dt_alvo, 'pt': input_total, 'ptr': max(0, input_total - passos_atv)})
            st.success(f"Fechado! Total: {input_total}"); st.rerun()

    st.markdown("---")
    st.subheader("➕ Adicionar Atividade")
    with st.form("form_treino"):
        ct1, ct2 = st.columns(2)
        tipo    = ct1.selectbox("Atividade", ["Caminhada Indoor","Caminhada Rua (Transporte)","Musculação","Bicicleta Ergométrica","Outro"])
        duracao = ct2.number_input("Duração (min)", 0, 300, 30)
        ct3, ct4, ct5 = st.columns(3)
        passos  = ct3.number_input("Passos", 0, 20000, 0)
        dist    = ct4.number_input("Distância (km)", 0.0, 50.0, 0.0)
        cal     = ct5.number_input("Calorias (Relógio)", 0, 2000, 0)
        bpm     = st.number_input("BPM Médio (Opcional)", 0, 200, 0)
        obs     = st.text_input("Observações")
        if st.form_submit_button("💾 Registrar", use_container_width=True):
            executar_sql("""INSERT INTO public.exercicios
                (data,tipo,duracao_min,passos,distancia_km,calorias,bpm_medio,observacoes)
                VALUES (:d,:t,:dm,:p,:dk,:c,:bpm,:o)""",
                {'d':dt_alvo,'t':tipo,'dm':duracao,'p':passos,'dk':dist,'c':cal,'bpm':bpm,'o':obs})
            st.success("Atividade registrada!"); st.rerun()

    if not df_tr_alvo.empty:
        st.write(f"#### Registros — {dt_alvo.strftime('%d/%m/%Y')}")
        for _, row in df_tr_alvo.iterrows():
            rt1, rt2, rt3 = st.columns([3, 2, 0.5])
            if row['tipo'] == 'Fechamento Diário':
                rt1.markdown("🏁 **TOTAL DO DIA**")
                rt2.caption(f"Relógio: **{row['passos_total_dia']}** | Rotina: **{row['passos_trabalho']}**")
            else:
                rt1.markdown(f"🏃‍♂️ **{row['tipo']}**")
                rt2.caption(f"{row['duracao_min']} min | {row['passos']} passos | {row['calorias']} kcal")
            if rt3.button("🗑️", key=f"del_tr_{row['id']}"):
                executar_sql("DELETE FROM public.exercicios WHERE id=:id", {'id': row['id']}); st.rerun()
            st.markdown("---")

# ============================================================================
# TAB: QS LAB
# ============================================================================
with tab_qs:
    st.markdown("### 🧠 Laboratório de Termodinâmica Humana")

    if df_merged.empty or 'deficit_real' not in df_merged.columns:
        st.info("📊 Aguardando cruzamento de dados de peso e consumo.")
        st.stop()

    df_qs = df_merged.copy()
    df_qs['peso_amanha']         = df_qs['peso_kg'].shift(-1)
    df_qs['delta_peso_kg']       = df_qs['peso_amanha'] - df_qs['peso_kg']
    df_qs['delta_esperado_kg']   = -(df_qs['deficit_real'] / 7700)
    df_qs['fator_desinflamacao'] = df_qs['delta_peso_kg'] - df_qs['delta_esperado_kg']

    def classif(f):
        if pd.isna(f): return 'Sem Dados'
        if f < -0.1:   return 'Água/Desinflamação'
        if f > 0.1:    return 'Retenção/Glicogênio'
        return 'Perda de Gordura Pura'

    def cor(f):
        if pd.isna(f): return '#bdc3c7'
        if f < -0.1:   return '#3498DB'
        if f > 0.1:    return '#F1C40F'
        return '#E74C3C'

    df_qs['tipo_perda'] = df_qs['fator_desinflamacao'].apply(classif)
    df_qs['cor']        = df_qs['fator_desinflamacao'].apply(cor)

    df_qs['primeira_refeicao_dt'] = pd.to_datetime(df_qs['primeira_refeicao_dt'])
    df_qs['ultima_refeicao_dt']   = pd.to_datetime(df_qs['ultima_refeicao_dt'])
    df_qs['ultima_ref_ontem']     = df_qs['ultima_refeicao_dt'].shift(1)
    df_qs['jejum_h']              = (df_qs['primeira_refeicao_dt'] - df_qs['ultima_ref_ontem']).dt.total_seconds() / 3600
    df_qs['jejum_h']              = df_qs['jejum_h'].apply(lambda x: x if 8 <= x <= 48 else np.nan)

    df_qs_valido = df_qs.dropna(subset=['delta_peso_kg'])
    if df_qs_valido.empty:
        st.warning("Aguardando dados de variação de peso consolidados.")
        st.stop()

    last = df_qs_valido.iloc[-1]

    # ── OUTPUTS / INPUTS ─────────────────────────────────────────────────────
    st.markdown("**⚙️ Inputs — Causas do Dia Referência**")
    qi1, qi2, qi3, qi4 = st.columns(4)
    qi1.metric("⏳ Jejum",         f"{last.get('jejum_h', 0):.1f}h")
    qi2.metric("💧 Água",          f"{int(last.get('tagua', 0))} ml")
    qi3.metric("💤 Sono",          f"{last.get('sono_h', 0):.1f}h",   f"Q: {int(last.get('sono_q',0))}/5")
    qi4.metric("👣 Passos Rotina", f"{int(last.get('t_passos_trabalho', 0))}")

    st.markdown("**📊 Outputs — Efeitos na Balança**")
    qo1, qo2, qo3, qo4 = st.columns(4)
    qo1.metric("⚖️ Δ Real",             f"{last['delta_peso_kg']*1000:.0f} g",         help="Negativo = perda")
    qo2.metric("📐 Δ Termodinâmico",     f"{last['delta_esperado_kg']*1000:.0f} g",     help="Gordura teórica pelo déficit")
    qo3.metric("💧 Fator Desinflamação", f"{last['fator_desinflamacao']*1000:.0f} g",   help="Negativo = eliminou água")
    _emoji = {'Água/Desinflamação':'🔵','Retenção/Glicogênio':'🟡','Perda de Gordura Pura':'🔴'}
    qo4.metric("🔬 Qualidade", f"{_emoji.get(last['tipo_perda'],'⚪')} {last['tipo_perda']}")

    st.markdown("---")

    # ── §1 HACKER'S DIET + DÉFICIT ────────────────────────────────────────────
    st.markdown("### 1️⃣ Hacker's Diet: Sinal vs Ruído + Déficit")
    h1, h2 = st.columns(2)

    with h1:
        fig_peso = go.Figure()
        fig_peso.add_trace(go.Scatter(
            x=df_merged['data_dt'], y=df_merged['peso_kg'],
            mode='markers+lines', name='Balança Diária (Ruído)',
            line=dict(color='rgba(41,128,185,0.3)', width=2),
            marker=dict(size=6, color='rgba(41,128,185,0.5)')))
        fig_peso.add_trace(go.Scatter(
            x=df_merged['data_dt'], y=df_merged['peso_tendencia'],
            mode='lines', name='Tendência Real (EWMA)',
            line=dict(color='#E74C3C', width=4)))
        if 'waist_cm' in df_merged.columns and not df_merged['waist_cm'].isna().all():
            fig_peso.add_trace(go.Scatter(
                x=df_merged['data_dt'], y=df_merged['waist_cm'],
                mode='lines+markers', name='Cintura (cm)',
                line=dict(color='#27AE60', width=2, dash='dot'),
                yaxis='y2'))
            fig_peso.update_layout(
                yaxis2=dict(title='Cintura (cm)', overlaying='y', side='right', showgrid=False))
        fig_peso.update_layout(
            title="Peso: Sinal (vermelho) vs Ruído (azul) + Cintura",
            height=420, template="plotly_white", yaxis_title="Peso (kg)",
            hovermode="x unified", legend=dict(orientation="h", y=1.12))
        st.plotly_chart(fig_peso, use_container_width=True)

    with h2:
        fig_cal = go.Figure()
        fig_cal.add_trace(go.Bar(
            x=df_merged['data_dt'], y=df_merged['tkcal'],
            name='Calorias Ingeridas', marker_color='#E74C3C', opacity=0.8))
        fig_cal.add_trace(go.Scatter(
            x=df_merged['data_dt'], y=df_merged['get_total'],
            mode='lines', name='TDEE',
            line=dict(color='#27AE60', width=3, dash='dot')))
        fig_cal.update_layout(
            title="Déficit: Consumo vs Gasto Total (TDEE)",
            height=420, template="plotly_white", yaxis_title="Kcal",
            hovermode="x unified", legend=dict(orientation="h", y=1.12))
        st.plotly_chart(fig_cal, use_container_width=True)

    st.markdown("---")

    # ── §2 LABORATÓRIO: DESINFLAMAÇÃO + SHIFT ─────────────────────────────────
    st.markdown("### 2️⃣ Laboratório: Desinflamação e Shift de Jejum")
    l1, l2 = st.columns([2, 1])

    with l1:
        fig_lab = go.Figure()
        fig_lab.add_trace(go.Bar(
            x=df_qs['data_dt'], y=df_qs['delta_peso_kg'],
            marker_color=df_qs['cor'], name='Delta Real',
            text=df_qs['tipo_perda'], hoverinfo='x+y+text'))
        fig_lab.add_trace(go.Scatter(
            x=df_qs['data_dt'], y=df_qs['delta_esperado_kg'],
            mode='lines', name='Delta Teórico (Termodinâmica)',
            line=dict(color='#2ECC71', dash='dash', width=2)))
        fig_lab.add_hline(y=0, line_width=1, line_color='black')
        fig_lab.update_layout(
            height=420, template="plotly_white", hovermode="x unified",
            yaxis_title="Variação (kg) — negativo = perda",
            legend=dict(orientation="h", y=1.12))
        st.plotly_chart(fig_lab, use_container_width=True)

    with l2:
        df_trend = df_qs.dropna(subset=['jejum_h','delta_peso_kg'])
        fig_shift = go.Figure()
        fig_shift.add_trace(go.Scatter(
            x=df_trend['jejum_h'], y=df_trend['delta_peso_kg'],
            mode='markers',
            marker=dict(size=12, color=df_trend['cor'], opacity=0.8,
                        line=dict(width=1, color='black')),
            text=df_trend['data_dt'].astype(str), hoverinfo='text+x+y'))
        if len(df_trend) > 2:
            z         = np.polyfit(df_trend['jejum_h'], df_trend['delta_peso_kg'], 1)
            poly_fn   = np.poly1d(z)
            x_range   = np.linspace(df_trend['jejum_h'].min(), df_trend['jejum_h'].max(), 100)
            residuals = df_trend['delta_peso_kg'] - poly_fn(df_trend['jejum_h'])
            std_res   = residuals.std()
            # Banda IC 95%
            fig_shift.add_trace(go.Scatter(
                x=x_range, y=poly_fn(x_range) + 1.96*std_res,
                mode='lines', line=dict(width=0), showlegend=False))
            fig_shift.add_trace(go.Scatter(
                x=x_range, y=poly_fn(x_range) - 1.96*std_res,
                mode='lines', line=dict(width=0), showlegend=False,
                fill='tonexty', fillcolor='rgba(0,0,0,0.07)', name='IC 95%'))
            fig_shift.add_trace(go.Scatter(
                x=x_range, y=poly_fn(x_range),
                mode='lines', name='Tendência',
                line=dict(color='black', dash='dot', width=2)))
        fig_shift.add_hline(y=0, line_width=1, line_dash='dash', line_color='gray')
        fig_shift.update_layout(
            height=420, template="plotly_white",
            xaxis_title="Horas de Jejum", yaxis_title="Δ Peso Seguinte (kg)",
            showlegend=False)
        st.plotly_chart(fig_shift, use_container_width=True)

    st.markdown("---")

    # ── §3 ORÁCULO METABÓLICO ─────────────────────────────────────────────────
    # Injeta DNA do AG se disponível
    if 'novo_dna_metabolico' in st.session_state:
        dna  = st.session_state.pop('novo_dna_metabolico')
        keys = ['win_peso','win_jej','win_prot','win_carb','win_gord',
                'win_passos','win_agua','win_int','win_bristol','win_sono_h']
        for i, k in enumerate(keys):
            st.session_state[k] = dna[i]
        st.session_state['win_sono_q'] = dna[9]

    st.markdown("### 3️⃣ Oráculo Metabólico (Sintonizador de Inércia)")
    st.markdown("**🎯 Variável Alvo**")
    win_peso = st.slider("⚖️ Filtro de Peso (janela em dias)", 1, 15, key='win_peso')

    st.markdown("**⚙️ Janelas de Atraso Fisiológico (1–15 dias)**")
    sf1, sf2, sf3, sf4, sf5 = st.columns(5)
    with sf1:
        win_jej  = st.slider("⏳ Jejum",     1, 15, key='win_jej')
        win_agua = st.slider("💧 Água",      1, 15, key='win_agua')
    with sf2:
        win_prot = st.slider("🥩 Proteína",  1, 15, key='win_prot')
        win_int  = st.slider("💩 Intestino", 1, 15, key='win_int')
    with sf3:
        win_carb    = st.slider("🍞 Carbo",    1, 15, key='win_carb')
        win_bristol = st.slider("🧪 Bristol",  1, 15, key='win_bristol')
    with sf4:
        win_gord   = st.slider("🥑 Gordura",  1, 15, key='win_gord')
        win_passos = st.slider("👣 Passos",   1, 15, key='win_passos')
    with sf5:
        win_sono_h = st.slider("💤 Sono H",   1, 15, key='win_sono_h')
        win_sono_q = st.slider("🌟 Sono Q",   1, 15, key='win_sono_q')

    df_model = df_qs.copy()
    df_model['peso_suav']        = df_model['peso_kg'].rolling(win_peso, min_periods=1).mean()
    df_model['peso_suav_amanha'] = df_model['peso_suav'].shift(-1)
    df_model['target']           = df_model['peso_suav_amanha'] - df_model['peso_suav']
    df_model['jejum_f']          = df_model['jejum_h'].rolling(win_jej,     min_periods=1).mean()
    df_model['prot_f']           = df_model['tprot'].rolling(win_prot,      min_periods=1).mean()
    df_model['carb_f']           = df_model['tcarb'].rolling(win_carb,      min_periods=1).mean()
    df_model['gord_f']           = df_model['tgord'].rolling(win_gord,      min_periods=1).mean()
    df_model['passos_f']         = df_model['t_passos_trabalho'].rolling(win_passos, min_periods=1).mean()
    df_model['agua_f']           = df_model['tagua'].rolling(win_agua,      min_periods=1).mean()
    df_model['int_f']            = df_model['tintestino'].rolling(win_int,  min_periods=1).mean()
    df_model['bristol_f']        = df_model['tbristol'].rolling(win_bristol,min_periods=1).mean()
    df_model['sono_h_f']         = df_model['sono_h'].rolling(win_sono_h,   min_periods=1).mean()
    df_model['sono_q_f']         = df_model['sono_q'].rolling(win_sono_q,   min_periods=1).mean()

    FEATURES = ['jejum_f','prot_f','carb_f','gord_f','passos_f','agua_f','int_f','bristol_f','sono_h_f','sono_q_f']
    LABELS_MAP = {
        'jejum_f':   f'⏳ Jejum ({win_jej}d)',
        'prot_f':    f'🥩 Proteína ({win_prot}d)',
        'carb_f':    f'🍞 Carbo ({win_carb}d)',
        'gord_f':    f'🥑 Gordura ({win_gord}d)',
        'passos_f':  f'👣 Passos ({win_passos}d)',
        'agua_f':    f'💧 Água ({win_agua}d)',
        'int_f':     f'💩 Intestino ({win_int}d)',
        'bristol_f': f'🧪 Bristol ({win_bristol}d)',
        'sono_h_f':  f'💤 Sono H ({win_sono_h}d)',
        'sono_q_f':  f'🌟 Sono Q ({win_sono_q}d)',
    }
    df_model = df_model.dropna(subset=['target'] + FEATURES)
    st.markdown("---")

    if len(df_model) <= 5:
        st.warning("⏳ Mínimo 6 dias de dados para ativar o Oráculo.")
    else:
        formula = 'target ~ ' + ' + '.join(FEATURES)
        model   = ols(formula, data=df_model).fit()
        r2, aic_val, bic_val = model.rsquared, model.aic, model.bic
        params_ols, pvalues  = model.params, model.pvalues

        st.markdown(f"**R²:** `{r2*100:.1f}%` | **AIC:** `{aic_val:.1f}` | **BIC:** `{bic_val:.1f}` | **N:** `{len(df_model)} dias`")

        os1, os2 = st.columns([1, 1.2])

        # ── TORNADO CHART (ΔViz-1) ────────────────────────────────────────────
        with os1:
            st.markdown("##### 🌪️ Tornado Chart: Impacto por Variável")
            df_torn = pd.DataFrame({
                'variavel': [LABELS_MAP[f] for f in FEATURES],
                'coef_g':   [params_ols[f] * 1000 for f in FEATURES],
                'pvalor':   [pvalues[f] for f in FEATURES],
            }).sort_values('coef_g')

            df_torn['alpha'] = df_torn['pvalor'].apply(lambda p: 1.0 if p < 0.05 else 0.45 if p < 0.15 else 0.15)
            df_torn['cor']   = df_torn['coef_g'].apply(lambda c: '#27AE60' if c < 0 else '#E74C3C')
            df_torn['label'] = df_torn.apply(
                lambda r: f"{r['coef_g']:+.1f}g  {'🟢' if r['pvalor']<0.05 else '🟠' if r['pvalor']<0.15 else '⚪'}",
                axis=1)

            fig_torn = go.Figure()
            for _, rt in df_torn.iterrows():
                fig_torn.add_trace(go.Bar(
                    x=[rt['coef_g']], y=[rt['variavel']],
                    orientation='h',
                    marker_color=rt['cor'],
                    opacity=rt['alpha'],
                    text=rt['label'], textposition='outside',
                    showlegend=False,
                ))
            fig_torn.add_vline(x=0, line_color='black', line_width=2)
            fig_torn.update_layout(
                height=400, template='plotly_white',
                xaxis_title='Impacto em g/dia  ←Perde  |  Ganha→',
                margin=dict(l=10, r=90, t=20, b=10), bargap=0.25)
            st.plotly_chart(fig_torn, use_container_width=True)
            st.caption("🟢 P<0.05 Significante | 🟠 P<0.15 Moderado | ⚪ Ruído (quasi-transparente)")

        # ── TORNEIO EL FAROL + SIMULADOR ──────────────────────────────────────
        with os2:
            st.markdown("##### 🏆 Torneio El Farol")
            vencedor, menor_erro, mod_lr, mod_rf, df_transp = torneio_el_farol(df_model, FEATURES, 'target')

            if vencedor:
                st.info(f"**Líder:** {vencedor} | **MAE:** {menor_erro*1000:.0f} g")
                with st.expander("🔍 Auditoria dos Agentes"):
                    df_tb = df_transp.copy()
                    for col in ['Real (g)','Previsto LR (g)','Previsto RF (g)']:
                        df_tb[col] = df_tb[col].apply(lambda x: f"{x:+.0f}")
                    for col in ['Erro LR (g)','Erro RF (g)']:
                        df_tb[col] = df_tb[col].apply(lambda x: f"{x:.0f}")
                    st.table(df_tb)

                st.markdown("##### 🔮 Simulador Preditivo")
                sc1, sc2, sc3 = st.columns(3)
                with sc1:
                    sim_jej    = st.slider(f"Jejum ({win_jej}d)",     8.0,  24.0,  16.0, 0.5, key='sim_jej')
                    sim_prot   = st.slider(f"Proteína ({win_prot}d)", 50,   250,   METAS['prot'], 5, key='sim_prot')
                    sim_agua   = st.slider(f"Água ({win_agua}d)",     1000, 5000,  3000, 100, key='sim_agua')
                    sim_sono_h = st.slider(f"Sono h ({win_sono_h}d)", 0.0,  14.0,  7.5,  0.5, key='sim_sono_h')
                with sc2:
                    sim_carb   = st.slider(f"Carbo ({win_carb}d)",    20,   300,   METAS['carb'], 5, key='sim_carb')
                    sim_gord   = st.slider(f"Gordura ({win_gord}d)",   20,   150,   METAS['gord'], 5, key='sim_gord')
                    sim_int    = st.slider(f"Intestino ({win_int}d)",  0,    5,     1, 1, key='sim_int')
                    sim_sono_q = st.slider(f"Sono Q ({win_sono_q}d)", 1,    5,     3, 1, key='sim_sono_q')
                with sc3:
                    sim_passos  = st.slider(f"Passos ({win_passos}d)",  0,    30000, 10000, 500, key='sim_passos')
                    sim_bristol = st.slider(f"Bristol ({win_bristol}d)",1,    7,     3, 1, key='sim_bristol')

                entrada = pd.DataFrame({'jejum_f':[sim_jej],'prot_f':[sim_prot],'carb_f':[sim_carb],
                    'gord_f':[sim_gord],'passos_f':[sim_passos],'agua_f':[sim_agua],
                    'int_f':[sim_int],'bristol_f':[sim_bristol],'sono_h_f':[sim_sono_h],'sono_q_f':[sim_sono_q]})
                pred = (mod_rf if vencedor == "Random Forest" else mod_lr).predict(entrada)[0]
                st.metric("Tendência de Variação Prevista", f"{pred*1000:+.0f} g", delta_color="inverse")
            else:
                st.warning("⏳ Mínimo 10 dias para iniciar o Torneio El Farol.")

        # ── GROQ ──────────────────────────────────────────────────────────────
        st.markdown("---")
        st.markdown("##### 🧠 Consultoria Metabólica (IA Groq)")
        if st.button("🩺 Pedir Análise de Inércia"):
            api_key = st.secrets.get("GROQ_API_KEY")
            if not api_key:
                st.error("GROQ_API_KEY não configurada!")
            else:
                # Prompt com coeficientes em g/dia (não kg) para melhor leitura da IA
                df_prompt = pd.DataFrame({
                    'Variável':      [LABELS_MAP[f] for f in FEATURES],
                    'Coef (g/dia)':  [f"{params_ols[f]*1000:+.2f}" for f in FEATURES],
                    'P-Valor':       [f"{pvalues[f]:.3f} {'🟢' if pvalues[f]<0.05 else '🟠' if pvalues[f]<0.15 else '⚪'}" for f in FEATURES],
                })
                prompt = f"""Atue como Engenheiro de Dados especializado em Bioestatística.
A variável alvo é VARIAÇÃO DE PESO (Δ Amanhã - Hoje).

⚠️ REGRAS MATEMÁTICAS OBRIGATÓRIAS:
1. Coef NEGATIVO (g/dia) = perda de peso. COMPORTAMENTO DESEJADO.
2. Coef POSITIVO (g/dia) = ganho de peso. COMPORTAMENTO A EVITAR.
3. Analise EXCLUSIVAMENTE variáveis com 🟢 (P<0.05). Ignore ⚪.
4. PROIBIDO conselhos genéricos. Se gordura tiver coef negativo, AFIRME que auxilia na perda.

R²={r2*100:.1f}% | AIC={aic_val:.1f}

{df_prompt.to_string(index=False)}

Responda em 2 parágrafos curtos e diretos:
P1: O que os dados revelam? Cite coeficientes em g/dia.
P2: Plano tático para as próximas 24h baseado ESTRITAMENTE nos sinais matemáticos."""

                from groq import Groq as _Groq
                client = _Groq(api_key=api_key)
                with st.spinner("Decodificando DNA metabólico..."):
                    stream = client.chat.completions.create(
                        model="llama-3.3-70b-versatile",
                        messages=[{"role":"user","content":prompt}],
                        temperature=0.1, stream=True)
                    def _gen(s):
                        for chunk in s:
                            if chunk.choices[0].delta.content:
                                yield chunk.choices[0].delta.content
                    st.write_stream(_gen(stream))

        # ── ALGORITMO GENÉTICO ─────────────────────────────────────────────────
        st.markdown("---")
        with st.expander("🧬 Evolução Genética do DNA Metabólico (AIC Evaluator)"):
            st.caption("O AG testa cruzamentos e mutações de janelas (1–15 dias) e converge para o menor AIC.")
            if st.button("🚀 Iniciar Evolução Biométrica"):
                with st.spinner("Decodificando DNA Metabólico..."):
                    TAM_POP, GERACOES, JMAX = 50, 15, 15
                    base = df_qs[['peso_kg','jejum_h','tprot','tcarb','tgord',
                                  't_passos_trabalho','tagua','tintestino','tbristol','sono_h','sono_q']].copy()
                    pc = {}
                    for w in range(1, JMAX+1):
                        pc[f't_{w}'] = base['peso_kg'].rolling(w, min_periods=1).mean().shift(-1) - base['peso_kg'].rolling(w, min_periods=1).mean()
                        for c in ['tprot','tcarb','tgord','tagua','tintestino','tbristol','sono_h','sono_q','jejum_h','t_passos_trabalho']:
                            pc[f'{c}_{w}'] = base[c].rolling(w, min_periods=1).mean()
                    df_pre = pd.DataFrame(pc)

                    def fitness(ind):
                        cols = [f'jejum_h_{ind[1]}',f'tprot_{ind[2]}',f'tcarb_{ind[3]}',f'tgord_{ind[4]}',
                                f't_passos_trabalho_{ind[5]}',f'tagua_{ind[6]}',f'tintestino_{ind[7]}',
                                f'tbristol_{ind[8]}',f'sono_h_{ind[9]}',f'sono_q_{ind[9]}']
                        d = df_pre[[f't_{ind[0]}']+cols].dropna()
                        if len(d) < 15: return 9999
                        try: return sm.OLS(d[f't_{ind[0]}'], sm.add_constant(d[cols])).fit().aic
                        except: return 9999

                    pop = [[random.randint(1, JMAX) for _ in range(10)] for _ in range(TAM_POP)]
                    pb  = st.progress(0)
                    for g in range(GERACOES):
                        pop     = sorted(pop, key=fitness)
                        nova    = pop[:5]
                        while len(nova) < TAM_POP:
                            p1, p2 = random.sample(pop[:20], 2)
                            filho  = [p1[i] if random.random() > 0.5 else p2[i] for i in range(10)]
                            if random.random() < 0.2:
                                filho[random.randint(0,9)] = random.randint(1, JMAX)
                            nova.append(filho)
                        pop = nova
                        pb.progress((g+1)/GERACOES)

                    best     = pop[0]
                    best_aic = fitness(best)

                    # ── ΔViz-4: Painel de resultado pré-aplicação ─────────────
                    AG_KEYS  = ['win_peso','win_jej','win_prot','win_carb','win_gord',
                                'win_passos','win_agua','win_int','win_bristol','win_sono_h']
                    AG_NOMES = ['⚖️ Peso','⏳ Jejum','🥩 Proteína','🍞 Carbo','🥑 Gordura',
                                '👣 Passos','💧 Água','💩 Intestino','🧪 Bristol','💤 Sono']
                    atuais   = [st.session_state.get(k, _AG_DEFAULTS.get(k, 1)) for k in AG_KEYS]

                    delta_aic = best_aic - aic_val
                    st.markdown(f"**AIC Atual:** `{aic_val:.1f}` → **AIC Ótimo:** `{best_aic:.1f}` &nbsp; `Δ = {delta_aic:+.1f}`")

                    df_dna = pd.DataFrame({
                        'Variável':         AG_NOMES,
                        'Janela Atual (d)': atuais,
                        'Janela Ótima (d)': best,
                        'Mudança':          [
                            f"{'↑' if best[i]>atuais[i] else '↓' if best[i]<atuais[i] else '='} {abs(best[i]-atuais[i])}d"
                            for i in range(10)
                        ]
                    })
                    st.table(df_dna)

                    ag1, ag2 = st.columns(2)
                    if ag1.button("🚀 Aplicar DNA Ótimo"):
                        st.session_state['novo_dna_metabolico'] = best
                        st.rerun()
                    ag2.button("❌ Cancelar")

    st.markdown("---")

    # ── §4 DENSIDADE ENERGÉTICA ────────────────────────────────────────────────
    st.markdown("### 4️⃣ Densidade Energética: Volume vs. Calorias")
    if not df_merged.empty and 'tkcal' in df_merged.columns:
        fig_vol = make_subplots(specs=[[{"secondary_y": True}]])
        fig_vol.add_trace(go.Bar(
            x=df_merged['data_dt'], y=df_merged['tqtd'],
            name="Volume Ingerido (g)", marker_color='#AED6F1', opacity=0.5), secondary_y=True)
        fig_vol.add_trace(go.Scatter(
            x=df_merged['data_dt'], y=df_merged['tkcal'],
            name="Calorias Ingeridas", mode='lines+markers',
            line=dict(color='#C0392B', width=3)), secondary_y=False)
        if 'get_total' in df_merged.columns:
            fig_vol.add_trace(go.Scatter(
                x=df_merged['data_dt'], y=df_merged['get_total'],
                name="TDEE", mode='lines',
                line=dict(color='#27AE60', width=2, dash='dot')), secondary_y=False)
        fig_vol.update_layout(
            height=380, template="plotly_white",
            legend=dict(orientation="h", y=1.12), margin=dict(l=10,r=10,t=30,b=10))
        fig_vol.update_yaxes(title_text="Kcal", secondary_y=False)
        fig_vol.update_yaxes(title_text="Gramas", secondary_y=True, showgrid=False)
        st.plotly_chart(fig_vol, use_container_width=True)

    st.markdown("---")

    # ── §5 CONSISTÊNCIA DE TREINO + INDICADORES DE SAÚDE ──────────────────────
    st.markdown("### 5️⃣ Consistência de Treino & Indicadores de Saúde")
    ic1, ic2, ic3, ic4 = st.columns(4)

    with ic1:
        if 't_passos_trabalho' in df_merged.columns:
            fig_tr = go.Figure()
            fig_tr.add_trace(go.Scatter(
                x=df_merged['data_dt'], y=df_merged['t_passos_trabalho'],
                name='Passos Rotina', mode='lines+markers',
                line=dict(color='#8E44AD', width=2)))
            if 't_min' in df_merged.columns:
                fig_tr.add_trace(go.Bar(
                    x=df_merged['data_dt'], y=df_merged['t_min'],
                    name='Min Treino', marker_color='#D7BDE2', opacity=0.6, yaxis='y2'))
                fig_tr.update_layout(
                    yaxis2=dict(overlaying='y', side='right', showgrid=False, title='Min'))
            fig_tr.update_layout(
                title="Passos + Tempo de Treino", height=300,
                template="plotly_white", legend=dict(orientation="h", y=1.18),
                margin=dict(l=10,r=10,t=45,b=10))
            st.plotly_chart(fig_tr, use_container_width=True)

    with ic2:
        if not df_medidas.empty:
            fig_bf = go.Figure(go.Scatter(
                x=df_medidas['log_date'], y=df_medidas['body_fat_est'],
                mode='lines+markers', line=dict(color='#e67e22', width=2)))
            fig_bf.update_layout(
                title="Gordura Corporal (%)", height=300,
                template="plotly_white", margin=dict(l=10,r=10,t=45,b=10))
            st.plotly_chart(fig_bf, use_container_width=True)

    with ic3:
        if not df_bp.empty:
            fig_bp2 = go.Figure()
            fig_bp2.add_trace(go.Scatter(
                x=df_bp['measurement_time'], y=df_bp['systolic'],
                name="Sistólica", line=dict(color='#c0392b')))
            fig_bp2.add_trace(go.Scatter(
                x=df_bp['measurement_time'], y=df_bp['diastolic'],
                name="Diastólica", line=dict(color='#2980b9')))
            fig_bp2.update_layout(
                title="Pressão Arterial", height=300,
                template="plotly_white", legend=dict(orientation="h", y=1.18),
                margin=dict(l=10,r=10,t=45,b=10))
            st.plotly_chart(fig_bp2, use_container_width=True)

    with ic4:
        if not df_hist.empty:
            df_mac = df_hist.copy()
            df_mac['tot'] = (df_mac['tprot']*4 + df_mac['tcarb']*4 + df_mac['tgord']*9).replace(0,1)
            fig_st = go.Figure()
            fig_st.add_trace(go.Bar(x=df_mac['data'], y=(df_mac['tprot']*4/df_mac['tot'])*100, name='P%', marker_color='#3366CC'))
            fig_st.add_trace(go.Bar(x=df_mac['data'], y=(df_mac['tgord']*9/df_mac['tot'])*100, name='G%', marker_color='#DC3912'))
            fig_st.add_trace(go.Bar(x=df_mac['data'], y=(df_mac['tcarb']*4/df_mac['tot'])*100, name='C%', marker_color='#FF9900'))
            fig_st.update_layout(
                title="Distribuição Macros (%)", barmode='stack', height=300,
                template="plotly_white", yaxis=dict(range=[0,100]),
                showlegend=False, margin=dict(l=10,r=10,t=45,b=10))
            st.plotly_chart(fig_st, use_container_width=True)

    st.markdown("---")

    # ── §6 ANÁLISE DE TENDÊNCIAS ───────────────────────────────────────────────
    st.markdown("### 6️⃣ Análise de Tendências (Médias Móveis & Extremos)")
    if not df_merged.empty:
        _cols = ['peso_kg','tkcal','tprot','tcarb','tgord','t_min','t_passos_trabalho','deficit_real']
        _pres = [c for c in _cols if c in df_merged.columns]
        df_eda = df_merged[['data_dt',*_pres]].sort_values('data_dt').fillna(0)

        def _mm(df, n, col): return df.tail(n)[col].mean() if col in df.columns else 0

        _metrics = [
            ("⚖️ Peso (kg)",       'peso_kg'),
            ("🔥 Calorias (kcal)", 'tkcal'),
            ("🥩 Proteína (g)",    'tprot'),
            ("🍞 Carbo (g)",       'tcarb'),
            ("🥑 Gordura (g)",     'tgord'),
            ("⏱️ Treino (min)",    't_min'),
            ("👣 Passos",          't_passos_trabalho'),
            ("📉 Déficit (kcal)",  'deficit_real'),
        ]
        rows = []
        for label, col in _metrics:
            if col in df_eda.columns:
                rows.append({
                    "Indicador":    label,
                    "3d":           f"{_mm(df_eda,3,col):.1f}",
                    "7d":           f"{_mm(df_eda,7,col):.1f}",
                    "30d":          f"{_mm(df_eda,30,col):.1f}",
                    "Média Total":  f"{df_eda[col].mean():.1f}",
                    "Mínimo":       f"{df_eda[col].min():.1f}",
                    "Máximo":       f"{df_eda[col].max():.1f}",
                })
        if rows: st.table(pd.DataFrame(rows))

    with st.expander("📚 Metodologia e Glossário"):
        st.markdown("""
**GET (Gasto Energético Total):** Mifflin-St Jeor × Fator de Atividade + Calorias de Treino  
**Déficit Real:** GET Total − Calorias Ingeridas  
**Perda Teórica de Gordura:** Déficit Acumulado ÷ 7.700  
**EWMA — Hacker's Diet:** Média Móvel Exponencial (span=10) para isolar sinal hídrico do peso real  
**OLS + Janelas Móveis:** Regressão linear multivariável com lags de 1–15 dias por variável fisiológica  
**AIC (Fitness do AG):** Critério de Akaike — penaliza parâmetros extras, combate overfitting  
**Torneio El Farol:** Seleção dinâmica entre LR e RF pelo menor MAE nos últimos 5 dias  
**Tornado Chart:** Coeficientes em g/dia; verde = reduz peso, vermelho = aumenta; opacidade ∝ significância  
**IC 95% (Shift):** Intervalo de confiança da tendência Jejum vs Δ Peso calculado via resíduos do ajuste linear  
""")

# ============================================================================
# TAB: HISTÓRICO
# ============================================================================
with tab_hist:
    st.header("📜 Histórico de Consumo")
    hh1, hh2 = st.columns(2)
    dt_hi = hh1.date_input("De:",  value=data_hoje - timedelta(days=7), key="hist_ini")
    dt_hf = hh2.date_input("Até:", value=data_hoje,                     key="hist_fim")
    df_ht = executar_sql("""SELECT data, alimento, quantidade, kcal, proteina, carbo, gordura
        FROM public.consumo WHERE data >= :d1 AND data <= :d2 ORDER BY data DESC""",
        {'d1': dt_hi, 'd2': dt_hf}, is_select=True)
    if not df_ht.empty:
        hm1, hm2, hm3 = st.columns(3)
        hm1.metric("Total Kcal",      f"{int(df_ht['kcal'].sum())}")
        hm2.metric("Média Prot/dia",  f"{df_ht.groupby('data')['proteina'].sum().mean():.0f}g")
        hm3.metric("Refeições",       f"{len(df_ht)}")
        st.dataframe(df_ht, use_container_width=True)
    else: st.info("Nenhum registro no período.")

# ============================================================================
# TAB: SAÚDE
# ============================================================================
with tab_medidas:
    st.subheader("🫀 Pressão Arterial")
    with st.form("bp_form"):
        bs1, bs2, bs3 = st.columns(3)
        sys = bs1.number_input("Sistólica",  90, 200, 120)
        dia = bs2.number_input("Diastólica", 50, 130, 80)
        pul = bs3.number_input("Pulso",      40, 200, 75)
        if st.form_submit_button("Salvar Pressão"):
            executar_sql("INSERT INTO public.blood_pressure (systolic,diastolic,pulse,notes) VALUES (:s,:d,:p,'App')", {'s':sys,'d':dia,'p':pul})
            st.rerun()

    st.divider()
    st.subheader("📏 Avaliação Corporal")
    with st.form("medidas_form"):
        d_med   = st.date_input("Data", value=data_hoje)
        p_inp   = st.number_input("Peso Atual (kg)", 40.0, 200.0, step=0.1, value=peso_atual)
        waist   = st.number_input("Cintura (cm)", 50.0, 200.0, step=0.5, value=METAS['last_waist'])
        bf_w    = calc_bf_weltman(waist, p_inp, METAS['altura'], METAS['genero'])
        st.info(f"🧬 **BF Weltman: {bf_w:.1f}%**")
        if st.form_submit_button("Salvar Avaliação"):
            executar_sql("""INSERT INTO public.body_measurements
                (log_date,weight_kg,waist_cm,neck_cm,hip_cm,body_fat_est,
                 fold_chest,fold_abdominal,fold_thigh,fold_triceps,body_fat_pollock,body_fat_weltman,notes)
                VALUES (:dt,:w,:wa,:ne,:hi,:bf,0,0,0,0,0,:bfw,'Weltman Simples')""",
                {'dt':d_med,'w':p_inp,'wa':waist,'ne':METAS['last_neck'],'hi':METAS['last_hip'],'bf':bf_w,'bfw':bf_w})
            executar_sql("INSERT INTO public.peso (data,peso_kg) VALUES (:dt,:w)", {'dt':d_med,'w':p_inp})
            executar_sql("UPDATE public.perfil SET ultima_cintura=:wa WHERE id=1", {'wa':waist})
            st.cache_resource.clear(); st.rerun()

# ============================================================================
# TAB: MICRONUTRIENTES
# ============================================================================
with tab_micros:
    st.header("🥦 Painel de Micronutrientes")
    mm1, mm2 = st.columns(2)
    dt_mi = mm1.date_input("De:",  value=data_hoje - timedelta(days=7), key="dt_ini_micros")
    dt_mf = mm2.date_input("Até:", value=data_hoje,                     key="dt_fim_micros")
    df_mic = executar_sql("""SELECT data, ferro_mg, b12_mcg, zinco_mg, magnesio_mg
        FROM public.consumo WHERE data >= :d1 AND data <= :d2""",
        {'d1':dt_mi,'d2':dt_mf}, is_select=True)
    if not df_mic.empty:
        df_md = df_mic.groupby('data')[['ferro_mg','b12_mcg','zinco_mg','magnesio_mg']].sum().reset_index()
        m_fe, m_b12, m_zn, m_mg = df_md['ferro_mg'].mean(), df_md['b12_mcg'].mean(), df_md['zinco_mg'].mean(), df_md['magnesio_mg'].mean()
        st.subheader(f"📊 Média Diária ({len(df_md)} dias)")
        mc1, mc2, mc3, mc4 = st.columns(4)
        mc1.metric("🩸 Ferro (mg)",    f"{m_fe:.1f}",  "Meta: 8.0");   mc1.progress(min(m_fe/8.0,1.0))
        mc2.metric("⚡ B12 (mcg)",     f"{m_b12:.1f}", "Meta: 2.4");   mc2.progress(min(m_b12/2.4,1.0))
        mc3.metric("🛡️ Zinco (mg)",   f"{m_zn:.1f}",  "Meta: 11.0");  mc3.progress(min(m_zn/11.0,1.0))
        mc4.metric("💤 Magnésio (mg)", f"{m_mg:.1f}",  "Meta: 400.0"); mc4.progress(min(m_mg/400.0,1.0))
        st.divider()
        df_md['data'] = df_md['data'].dt.strftime('%d/%m/%Y')
        df_md.columns = ['Data','Ferro (mg)','B12 (mcg)','Zinco (mg)','Magnésio (mg)']
        st.dataframe(df_md, use_container_width=True)
    else: st.warning("Nenhum dado de micronutriente no período.")

# ============================================================================
# TAB: RELATÓRIOS
# ============================================================================
with tab_rel:
    st.header("📄 Relatórios")
    rd1, rd2 = st.columns(2)
    dt_ri = rd1.date_input("De:",  value=data_hoje - timedelta(days=30))
    dt_rf = rd2.date_input("Até:", value=data_hoje)
    if st.button("📊 Gerar Relatório Completo (.xlsx)"):
        try:
            xls = gerar_excel_nutri(dt_ri, dt_rf)
            st.download_button("📥 Download", data=xls,
                file_name=f"Leo_Relatorio_{dt_ri}_{dt_rf}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        except Exception as ex: st.error(f"Erro: {ex}")

# ============================================================================
# TAB: CONFIGURAÇÕES
# ============================================================================
with tab_admin:
    st.header("⚙️ Configurações")
    with st.form("form_metas"):
        st.subheader("Fator de Atividade (Basal Multiplier)")
        st.caption("1.2 = Sedentário/Férias | 1.35 = Leve/Aulas | 1.55 = Moderado/Treino Pesado")
        n_fat  = st.number_input("Fator", 1.0, 2.0, METAS['fator'], 0.05)
        st.divider()
        ak1, ak2 = st.columns(2)
        n_kcal = ak1.number_input("Calorias Meta",    value=METAS['kcal'])
        n_prot = ak2.number_input("Proteína Meta (g)", value=METAS['prot'])
        ak3, ak4 = st.columns(2)
        n_carb = ak3.number_input("Carbo Meta (g)",   value=METAS['carb'])
        n_gord = ak4.number_input("Gordura Meta (g)", value=METAS['gord'])
        ap1, ap2 = st.columns(2)
        n_alvo = ap1.number_input("Peso Alvo (kg)",      value=METAS['peso_alvo'])
        n_ritmo= ap2.number_input("Ritmo Semanal (kg/s)", value=METAS['ritmo'])
        if st.form_submit_button("💾 Salvar Metas"):
            executar_sql("""UPDATE public.perfil SET
                meta_kcal=:mk, meta_proteina=:mp, meta_carbo=:mc, meta_gordura=:mg,
                meta_peso_alvo=:mpa, ritmo_semanal=:rit, fator_atividade=:fat WHERE id=1""",
                {'mk':n_kcal,'mp':n_prot,'mc':n_carb,'mg':n_gord,'mpa':n_alvo,'rit':n_ritmo,'fat':n_fat})
            st.cache_resource.clear(); st.rerun()

st.caption("Leo Tracker Pro v12.0 | QS Lab Unificado 🦁🧬")
