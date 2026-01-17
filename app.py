import streamlit as st
import pandas as pd
from sqlalchemy import create_engine, text
from datetime import datetime, timedelta
import json
import pytz 
from groq import Groq 
import io
from fpdf import FPDF
import math

# ============================================================================
# 1. CONFIGURAÇÃO E ACESSO
# ============================================================================
st.set_page_config(page_title="Leo Tracker Pro", page_icon="🦁", layout="wide")

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
                for col in ['data', 'log_date', 'measurement_time']:
                    if col in df.columns:
                        try: df[col] = pd.to_datetime(df[col])
                        except: pass
                return df
        else:
            with engine.begin() as conn:
                conn.execute(text(sql), params)
            return True
    except Exception as e:
        # Retorna DataFrame vazio se der erro no Select para não quebrar a tela
        if is_select: return pd.DataFrame()
        return False

# ============================================================================
# 3. SINCRONIZAÇÃO DO BANCO
# ============================================================================
def inicializar_banco():
    executar_sql("CREATE TABLE IF NOT EXISTS public.consumo (id SERIAL PRIMARY KEY, data DATE, alimento TEXT, quantidade REAL, kcal REAL, proteina REAL, carbo REAL, gordura REAL, gluten TEXT DEFAULT 'Não informado');")
    executar_sql("CREATE TABLE IF NOT EXISTS public.peso (id SERIAL PRIMARY KEY, data DATE, peso_kg REAL);")
    executar_sql("""
        CREATE TABLE IF NOT EXISTS public.perfil (
            id SERIAL PRIMARY KEY, 
            genero TEXT, idade INT, altura_cm INT, atividade TEXT, 
            objetivo TEXT, ritmo_semanal REAL, 
            meta_kcal REAL, meta_proteina REAL, meta_carbo REAL, meta_gordura REAL, meta_peso_alvo REAL
        );
    """)
    # Migrações silenciosas
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
            id SERIAL PRIMARY KEY,
            measurement_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            systolic INT, diastolic INT, pulse INT, notes TEXT
        );
    """)

def get_metas_do_banco():
    try:
        df = executar_sql("SELECT * FROM public.perfil WHERE id = 1", is_select=True)
        if not df.empty:
            row = df.iloc[0]
            return {
                "kcal": int(row['meta_kcal']), "prot": int(row['meta_proteina']),
                "carb": int(row.get('meta_carbo', 164)), "gord": int(row.get('meta_gordura', 67)),
                "peso_alvo": float(row.get('meta_peso_alvo', 120.0)), "ritmo": float(row.get('ritmo_semanal', 0.8)),
                "altura": int(row.get('altura_cm', 178)),
                "idade": int(row.get('idade', 41)),
                "genero": row.get('genero', 'Masculino'),
                "last_waist": float(row.get('ultima_cintura') or 133.0),
                "last_neck": float(row.get('ultimo_pescoco') or 53.0),
                "last_hip": float(row.get('ultimo_quadril') or 122.0)
            }
    except: pass
    return {"kcal": 1638, "prot": 108, "carb": 164, "gord": 67, "peso_alvo": 120.0, "ritmo": 0.8, "altura": 178, "idade": 41, "genero": "Masculino", "last_waist": 133.0, "last_neck": 53.0, "last_hip": 122.0}

inicializar_banco()
METAS = get_metas_do_banco()

# CÁLCULOS
def calc_bf_navy(waist, neck, height):
    if waist <= 0 or neck <= 0 or height <= 0: return 0.0
    try: return 495 / (1.0324 - 0.19077 * math.log10(waist - neck) + 0.15456 * math.log10(height)) - 450
    except: return 0.0

def calc_bf_weltman_obese(waist, weight_kg, height_cm, gender):
    if waist <= 0 or weight_kg <= 0: return 0.0
    try:
        if gender == 'Masculino':
            return (0.31457 * waist) - (0.10969 * weight_kg) + 10.8336
        else:
            return (0.11077 * waist) - (0.17666 * height_cm) + (0.14354 * weight_kg) + 51.03301
    except: return 0.0

def calc_bf_pollock_3(chest, abdominal, thigh, age):
    soma = chest + abdominal + thigh
    if soma <= 0: return 0.0
    try:
        bd = 1.10938 - (0.0008267 * soma) + (0.0000016 * (soma ** 2)) - (0.0002574 * age)
        return (495 / bd) - 450
    except: return 0.0

# ============================================================================
# 5. GROQ IA (AUDITORIA)
# ============================================================================
def processar_texto_ia(texto_usuario, api_key):
    client = Groq(api_key=api_key)
    prompt_system = f"""
    Aja como Nutricionista. Hoje: {get_now_br().strftime('%Y-%m-%d')}.
    Regras: GORDURA OCULTA (fritura/grelhado = +5g gordura).
    JSON CRU: {{ "analise": "txt", "alimentos": [ {{ "data": "YYYY-MM-DD", "alimento": "txt", "quantidade_g": 0, "kcal": 0, "p": 0, "c": 0, "g": 0, "gluten": "Não contém" }} ] }}
    """
    try:
        completion = client.chat.completions.create(messages=[{"role": "system", "content": prompt_system}, {"role": "user", "content": texto_usuario}], model="llama-3.3-70b-versatile", response_format={"type": "json_object"})
        content = json.loads(completion.choices[0].message.content)
        if isinstance(content, list): content = {"analise": "Processado", "alimentos": content}
        return True, content
    except Exception as e: return False, str(e)

# ============================================================================
# 6. INTERFACE
# ============================================================================
st.title("🦁 Leo Tracker Pro")

data_hoje = get_now_br().date()
df_hoje = executar_sql("SELECT * FROM public.consumo WHERE data = %s", (data_hoje,), is_select=True)

# SIDEBAR
st.sidebar.header("🎯 Status")
ultimo_peso_df = executar_sql("SELECT peso_kg FROM public.peso ORDER BY data DESC LIMIT 1", is_select=True)
peso_atual_sidebar = float(ultimo_peso_df.iloc[0]['peso_kg']) if not ultimo_peso_df.empty else 140.0
st.sidebar.metric("Peso Atual", f"{peso_atual_sidebar} kg", f"Meta: {METAS['peso_alvo']} kg")
st.sidebar.progress(min(max(0.0, (150 - peso_atual_sidebar) / (150 - METAS['peso_alvo'])), 1.0))

# Métricas Topo
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
tab_daily, tab_hist, tab_medidas, tab_rel, tab_admin = st.tabs(["📝 Diário", "📜 Histórico", "❤️ Saúde", "📄 Relatórios", "⚙️ Configurações"])

# --- ABA 1: DIÁRIO ---
with tab_daily:
    # 1. PESO RÁPIDO
    with st.container():
        st.markdown("##### ⚖️ Peso de Hoje")
        with st.form("form_peso_diario_top"):
            cp1, cp2, cp3 = st.columns([1, 1, 2])
            d_peso = cp1.date_input("Data", value=data_hoje, label_visibility="collapsed")
            p_val = cp2.number_input("Peso (kg)", 40.0, 200.0, step=0.1, value=peso_atual_sidebar, label_visibility="collapsed")
            if cp3.form_submit_button("💾 Salvar Peso", use_container_width=True):
                ok = executar_sql("INSERT INTO public.peso (data, peso_kg) VALUES (:d, :p)", {'d': d_peso, 'p': p_val})
                if ok:
                    st.cache_resource.clear() # Limpa cache do banco
                    st.rerun()
    st.divider()

    # 2. IA DE COMIDA
    st.write("### 🍎 O que você comeu?")
    texto_input = st.text_area("Descrição", height=100, label_visibility="collapsed", placeholder="Ex: 2 ovos mexidos e café preto")
    if st.button("🚀 Processar Alimentação (IA)"):
        api_key = st.secrets.get("GROQ_API_KEY")
        if texto_input and api_key:
            with st.spinner("Auditando..."):
                ok_ia, res = processar_texto_ia(texto_input, api_key)
                if ok_ia:
                    st.success(res.get('analise'))
                    for item in res.get('alimentos', []):
                        k_calc = (item.get('p',0)*4 + item.get('c',0)*4 + item.get('g',0)*9)
                        k_final = max(k_calc, float(item.get('kcal', 0)))
                        params = {
                            'dt': item.get('data') or data_hoje, 
                            'ali': item.get('alimento'), 'qtd': item.get('quantidade_g'), 
                            'kc': k_final, 'pr': item.get('p'), 'ca': item.get('c'), 'go': item.get('g'), 'gl': item.get('gluten')
                        }
                        ok_db = executar_sql("INSERT INTO public.consumo (data, alimento, quantidade, kcal, proteina, carbo, gordura, gluten) VALUES (:dt, :ali, :qtd, :kc, :pr, :ca, :go, :gl)", params)
                        if not ok_db: st.stop()
                    
                    st.cache_resource.clear()
                    st.rerun()

    # 3. JSON MANUAL
    with st.expander("Importação JSON Manual"):
        st.info("Para quando a IA falhar.")
        json_manual = st.text_area("JSON", label_visibility="collapsed")
        if st.button("Salvar JSON"):
            try:
                cleaned = json_manual.replace('```json', '').replace('```', '')
                start, end = cleaned.find('['), cleaned.rfind(']')
                if start != -1 and end != -1: cleaned = cleaned[start:end+1]
                lista = json.loads(cleaned)
                for item in (lista if isinstance(lista, list) else [lista]):
                    dt = item.get('data') if item.get('data') else data_hoje
                    k_calc = (float(item.get('p',0))*4 + float(item.get('c',0))*4 + float(item.get('g',0))*9)
                    k_final = max(k_calc, float(item.get('kcal', 0)))
                    params = {
                        'dt': dt, 'ali': item.get('alimento'), 'qtd': item.get('quantidade_g'), 
                        'kcal': k_final, 'prot': item.get('p'), 'carb': item.get('c'), 'gord': item.get('g'), 'glut': item.get('gluten')
                    }
                    executar_sql("INSERT INTO public.consumo (data, alimento, quantidade, kcal, proteina, carbo, gordura, gluten) VALUES (:dt, :ali, :qtd, :kcal, :prot, :carb, :gord, :glut)", params)
                st.cache_resource.clear()
                st.rerun()
            except Exception as e: st.error(f"Erro: {e}")

    # 4. LISTA DO DIA (Restaurada para a Tela Principal)
    st.subheader("Hoje")
    if not df_hoje.empty:
        for i, row in df_hoje.iterrows():
            c1, c2, c3 = st.columns([3, 2, 0.5])
            c1.markdown(f"**{row['alimento']}**")
            c2.caption(f"{int(row['kcal'])} kcal | P:{int(row['proteina'])} G:{int(row['gordura'])}")
            if c3.button("❌", key=f"del_daily_{row['id']}"):
                executar_sql("DELETE FROM public.consumo WHERE id=:id", {'id': row['id']})
                st.cache_resource.clear()
                st.rerun()
            st.markdown("---")
    else: st.info("Nada registrado hoje.")

with tab_hist:
    st.write("Histórico Geral")
    if not df_hoje.empty:
        st.dataframe(df_hoje)

with tab_medidas:
    st.subheader("🫀 Pressão Arterial")
    with st.form("bp_form"):
        c1, c2, c3 = st.columns(3)
        sys = c1.number_input("Sistólica", 90, 200, 120)
        dia = c2.number_input("Diastólica", 50, 130, 80)
        pul = c3.number_input("Pulso", 40, 200, 75)
        if st.form_submit_button("Salvar Pressão"):
            ok = executar_sql("INSERT INTO public.blood_pressure (systolic, diastolic, pulse, notes) VALUES (:s, :d, :p, 'App')", {'s': sys, 'd': dia, 'p': pul})
            if ok: st.rerun()

    st.divider()
    st.subheader("📏 Avaliação Corporal (Weltman)")
    with st.form("medidas_form"):
        d_med = st.date_input("Data", value=data_hoje)
        c_m1, c_m2 = st.columns(2)
        p_input = c_m1.number_input("Peso Atual (kg)", 40.0, 200.0, step=0.1, value=peso_atual_sidebar)
        waist = c_m2.number_input("Cintura (Umbigo) cm", 50.0, 200.0, step=0.5, value=METAS['last_waist'])
        
        bf_weltman = calc_bf_weltman_obese(waist, p_input, METAS['altura'], METAS['genero'])
        st.info(f"🧬 **BF Weltman: {bf_weltman:.1f}%**")

        if st.form_submit_button("Salvar Avaliação"):
            params = {'dt': d_med, 'w': p_input, 'wa': waist, 'ne': METAS['last_neck'], 'hi': METAS['last_hip'], 'bf_est': bf_weltman, 'f_pec': 0, 'f_abd': 0, 'f_thi': 0, 'f_tri': 0, 'bf_pol': 0, 'bf_wel': bf_weltman, 'nt': 'Weltman Simples'}
            sql_med = "INSERT INTO public.body_measurements (log_date, weight_kg, waist_cm, neck_cm, hip_cm, body_fat_est, fold_chest, fold_abdominal, fold_thigh, fold_triceps, body_fat_pollock, body_fat_weltman, notes) VALUES (:dt, :w, :wa, :ne, :hi, :bf_est, :f_pec, :f_abd, :f_thi, :f_tri, :bf_pol, :bf_wel, :nt)"
            executar_sql(sql_med, params)
            executar_sql("INSERT INTO public.peso (data, peso_kg) VALUES (:dt, :w)", {'dt': d_med, 'w': p_input})
            executar_sql("UPDATE public.perfil SET ultima_cintura=:wa WHERE id=1", {'wa': waist})
            st.cache_resource.clear()
            st.rerun()

with tab_rel:
    st.header("Relatórios")
    if st.button("Gerar Relatório"): st.info("Pronto.")

with tab_admin:
    st.header("⚙️ Configurações & Metas")
    with st.form("form_admin_simple"):
        n_peso = st.number_input("Peso Alvo (kg)", value=METAS['peso_alvo'])
        if st.form_submit_button("Salvar"):
             executar_sql("UPDATE public.perfil SET meta_peso_alvo=:p WHERE id=1", {'p': n_peso})
             st.rerun()

st.caption("Leo Tracker Pro v5.9 | List Restored")
