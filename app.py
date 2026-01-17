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
    
    st.title("🦁 Leo Tracker Pro v6.0")
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
            with engine.begin() as conn: # Engine.begin abre transação e dá auto-commit
                conn.execute(text(sql), params)
            return True
    except Exception as e:
        st.error(f"❌ ERRO SQL: {e}")
        return False

# ============================================================================
# 3. SETUP E METAS
# ============================================================================
def inicializar_banco():
    # Tabelas Core
    executar_sql("CREATE TABLE IF NOT EXISTS public.consumo (id SERIAL PRIMARY KEY, data DATE, alimento TEXT, quantidade REAL, kcal REAL, proteina REAL, carbo REAL, gordura REAL, gluten TEXT DEFAULT 'Não informado');")
    executar_sql("CREATE TABLE IF NOT EXISTS public.peso (id SERIAL PRIMARY KEY, data DATE, peso_kg REAL);")
    
    # Tabela Perfil (Garante que existe linha 1)
    executar_sql("""
        CREATE TABLE IF NOT EXISTS public.perfil (
            id SERIAL PRIMARY KEY, 
            genero TEXT, idade INT, altura_cm INT, atividade TEXT, 
            objetivo TEXT, ritmo_semanal REAL, 
            meta_kcal REAL, meta_proteina REAL, meta_carbo REAL, meta_gordura REAL, meta_peso_alvo REAL,
            ultima_cintura REAL, ultimo_pescoco REAL, ultimo_quadril REAL
        );
    """)
    res = executar_sql("SELECT count(*) as c FROM public.perfil", is_select=True)
    if res.iloc[0]['c'] == 0:
        executar_sql("INSERT INTO public.perfil (id, meta_kcal, meta_proteina, meta_carbo, meta_gordura, ritmo_semanal, meta_peso_alvo) VALUES (1, 1638, 108, 164, 67, 0.8, 120.0)")

    # Tabelas Auxiliares
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
            id SERIAL PRIMARY KEY, measurement_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            systolic INT, diastolic INT, pulse INT, notes TEXT
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
                "last_waist": float(row.get('ultima_cintura') or 133.0),
                "last_neck": float(row.get('ultimo_pescoco') or 53.0),
                "last_hip": float(row.get('ultimo_quadril') or 122.0)
            }
    except: pass
    return {"kcal": 1638, "prot": 108, "carb": 164, "gord": 67, "peso_alvo": 120.0, "ritmo": 0.8, "altura": 178, "idade": 41, "genero": "Masculino", "last_waist": 133.0, "last_neck": 53.0, "last_hip": 122.0}

inicializar_banco()
METAS = get_metas_do_banco()

# CÁLCULOS BF
def calc_bf_navy(waist, neck, height):
    if waist <= 0 or neck <= 0 or height <= 0: return 0.0
    try: return 495 / (1.0324 - 0.19077 * math.log10(waist - neck) + 0.15456 * math.log10(height)) - 450
    except: return 0.0

def calc_bf_weltman_obese(waist, weight_kg, height_cm, gender):
    if waist <= 0 or weight_kg <= 0: return 0.0
    try:
        if gender == 'Masculino': return (0.31457 * waist) - (0.10969 * weight_kg) + 10.8336
        else: return (0.11077 * waist) - (0.17666 * height_cm) + (0.14354 * weight_kg) + 51.03301
    except: return 0.0

def calc_bf_pollock_3(chest, abdominal, thigh, age):
    soma = chest + abdominal + thigh
    if soma <= 0: return 0.0
    try:
        bd = 1.10938 - (0.0008267 * soma) + (0.0000016 * (soma ** 2)) - (0.0002574 * age)
        return (495 / bd) - 450
    except: return 0.0

