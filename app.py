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
    
    st.title("🦁 Leo Tracker Pro v6.2")
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
        st.error(f"❌ ERRO SQL: {e}")
        return False

# ============================================================================
# 3. SETUP E METAS
# ============================================================================
def inicializar_banco():
    executar_sql("CREATE TABLE IF NOT EXISTS public.consumo (id SERIAL PRIMARY KEY, data DATE, alimento TEXT, quantidade REAL, kcal REAL, proteina REAL, carbo REAL, gordura REAL, gluten TEXT DEFAULT 'Não informado');")
    executar_sql("CREATE TABLE IF NOT EXISTS public.peso (id SERIAL PRIMARY KEY, data DATE, peso_kg REAL);")
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

# CÁLCULOS
def calc_bf_weltman_obese(waist, weight_kg, height_cm, gender):
    if waist <= 0 or weight_kg <= 0: return 0.0
    try:
        if gender == 'Masculino': return (0.31457 * waist) - (0.10969 * weight_kg) + 10.8336
        else: return (0.11077 * waist) - (0.17666 * height_cm) + (0.14354 * weight_kg) + 51.03301
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
# 5. GERADORES
# ============================================================================
def gerar_pdf_relatorio(dias=7):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(0, 10, f"Leo Tracker - Relatorio ({dias} dias)", 0, 1, 'C')
    pdf.set_font("Arial", '', 12)
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

def gerar_excel_completo():
    output = io.BytesIO()
    df_consumo = executar_sql("SELECT * FROM public.consumo ORDER BY data DESC", is_select=True)
    df_peso = executar_sql("SELECT * FROM public.peso ORDER BY data DESC", is_select=True)
    df_medidas = executar_sql("SELECT * FROM public.body_measurements ORDER BY log_date DESC", is_select=True)
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df_consumo.to_excel(writer, sheet_name='Diario Alimentar', index=False)
        df_peso.to_excel(writer, sheet_name='Historico Peso', index=False)
        if not df_medidas.empty: df_medidas.to_excel(writer, sheet_name='Medidas Corporais', index=False)
    return output.getvalue()

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
st.sidebar.progress(min((150 - peso_atual_sidebar) / (150 - METAS['peso_alvo']), 1.0))

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

# ABAS - REORGANIZADAS
tab_daily, tab_graph, tab_logs, tab_health, tab_config = st.tabs(["📝 Diário", "📉 Peso", "📊 Análise & Logs", "❤️ Saúde", "⚙️ Export/Config"])

# --- 1. DIÁRIO ---
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
    texto_input = st.text_area("Refeição", height=80, placeholder="Ex: 3 ovos cozidos...")
    if st.button("🚀 Processar"):
        api_key = st.secrets.get("GROQ_API_KEY")
        if texto_input and api_key:
            with st.spinner("Analisando..."):
                ok_ia, res = processar_texto_ia(texto_input, api_key)
                if ok_ia:
                    st.success(res.get('analise'))
                    for item in res.get('alimentos', []):
                        k_calc = (item.get('p',0)*4 + item.get('c',0)*4 + item.get('g',0)*9)
                        k_final = max(k_calc, float(item.get('kcal', 0)))
                        params = {'dt': item.get('data') or data_hoje, 'ali': item.get('alimento'), 'qtd': item.get('quantidade_g'), 'kc': k_final, 'pr': item.get('p'), 'ca': item.get('c'), 'go': item.get('g'), 'gl': item.get('gluten')}
                        executar_sql("INSERT INTO public.consumo (data, alimento, quantidade, kcal, proteina, carbo, gordura, gluten) VALUES (:dt, :ali, :qtd, :kc, :pr, :ca, :go, :gl)", params)
                    st.cache_data.clear(); st.rerun()

    st.subheader("Hoje")
    if not df_hoje.empty:
        for i, row in df_hoje.iterrows():
            c1, c2, c3 = st.columns([3, 2, 0.5])
            c1.markdown(f"**{row['alimento']}**")
            c2.caption(f"{int(row['kcal'])} kcal | P:{int(row['proteina'])} C:{int(row['carbo']} G:{int(row['gordura'])}")
            if c3.button("🗑️", key=f"del_{row['id']}"):
                executar_sql("DELETE FROM public.consumo WHERE id=:id", {'id': row['id']})
                st.cache_data.clear(); st.rerun()
            st.markdown("---")

