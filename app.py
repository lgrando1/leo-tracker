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
    # Tabelas antigas...
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

    # --- TABELAS DE SONO, HIDRATAÇÃO E EVACUAÇÃO ---
    executar_sql("""
        CREATE TABLE IF NOT EXISTS public.sono (
            data DATE PRIMARY KEY, horas REAL, qualidade INT
        );
    """)
    executar_sql("""
        CREATE TABLE IF NOT EXISTS public.hidratacao (
            data DATE PRIMARY KEY, agua_ml INT DEFAULT 0, cafe_ml INT DEFAULT 0
        );
    """)
    executar_sql("""
        CREATE TABLE IF NOT EXISTS public.evacuacao (
            data DATE PRIMARY KEY, vezes INT DEFAULT 0, bristol INT DEFAULT 4
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
    
    df_sono_exp = executar_sql("SELECT data, horas as sono_horas, qualidade as sono_qualidade FROM public.sono WHERE data >= :d1 AND data <= :d2", params, is_select=True)
    df_hidra_exp = executar_sql("SELECT data, agua_ml, cafe_ml FROM public.hidratacao WHERE data >= :d1 AND data <= :d2", params, is_select=True)
    df_evac_exp = executar_sql("SELECT data, vezes as evac_vezes, bristol as evac_bristol FROM public.evacuacao WHERE data >= :d1 AND data <= :d2", params, is_select=True)

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
    if not df_sono_exp.empty: df_sono_exp['data'] = pd.to_datetime(df_sono_exp['data']).dt.normalize()
    if not df_hidra_exp.empty: df_hidra_exp['data'] = pd.to_datetime(df_hidra_exp['data']).dt.normalize()
    if not df_evac_exp.empty: df_evac_exp['data'] = pd.to_datetime(df_evac_exp['data']).dt.normalize()

    if not df_macros.empty or not df_peso.empty:
        df_resumo = pd.merge(df_macros, df_peso, on='data', how='outer')
        df_resumo = pd.merge(df_resumo, df_treinos_agg, on='data', how='left')
        
        # Merge Sono, Hidratação e Evacuação
        if not df_sono_exp.empty: df_resumo = pd.merge(df_resumo, df_sono_exp, on='data', how='left')
        else: df_resumo['sono_horas'] = 0; df_resumo['sono_qualidade'] = 0
        
        if not df_hidra_exp.empty: df_resumo = pd.merge(df_resumo, df_hidra_exp, on='data', how='left')
        else: df_resumo['agua_ml'] = 0; df_resumo['cafe_ml'] = 0

        if not df_evac_exp.empty: df_resumo = pd.merge(df_resumo, df_evac_exp, on='data', how='left')
        else: df_resumo['evac_vezes'] = 0; df_resumo['evac_bristol'] = 0
        
        df_resumo = df_resumo.sort_values('data', ascending=False)
        cols_order = ['data', 'peso_kg', 'kcal', 'proteina', 'carbo', 'gordura', 'treino_min', 'passos_dia', 'passos_prof', 'treino_kcal', 'sono_horas', 'agua_ml', 'cafe_ml', 'evac_vezes', 'evac_bristol']
        for c in cols_order: 
            if c not in df_resumo.columns: df_resumo[c] = 0
        df_resumo = df_resumo[cols_order]
        df_resumo.columns = ['Data', 'Peso (kg)', 'Comida (kcal)', 'Prot (g)', 'Carb (g)', 'Gord (g)', 'Treino (min)', 'Passos Totais', 'Passos Prof', 'Gasto Treino (kcal)', 'Sono (h)', 'Água (ml)', 'Café (ml)', 'Intestino (Vezes)', 'Bristol (Qualidade)']
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

# Busca Dados Diários de Hidratação, Sono e Evacuação
df_hidra_hoje = executar_sql("SELECT agua_ml, cafe_ml FROM public.hidratacao WHERE data = :d", {'d': data_hoje}, is_select=True)
df_sono_hoje = executar_sql("SELECT horas, qualidade FROM public.sono WHERE data = :d", {'d': data_hoje}, is_select=True)
df_evac_hoje = executar_sql("SELECT vezes FROM public.evacuacao WHERE data = :d", {'d': data_hoje}, is_select=True)

agua_hoje = int(df_hidra_hoje.iloc[0]['agua_ml']) if not df_hidra_hoje.empty else 0
cafe_hoje = int(df_hidra_hoje.iloc[0]['cafe_ml']) if not df_hidra_hoje.empty else 0
sono_hoje = float(df_sono_hoje.iloc[0]['horas']) if not df_sono_hoje.empty else 0.0
evac_hoje = int(df_evac_hoje.iloc[0]['vezes']) if not df_evac_hoje.empty else 0

c1, c2, c3, c4 = st.columns(4)
c1.metric("🔥 Calorias", f"{int(k_hoje)}", f"Meta: {METAS['kcal']}")
c2.metric("🥩 Proteína", f"{int(p_hoje)}g", f"Meta: {METAS['prot']}g")
c3.metric("🍞 Carbo", f"{int(c_hoje)}g", f"Meta: {METAS['carb']}g")
c4.metric("🥑 Gordura", f"{int(g_hoje)}g", f"Meta: {METAS['gord']}g")
st.progress(min(k_hoje/METAS['kcal'], 1.0))

c5, c6, c7, c8 = st.columns(4)
c5.metric("💧 Água", f"{agua_hoje} ml")
c6.metric("☕ Café", f"{cafe_hoje} ml")
c7.metric("💤 Sono", f"{sono_hoje} h")
c8.metric("💩 Intestino", f"{evac_hoje}x")

st.divider()

# ABAS
tab_daily, tab_treino, tab_hist, tab_medidas, tab_rel, tab_admin = st.tabs(["📝 Diário", "🏃‍♂️ Treino", "📜 Histórico", "❤️ Saúde", "📄 Relatórios", "⚙️ Configurações"])



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
    # 💧 HIDRATAÇÃO E CAFÉ (SEPARADOS)
    # --------------------------------------------------------
    st.markdown("### 💧 Hidratação e ☕ Café")
    st.info("Basta informar o que bebeu agora. O sistema vai SOMANDO o valor ao longo do dia.")
    
    col_w1, col_w2 = st.columns(2)
    
    with col_w1:
        with st.form("form_agua"):
            add_agua = st.number_input("➕ Adicionar Água (ml)", 0, 2000, 250, step=50)
            if st.form_submit_button("💧 Somar Água", use_container_width=True):
                executar_sql("""
                    INSERT INTO public.hidratacao (data, agua_ml, cafe_ml) 
                    VALUES (:d, :a, 0)
                    ON CONFLICT (data) DO UPDATE 
                    SET agua_ml = public.hidratacao.agua_ml + EXCLUDED.agua_ml
                """, {'d': data_hoje, 'a': add_agua})
                st.success(f"+{add_agua}ml de Água!"); st.rerun()

    with col_w2:
        with st.form("form_cafe"):
            add_cafe = st.number_input("➕ Adicionar Café (ml)", 0, 1000, 50, step=10)
            if st.form_submit_button("☕ Somar Café", use_container_width=True):
                executar_sql("""
                    INSERT INTO public.hidratacao (data, agua_ml, cafe_ml) 
                    VALUES (:d, 0, :c)
                    ON CONFLICT (data) DO UPDATE 
                    SET cafe_ml = public.hidratacao.cafe_ml + EXCLUDED.cafe_ml
                """, {'d': data_hoje, 'c': add_cafe})
                st.success(f"+{add_cafe}ml de Café!"); st.rerun()

    # --------------------------------------------------------
    # 💩 TRÂNSITO INTESTINAL (DINÂMICO E BINÁRIO)
    # --------------------------------------------------------
    st.markdown("### 💩 Trânsito Intestinal")
    with st.form("form_evac"):
        c_e1, c_e2, c_e3 = st.columns([1, 2, 1])
        data_evac = c_e1.date_input("Data da Ida", value=data_hoje, help="Altere se estiver registrando o dia de ontem.")
        tipo_bristol = c_e2.select_slider("Escala de Bristol", options=[1,2,3,4,5,6,7], value=4, help="1-2: Constipação | 3-4: Ideal | 5-7: Diarreia")
        
        st.write("") # Espaçamento vertical para alinhar o botão
        if c_e3.form_submit_button("🚽 Fui ao Banheiro (+1)", use_container_width=True):
            executar_sql("""
                INSERT INTO public.evacuacao (data, vezes, bristol) 
                VALUES (:d, 1, :b)
                ON CONFLICT (data) DO UPDATE 
                SET vezes = public.evacuacao.vezes + 1,
                    bristol = EXCLUDED.bristol
            """, {'d': data_evac, 'b': tipo_bristol})
            st.success("Ida registrada no banco!"); st.rerun()

    # --------------------------------------------------------
    # 💤 REGISTRO DE SONO
    # --------------------------------------------------------
    st.markdown("### 💤 Registro de Sono (Recuperação)")
    with st.form("form_sono"):
        c_s1, c_s2, c_s3 = st.columns([1, 1, 2])
        d_sono = c_s1.date_input("Dormiu na noite de:", value=data_hoje - timedelta(days=1), help="Referente a noite passada.")
        h_sono = c_s2.slider("Horas", 0.0, 14.0, 7.5, 0.5)
        q_sono = c_s3.select_slider("Qualidade de Sono", options=[1, 2, 3, 4, 5], value=3, help="1=Péssima | 5=Fantástica")
        
        if st.form_submit_button("💾 Salvar Sono", use_container_width=True):
            # O sono da noite anterior afeta a fisiologia do "dia_hoje", então guardamos a data em que você ACORDOU (data_hoje) 
            # para casar perfeitamente com os treinos e refeições deste dia.
            executar_sql("""
                INSERT INTO public.sono (data, horas, qualidade) 
                VALUES (:d, :h, :q)
                ON CONFLICT (data) DO UPDATE 
                SET horas = EXCLUDED.horas, qualidade = EXCLUDED.qualidade
            """, {'d': data_hoje, 'h': h_sono, 'q': q_sono})
            st.success("Sono registrado e cruzado com o dia atual!"); st.rerun()

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

st.caption("Leo Tracker Pro v9.0 | Hidratação, Sono, Trânsito Intestinal & ML 🚀")