# ============================================================================
# 4. IA GROQ
# ============================================================================
def processar_texto_ia(texto_usuario, api_key):
    client = Groq(api_key=api_key)
    prompt_system = f"""
    Aja como Nutricionista. Data de hoje: {get_now_br().strftime('%Y-%m-%d')}.
    Regra: Identifique a refeição. Adicione GORDURA OCULTA (fritura/grelhado = +5g gordura).
    Retorne JSON CRU: {{ "analise": "Resumo curto", "alimentos": [ {{ "data": "YYYY-MM-DD", "alimento": "Nome", "quantidade_g": 0, "kcal": 0, "p": 0, "c": 0, "g": 0, "gluten": "Não contém" }} ] }}
    """
    try:
        completion = client.chat.completions.create(messages=[{"role": "system", "content": prompt_system}, {"role": "user", "content": texto_usuario}], model="llama-3.3-70b-versatile", response_format={"type": "json_object"})
        return True, json.loads(completion.choices[0].message.content)
    except Exception as e: return False, str(e)

# ============================================================================
# 5. GERADOR DE RELATÓRIO PDF
# ============================================================================
def gerar_pdf_relatorio(dias=7):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(0, 10, f"Leo Tracker - Relatorio ({dias} dias)", 0, 1, 'C')
    pdf.set_font("Arial", '', 12)
    
    # Dados
    dt_inicio = (get_now_br() - timedelta(days=dias)).date()
    df_con = executar_sql(f"SELECT data, sum(kcal) as k, sum(proteina) as p, sum(carbo) as c, sum(gordura) as g FROM public.consumo WHERE data >= '{dt_inicio}' GROUP BY data ORDER BY data", is_select=True)
    
    if not df_con.empty:
        pdf.ln(5)
        pdf.set_font("Arial", 'B', 12)
        pdf.cell(0, 10, "Media de Consumo:", 0, 1)
        pdf.set_font("Arial", '', 12)
        media_k = df_con['k'].mean()
        media_p = df_con['p'].mean()
        pdf.cell(0, 8, f"Calorias: {media_k:.0f} kcal (Meta: {METAS['kcal']})", 0, 1)
        pdf.cell(0, 8, f"Proteina: {media_p:.0f} g (Meta: {METAS['prot']})", 0, 1)
        pdf.ln(5)
        
        # Tabela Simples
        pdf.set_font("Arial", 'B', 10)
        pdf.cell(30, 8, "Data", 1)
        pdf.cell(25, 8, "Kcal", 1)
        pdf.cell(25, 8, "Prot", 1)
        pdf.cell(25, 8, "Carb", 1)
        pdf.cell(25, 8, "Gord", 1)
        pdf.ln()
        pdf.set_font("Arial", '', 10)
        for _, row in df_con.iterrows():
            pdf.cell(30, 8, str(row['data'].strftime('%d/%m')), 1)
            pdf.cell(25, 8, str(int(row['k'])), 1)
            pdf.cell(25, 8, str(int(row['p'])), 1)
            pdf.cell(25, 8, str(int(row['c'])), 1)
            pdf.cell(25, 8, str(int(row['g'])), 1)
            pdf.ln()
            
    return pdf.output(dest='S').encode('latin-1')

# ============================================================================
# 6. INTERFACE PRINCIPAL
# ============================================================================
st.title("🦁 Leo Tracker Pro")

data_hoje = get_now_br().date()
df_hoje = executar_sql("SELECT * FROM public.consumo WHERE data = %s", (data_hoje,), is_select=True)

# SIDEBAR (Resumo Rápido)
st.sidebar.header("🎯 Status")
ultimo_peso_df = executar_sql("SELECT peso_kg FROM public.peso ORDER BY data DESC LIMIT 1", is_select=True)
peso_atual_sidebar = float(ultimo_peso_df.iloc[0]['peso_kg']) if not ultimo_peso_df.empty else 140.0
st.sidebar.metric("Peso Atual", f"{peso_atual_sidebar} kg", f"Meta: {METAS['peso_alvo']} kg")
st.sidebar.progress(min((150 - peso_atual_sidebar) / (150 - METAS['peso_alvo']), 1.0))

# Métricas Topo (Consumo Hoje)
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
tab_daily, tab_hist, tab_medidas, tab_rel, tab_admin = st.tabs(["📝 Diário", "📜 Histórico / Gráfico", "❤️ Saúde", "📄 Relatórios", "⚙️ Metas & Config"])

