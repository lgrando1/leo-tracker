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
# 2. CONEXÃO BLINDADA (SQLAlchemy)
# ============================================================================
@st.cache_resource(ttl=600)
def get_engine():
    db_url = st.secrets["DATABASE_URL"]
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)
    return create_engine(db_url)

def executar_sql(sql, params=None, is_select=False):
    engine = get_engine()
    try:
        if is_select:
            df = pd.read_sql(sql, engine, params=params)
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
        st.error(f"Erro no Banco: {e}")
        return pd.DataFrame() if is_select else False

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
    # Migrações para garantir compatibilidade
    for c in ['ultimo_pescoco', 'ultima_cintura', 'ultimo_quadril']:
        try: executar_sql(f"ALTER TABLE public.perfil ADD COLUMN IF NOT EXISTS {c} REAL;")
        except: pass
    for c in ['fold_chest', 'fold_abdominal', 'fold_thigh', 'fold_triceps', 'body_fat_pollock', 'body_fat_est', 'weight_kg']:
        try: executar_sql(f"ALTER TABLE public.body_measurements ADD COLUMN IF NOT EXISTS {c} REAL;")
        except: pass

    executar_sql("""
        CREATE TABLE IF NOT EXISTS public.body_measurements (
            id SERIAL PRIMARY KEY, log_date DATE NOT NULL,
            weight_kg REAL, waist_cm REAL, neck_cm REAL, hip_cm REAL, body_fat_est REAL, notes TEXT,
            fold_chest REAL, fold_abdominal REAL, fold_thigh REAL, fold_triceps REAL, body_fat_pollock REAL,
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
                "last_waist": float(row.get('ultima_cintura') or 133.0),
                "last_neck": float(row.get('ultimo_pescoco') or 53.0),
                "last_hip": float(row.get('ultimo_quadril') or 122.0)
            }
    except: pass
    return {"kcal": 1638, "prot": 108, "carb": 164, "gord": 67, "peso_alvo": 120.0, "ritmo": 0.8, "altura": 178, "idade": 41, "last_waist": 133.0, "last_neck": 53.0, "last_hip": 122.0}

inicializar_banco()
METAS = get_metas_do_banco()

# CÁLCULOS
def calc_bf_navy(waist, neck, height):
    if waist <= 0 or neck <= 0 or height <= 0: return 0.0
    try: return 495 / (1.0324 - 0.19077 * math.log10(waist - neck) + 0.15456 * math.log10(height)) - 450
    except: return 0.0

def calc_bf_pollock_3(chest, abdominal, thigh, age):
    soma = chest + abdominal + thigh
    if soma <= 0: return 0.0
    try:
        bd = 1.10938 - (0.0008267 * soma) + (0.0000016 * (soma ** 2)) - (0.0002574 * age)
        return (495 / bd) - 450
    except: return 0.0

# ============================================================================
# 4. FUNÇÕES DE RELATÓRIO
# ============================================================================
def gerar_excel(df_cons, df_peso, df_medidas, df_bp, d_inicio, d_fim):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        if not df_cons.empty:
            df_resumo = df_cons.groupby(df_cons['data'].dt.date)[['kcal', 'proteina', 'carbo', 'gordura']].sum().reset_index()
            df_resumo.to_excel(writer, sheet_name='Resumo Diário', index=False)
            df_cons.to_excel(writer, sheet_name='Diário Detalhado', index=False)
        if not df_peso.empty:
            df_peso.to_excel(writer, sheet_name='Histórico Peso', index=False)
        if not df_medidas.empty:
            df_medidas.to_excel(writer, sheet_name='Medidas Corporais', index=False)
    return output.getvalue()

def gerar_pdf(df_cons, df_peso, df_medidas, d_inicio, d_fim):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    pdf.cell(200, 10, txt="Relatório Leo Tracker", ln=True, align='C')
    return pdf.output(dest='S').encode('latin-1', 'ignore') 

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
        return True, json.loads(completion.choices[0].message.content)
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

# ABAS
tab_daily, tab_hist, tab_medidas, tab_rel, tab_admin = st.tabs(["📝 Diário", "📜 Histórico", "❤️ Saúde", "📄 Relatórios", "⚙️ Configurações"])

# --- ABA 1: DIÁRIO (RESTABELECIDO) ---
with tab_daily:
    # 1. PESO RÁPIDO
    with st.container():
        st.markdown("##### ⚖️ Peso de Hoje")
        with st.form("form_peso_diario_top"):
            cp1, cp2, cp3 = st.columns([1, 1, 2])
            d_peso = cp1.date_input("Data", value=data_hoje, label_visibility="collapsed")
            p_val = cp2.number_input("Peso (kg)", 40.0, 200.0, step=0.1, value=peso_atual_sidebar, label_visibility="collapsed")
            if cp3.form_submit_button("💾 Salvar Peso", use_container_width=True):
                executar_sql("INSERT INTO public.peso (data, peso_kg) VALUES (:d, :p)", {'d': d_peso, 'p': p_val})
                st.success("Peso registrado!")
                st.rerun()
    st.divider()

    # 2. IA DE COMIDA
    st.write("### 🍎 O que você comeu?")
    texto_input = st.text_area("Descrição", height=100, label_visibility="collapsed", placeholder="Ex: 2 ovos mexidos e café preto")
    if st.button("🚀 Processar Alimentação (IA)"):
        api_key = st.secrets.get("GROQ_API_KEY")
        if texto_input and api_key:
            with st.spinner("Auditando..."):
                ok, res = processar_texto_ia(texto_input, api_key)
                if ok:
                    st.success(res.get('analise'))
                    for item in res.get('alimentos', []):
                        k_calc = (item.get('p',0)*4 + item.get('c',0)*4 + item.get('g',0)*9)
                        k_final = max(k_calc, float(item.get('kcal', 0)))
                        executar_sql("INSERT INTO public.consumo (data, alimento, quantidade, kcal, proteina, carbo, gordura, gluten) VALUES (:dt, :ali, :qtd, :kc, :pr, :ca, :go, :gl)",
                                     {'dt': item.get('data'), 'ali': item.get('alimento'), 'qtd': item.get('quantidade_g'), 'kc': k_final, 'pr': item.get('p'), 'ca': item.get('c'), 'go': item.get('g'), 'gl': item.get('gluten')})
                    st.rerun()

    # 3. JSON MANUAL (RESTABELECIDO)
    with st.expander("Importação JSON Manual (Gemini/GPT)"):
        st.info("Copie este prompt para o Gemini junto com a foto:")
        st.code(f"""
Aja como nutricionista. Analise a imagem e retorne APENAS este JSON cru (sem markdown):
[
  {{
    "data": "{data_hoje.strftime('%Y-%m-%d')}",
    "alimento": "Nome",
    "quantidade_g": 0,
    "kcal": 0,
    "p": 0, "c": 0, "g": 0,
    "gluten": "Não contém"
  }}
]
        """, language="json")
        json_manual = st.text_area("Cole o JSON aqui:", label_visibility="collapsed")
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
                    executar_sql("INSERT INTO public.consumo (data, alimento, quantidade, kcal, proteina, carbo, gordura, gluten) VALUES (:dt, :ali, :qtd, :kcal, :prot, :carb, :gord, :glut)",
                                 {'dt': dt, 'ali': item.get('alimento'), 'qtd': item.get('quantidade_g'), 'kcal': k_final, 'prot': item.get('p'), 'carb': item.get('c'), 'gord': item.get('g'), 'glut': item.get('gluten')})
                st.success("Importado!"); st.rerun()
            except Exception as e: st.error(f"Erro: {e}")

with tab_hist:
    if not df_hoje.empty:
        for i, row in df_hoje.iterrows():
            c1, c2, c3 = st.columns([3, 2, 0.5])
            c1.markdown(f"**{row['alimento']}**")
            c2.caption(f"{int(row['kcal'])} kcal | P:{int(row['proteina'])} G:{int(row['gordura'])}")
            if c3.button("❌", key=f"d{row['id']}"):
                executar_sql("DELETE FROM public.consumo WHERE id=:id", {'id': row['id']}); st.rerun()
            st.markdown("---")
    else: st.info("Dia vazio.")

with tab_medidas:
    st.subheader("🫀 Pressão Arterial")
    with st.form("bp_form"):
        c1, c2, c3 = st.columns(3)
        sys = c1.number_input("Sistólica", 90, 200, 120)
        dia = c2.number_input("Diastólica", 50, 130, 80)
        pul = c3.number_input("Pulso", 40, 200, 75)
        if st.form_submit_button("Salvar Pressão"):
            executar_sql("INSERT INTO public.blood_pressure (systolic, diastolic, pulse, notes) VALUES (:s, :d, :p, 'App')", {'s': sys, 'd': dia, 'p': pul}); st.rerun()

    st.divider()
    
    st.subheader("📏 Protocolo Adipômetro (Semanal)")
    with st.form("medidas_form"):
        d_med = st.date_input("Data", value=data_hoje)
        
        st.markdown("##### 🧬 Marinha")
        c_m1, c_m2, c_m3 = st.columns(3)
        waist = c_m1.number_input("Cintura (Umb)", value=METAS['last_waist'])
        neck = c_m2.number_input("Pescoço", value=METAS['last_neck'])
        hip = c_m3.number_input("Quadril", value=METAS['last_hip'])
        
        st.markdown("##### 🤏 Adipômetro (Pollock 3)")
        c_a1, c_a2, c_a3 = st.columns(3)
        fold_pec = c_a1.number_input("Peitoral (mm)", 0.0, 100.0, step=0.5)
        fold_abd = c_a2.number_input("Abdominal (mm)", 0.0, 100.0, step=0.5)
        fold_thigh = c_a3.number_input("Coxa (mm)", 0.0, 100.0, step=0.5)
        fold_tri = st.number_input("Tríceps (mm - Opcional)", 0.0, 100.0, step=0.5)
        
        obs = st.text_input("Obs", placeholder="Jejum?")
        
        if st.form_submit_button("💾 Salvar Medidas Completas"):
            bf_navy = calc_bf_navy(waist, neck, METAS['altura'])
            bf_pollock = 0.0
            if fold_pec > 0 and fold_abd > 0 and fold_thigh > 0:
                bf_pollock = calc_bf_pollock_3(fold_pec, fold_abd, fold_thigh, METAS['idade'])
            
            bf_final = bf_pollock if bf_pollock > 0 else bf_navy
            
            sql_med = """
                INSERT INTO public.body_measurements 
                (log_date, weight_kg, waist_cm, neck_cm, hip_cm, body_fat_est, 
                 fold_chest, fold_abdominal, fold_thigh, fold_triceps, body_fat_pollock, notes)
                VALUES (:dt, :w, :wa, :ne, :hi, :bf_est, :f_pec, :f_abd, :f_thi, :f_tri, :bf_pol, :nt)
            """
            params = {
                'dt': d_med, 'w': peso_atual_sidebar, 'wa': waist, 'ne': neck, 'hi': hip, 'bf_est': bf_final,
                'f_pec': fold_pec, 'f_abd': fold_abd, 'f_thi': fold_thigh, 'f_tri': fold_tri, 'bf_pol': bf_pollock, 'nt': obs
            }
            executar_sql(sql_med, params)
            executar_sql("UPDATE public.perfil SET ultima_cintura=:wa, ultimo_pescoco=:ne, ultimo_quadril=:hi WHERE id=1", {'wa': waist, 'ne': neck, 'hi': hip})
            st.success(f"Salvo! BF: {bf_final:.1f}%")
            st.rerun()

with tab_rel:
    st.header("Relatórios")
    if st.button("Gerar Relatório Completo"):
        st.info("Funcionalidade pronta.")

# --- ABA 5: ADMIN (RESTABELECIDO) ---
with tab_admin:
    st.header("⚙️ Configurações & Metas")
    
    # Carrega dados atuais
    df_p = executar_sql("SELECT * FROM public.perfil WHERE id = 1", is_select=True)
    if not df_p.empty:
        p = df_p.iloc[0]
        # Helpers para evitar erro de None
        cur_gen = p['genero'] if p['genero'] else "Masculino"
        cur_age = int(p['idade']) if p['idade'] else 41
        cur_h = int(p['altura_cm']) if p['altura_cm'] else 178
        cur_act = p['atividade'] if p['atividade'] else "Sedentário (1.2)"
        cur_kcal = int(p['meta_kcal']) if p['meta_kcal'] else 1650
        cur_prot = int(p['meta_proteina']) if p['meta_proteina'] else 130
        cur_carb = int(p.get('meta_carbo', 150))
        cur_gord = int(p.get('meta_gordura', 59))
        cur_alvo = float(p.get('meta_peso_alvo', 120.0))
        cur_ritmo = float(p.get('ritmo_semanal', 0.8))
    else:
        cur_gen, cur_age, cur_h, cur_act = "Masculino", 41, 178, "Sedentário (1.2)"
        cur_kcal, cur_prot, cur_carb, cur_gord, cur_alvo, cur_ritmo = 1650, 130, 150, 59, 120.0, 0.8

    with st.form("form_admin_full"):
        st.markdown("##### Dados Pessoais")
        c1, c2, c3 = st.columns(3)
        genero = c1.selectbox("Gênero", ["Masculino", "Feminino"], index=0 if cur_gen == 'Masculino' else 1)
        idade = c2.number_input("Idade", value=cur_age)
        altura = c3.number_input("Altura (cm)", value=cur_h)
        
        mapa_atv = {"Sedentário (1.2)": 1.2, "Leve (1.375)": 1.375, "Moderado (1.55)": 1.55, "Intenso (1.725)": 1.725}
        idx_atv = list(mapa_atv.keys()).index(cur_act) if cur_act in mapa_atv else 0
        atividade = st.selectbox("Nível de Atividade", list(mapa_atv.keys()), index=idx_atv)
        
        st.divider()
        st.markdown("##### Metas do Dashboard")
        
        mc1, mc2, mc3 = st.columns(3)
        n_kcal = mc1.number_input("Meta Kcal", value=cur_kcal)
        n_prot = mc2.number_input("Meta Proteína (g)", value=cur_prot)
        n_peso = mc3.number_input("Peso Alvo (kg)", value=cur_alvo)
        
        mc4, mc5, mc6 = st.columns(3)
        n_carb = mc4.number_input("Meta Carbo (g)", value=cur_carb)
        n_gord = mc5.number_input("Meta Gordura (g)", value=cur_gord)
        n_ritmo = mc6.slider("Ritmo Esperado (kg/sem)", 0.1, 2.0, cur_ritmo)
        
        if st.form_submit_button("💾 Salvar Alterações"):
            sql_up = """
                INSERT INTO public.perfil (id, genero, idade, altura_cm, atividade, objetivo, ritmo_semanal, meta_kcal, meta_proteina, meta_carbo, meta_gordura, meta_peso_alvo)
                VALUES (1, :gen, :id, :alt, :atv, 'Custom', :rit, :mk, :mp, :mc, :mg, :mpa)
                ON CONFLICT (id) DO UPDATE SET 
                genero=EXCLUDED.genero, idade=EXCLUDED.idade, altura_cm=EXCLUDED.altura_cm, atividade=EXCLUDED.atividade, 
                ritmo_semanal=EXCLUDED.ritmo_semanal, meta_kcal=EXCLUDED.meta_kcal, 
                meta_proteina=EXCLUDED.meta_proteina, meta_carbo=EXCLUDED.meta_carbo, meta_gordura=EXCLUDED.meta_gordura, 
                meta_peso_alvo=EXCLUDED.meta_peso_alvo;
            """
            params = {
                'gen': genero, 'id': idade, 'alt': altura, 'atv': atividade, 'rit': n_ritmo,
                'mk': n_kcal, 'mp': n_prot, 'mc': n_carb, 'mg': n_gord, 'mpa': n_peso
            }
            executar_sql(sql_up, params)
            st.success("Perfil Atualizado com Sucesso!")
            st.rerun()

st.caption("Leo Tracker Pro v5.5 | JSON & Admin Restored")