# --- 2. GRÁFICO PESO ---
with tab_graph:
    st.header("📉 Evolução vs Meta")
    df_peso = executar_sql("SELECT data, peso_kg FROM public.peso ORDER BY data ASC", is_select=True)
    if not df_peso.empty:
        df_peso['data'] = pd.to_datetime(df_peso['data'])
        start_date = df_peso.iloc[0]['data']
        start_weight = df_peso.iloc[0]['peso_kg']
        df_peso['semanas'] = (df_peso['data'] - start_date).dt.days / 7
        df_peso['Meta Ideal'] = start_weight - (df_peso['semanas'] * METAS['ritmo'])
        df_chart = df_peso.set_index('data')[['peso_kg', 'Meta Ideal']]
        st.line_chart(df_chart, color=["#FF4B4B", "#29B5E8"])
        
        diff = df_peso.iloc[-1]['peso_kg'] - df_peso.iloc[-1]['Meta Ideal']
        if diff < 0: st.success(f"🦁 {abs(diff):.1f} kg à frente da meta!")
        else: st.warning(f"⚠️ {diff:.1f} kg atrás da meta.")
    else: st.warning("Sem dados.")

# --- 3. ANÁLISE & LOGS (NOVA) ---
with tab_logs:
    st.header("📊 Análise de Dados")
    
    tab_resumo, tab_detalhado = st.tabs(["📅 Resumo por Dia", "📋 Extrato Detalhado"])
    
    with tab_resumo:
        # Agrupa por dia
        sql_resumo = """
            SELECT data, SUM(kcal) as "Kcal", SUM(proteina) as "Prot", SUM(carbo) as "Carb", SUM(gordura) as "Gord" 
            FROM public.consumo 
            GROUP BY data 
            ORDER BY data DESC
        """
        df_resumo = executar_sql(sql_resumo, is_select=True)
        st.dataframe(df_resumo, use_container_width=True)

    with tab_detalhado:
        # Mostra tudo
        sql_full = """
            SELECT data, alimento, quantidade, kcal, proteina as prot, carbo, gordura as gord 
            FROM public.consumo 
            ORDER BY data DESC, id DESC 
            LIMIT 200
        """
        df_full = executar_sql(sql_full, is_select=True)
        st.dataframe(df_full, use_container_width=True)