# --- ABA 1: DIÁRIO ---
with tab_daily:
    st.write("### ⚖️ Registro Rápido")
    with st.form("form_peso_diario_top"):
        cp1, cp2, cp3 = st.columns([1, 1, 2])
        d_peso = cp1.date_input("Data", value=data_hoje, label_visibility="collapsed")
        p_val = cp2.number_input("Peso (kg)", 40.0, 200.0, step=0.1, value=peso_atual_sidebar, label_visibility="collapsed")
        if cp3.form_submit_button("💾 Salvar Peso", use_container_width=True):
            ok = executar_sql("INSERT INTO public.peso (data, peso_kg) VALUES (:d, :p)", {'d': d_peso, 'p': p_val})
            if ok: st.cache_data.clear(); st.rerun()
    
    st.divider()
    
    st.write("### 🍎 Refeições (IA)")
    texto_input = st.text_area("Descreva sua refeição:", height=80, placeholder="Ex: 3 ovos cozidos e 30g de queijo meia cura")
    if st.button("🚀 Processar"):
        api_key = st.secrets.get("GROQ_API_KEY")
        if texto_input and api_key:
            with st.spinner("Analisando com Llama 3..."):
                ok_ia, res = processar_texto_ia(texto_input, api_key)
                if ok_ia:
                    st.success(res.get('analise'))
                    for item in res.get('alimentos', []):
                        k_calc = (item.get('p',0)*4 + item.get('c',0)*4 + item.get('g',0)*9)
                        k_final = max(k_calc, float(item.get('kcal', 0)))
                        params = {
                            'dt': item.get('data') or data_hoje, 'ali': item.get('alimento'), 
                            'qtd': item.get('quantidade_g'), 'kc': k_final, 
                            'pr': item.get('p'), 'ca': item.get('c'), 'go': item.get('g'), 'gl': item.get('gluten')
                        }
                        executar_sql("INSERT INTO public.consumo (data, alimento, quantidade, kcal, proteina, carbo, gordura, gluten) VALUES (:dt, :ali, :qtd, :kc, :pr, :ca, :go, :gl)", params)
                    st.cache_data.clear()
                    st.rerun()

    # Import JSON Manual (Backup)
    with st.expander("Importação JSON Manual"):
        st.caption("Cole o JSON gerado pelo Gemini aqui se a IA falhar.")
        json_manual = st.text_area("JSON", label_visibility="collapsed")
        if st.button("Importar JSON"):
            try:
                cleaned = json_manual.replace('```json', '').replace('```', '')
                start, end = cleaned.find('['), cleaned.rfind(']')
                if start != -1: cleaned = cleaned[start:end+1]
                lista = json.loads(cleaned)
                for item in (lista if isinstance(lista, list) else [lista]):
                    k_final = max((float(item.get('p',0))*4 + float(item.get('c',0))*4 + float(item.get('g',0))*9), float(item.get('kcal',0)))
                    params = {'dt': item.get('data', data_hoje), 'ali': item.get('alimento'), 'qtd': item.get('quantidade_g'), 'kc': k_final, 'pr': item.get('p'), 'ca': item.get('c'), 'go': item.get('g'), 'gl': item.get('gluten')}
                    executar_sql("INSERT INTO public.consumo (data, alimento, quantidade, kcal, proteina, carbo, gordura, gluten) VALUES (:dt, :ali, :qtd, :kc, :pr, :ca, :go, :gl)", params)
                st.cache_data.clear(); st.rerun()
            except Exception as e: st.error(f"Erro: {e}")

    # Listagem de Hoje
    st.subheader("Hoje")
    if not df_hoje.empty:
        for i, row in df_hoje.iterrows():
            c1, c2, c3 = st.columns([3, 2, 0.5])
            c1.markdown(f"**{row['alimento']}**")
            c2.caption(f"{int(row['kcal'])} kcal | P:{int(row