# --- 4. SAÚDE (ATUALIZADA) ---
with tab_health:
    st.header("❤️ Saúde & Medidas")
    
    c_h1, c_h2 = st.columns(2)
    
    with c_h1:
        st.subheader("🫀 Pressão Arterial")
        with st.form("bp_form"):
            sys = st.number_input("Sistólica", 90, 200, 120)
            dia = st.number_input("Diastólica", 50, 130, 80)
            pul = st.number_input("Pulso", 40, 200, 75)
            if st.form_submit_button("Salvar Pressão"):
                ok = executar_sql("INSERT INTO public.blood_pressure (systolic, diastolic, pulse, notes) VALUES (:s, :d, :p, 'App')", {'s': sys, 'd': dia, 'p': pul})
                if ok: st.success("Salvo!"); st.cache_data.clear(); st.rerun()
        
        # VISUALIZAÇÃO DA PRESSÃO
        st.write("Histórico (Últimos 10)")
        df_bp = executar_sql("SELECT measurement_time as data, systolic, diastolic, pulse FROM public.blood_pressure ORDER BY measurement_time DESC LIMIT 10", is_select=True)
        if not df_bp.empty:
            st.dataframe(df_bp, hide_index=True)

    with c_h2:
        st.subheader("📏 Avaliação Corporal")
        with st.form("medidas_form"):
            d_med = st.date_input("Data", value=data_hoje)
            p_input = st.number_input("Peso (kg)", value=peso_atual_sidebar)
            waist = st.number_input("Cintura (cm)", value=METAS['last_waist'])
            bf_weltman = calc_bf_weltman_obese(waist, p_input, METAS['altura'], METAS['genero'])
            st.info(f"BF Estimado: {bf_weltman:.1f}%")
            if st.form_submit_button("Salvar Medida"):
                 params = {'dt': d_med, 'w': p_input, 'wa': waist, 'ne': METAS['last_neck'], 'hi': METAS['last_hip'], 'bf_est': bf_weltman, 'f_pec': 0, 'f_abd': 0, 'f_thi': 0, 'f_tri': 0, 'bf_pol': 0, 'bf_wel': bf_weltman, 'nt': 'Weltman Simples'}
                 executar_sql("INSERT INTO public.body_measurements (log_date, weight_kg, waist_cm, neck_cm, hip_cm, body_fat_est, fold_chest, fold_abdominal, fold_thigh, fold_triceps, body_fat_pollock, body_fat_weltman, notes) VALUES (:dt, :w, :wa, :ne, :hi, :bf_est, :f_pec, :f_abd, :f_thi, :f_tri, :bf_pol, :bf_wel, :nt)", params)
                 executar_sql("UPDATE public.perfil SET ultima_cintura=:wa WHERE id=1", {'wa': waist})
                 executar_sql("INSERT INTO public.peso (data, peso_kg) VALUES (:dt, :w)", {'dt': d_med, 'w': p_input})
                 st.success("Salvo!"); st.cache_data.clear(); st.rerun()
        
        # VISUALIZAÇÃO DAS MEDIDAS
        st.write("Histórico (Últimos 5)")
        df_med = executar_sql("SELECT log_date as data, waist_cm as cintura, body_fat_est as bf FROM public.body_measurements ORDER BY log_date DESC LIMIT 5", is_select=True)
        if not df_med.empty:
            st.dataframe(df_med, hide_index=True)

# --- 5. EXPORT & CONFIG ---
with tab_config:
    st.header("⚙️ Configurações & Backup")
    
    st.subheader("📄 Exportar")
    c_btn1, c_btn2 = st.columns(2)
    if c_btn1.button("📄 Gerar PDF (7 dias)"):
        pdf_bytes = gerar_pdf_relatorio(7)
        st.download_button("📥 Baixar PDF", pdf_bytes, f"Relatorio_{data_hoje}.pdf", "application/pdf")
    
    if c_btn2.button("📊 Excel Completo (Backup)"):
        try:
            excel_bytes = gerar_excel_completo()
            st.download_button("📥 Baixar XLSX", excel_bytes, f"Backup_LeoTracker_{data_hoje}.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        except Exception as e: st.error(f"Erro Excel: {e}")
    
    st.divider()
    
    with st.form("form_metas"):
        st.subheader("Editar Metas")
        c_k1, c_k2 = st.columns(2)
        n_kcal = c_k1.number_input("Meta Kcal", value=METAS['kcal'])
        n_prot = c_k2.number_input("Meta Prot", value=METAS['prot'])
        c_k3, c_k4 = st.columns(2)
        n_carb = c_k3.number_input("Meta Carb", value=METAS['carb'])
        n_gord = c_k4.number_input("Meta Gord", value=METAS['gord'])
        c_p1, c_p2 = st.columns(2)
        n_peso_alvo = c_p1.number_input("Peso Alvo", value=METAS['peso_alvo'])
        n_ritmo = c_p2.number_input("Ritmo (kg/sem)", value=METAS['ritmo'])
        if st.form_submit_button("Atualizar Metas"):
            executar_sql("UPDATE public.perfil SET meta_kcal=:mk, meta_proteina=:mp, meta_carbo=:mc, meta_gordura=:mg, meta_peso_alvo=:mpa, ritmo_semanal=:rit WHERE id=1", {'mk': n_kcal, 'mp': n_prot, 'mc': n_carb, 'mg': n_gord, 'mpa': n_peso_alvo, 'rit': n_ritmo})
            st.success("Atualizado!"); st.cache_data.clear(); st.rerun()

st.caption("Leo Tracker Pro v6.2 | Data Views Restored 🦁")
