import streamlit as st
import pandas as pd
from sqlalchemy import create_engine, text
from datetime import datetime, timedelta
import json
import pytz 
from groq import Groq 
import io
import math
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# ============================================================================
# 1. CONFIGURAÇÃO E ACESSO
# ============================================================================
st.set_page_config(page_title="Leo Tracker Pro", page_icon="🦁", layout="wide", initial_sidebar_state="expanded")

# CSS para métricas estilo Dashboard
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
        if is_select: return pd.DataFrame()
        return False

# ============================================================================
# 3. SINCRONIZAÇÃO E METAS
# ============================================================================
def inicializar_banco():
    executar_sql("CREATE TABLE IF NOT EXISTS public.consumo (id SERIAL PRIMARY KEY, data DATE, alimento TEXT, quantidade REAL, kcal REAL, proteina REAL, carbo REAL, gordura REAL, gluten TEXT DEFAULT 'Não informado');")
    executar_sql("CREATE TABLE IF NOT EXISTS public.peso (id SERIAL PRIMARY KEY, data DATE, peso_kg REAL);")
    executar_sql("CREATE TABLE IF NOT EXISTS public.perfil (id SERIAL PRIMARY KEY, genero TEXT, idade INT, altura_cm INT, atividade TEXT, objetivo TEXT, ritmo_semanal REAL, meta_kcal REAL, meta_proteina REAL, meta_carbo REAL, meta_gordura REAL, meta_peso_alvo REAL);")
    for c in ['ultimo_pescoco', 'ultima_cintura', 'ultimo_quadril']:
        try: executar_sql(f"ALTER TABLE public.perfil ADD COLUMN IF NOT EXISTS {c} REAL;")
        except: pass
    executar_sql("CREATE TABLE IF NOT EXISTS public.body_measurements (id SERIAL PRIMARY KEY, log_date DATE NOT NULL, weight_kg REAL, waist_cm REAL, neck_cm REAL, hip_cm REAL, body_fat_est REAL, notes TEXT, fold_chest REAL, fold_abdominal REAL, fold_thigh REAL, fold_triceps REAL, body_fat_pollock REAL, body_fat_weltman REAL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);")
    executar_sql("CREATE TABLE IF NOT EXISTS public.blood_pressure (id SERIAL PRIMARY KEY, measurement_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP, systolic INT, diastolic INT, pulse INT, notes TEXT);")

def get_metas_do_banco():
    try:
        df = executar_sql("SELECT * FROM public.perfil WHERE id = 1", is_select=True)
        if not df.empty:
            row = df.iloc[0]
            return {
                "kcal": int(row.get('meta_kcal', 1638)), "prot": int(row.get('meta_proteina', 108)),
                "carb": int(row.get('meta_carbo', 164)), "gord": int(row.get('meta_gordura', 67)),
                "peso_alvo": float(row.get('meta_peso_alvo', 120.0)), "ritmo_semanal": float(row.get('ritmo_semanal', 0.8)),
                "altura_cm": int(row.get('altura_cm', 178)), "idade": int(row.get('idade', 41)),
                "genero": row.get('genero', 'Masculino'), "last_waist": float(row.get('ultima_cintura') or 133.0),
                "last_neck": float(row.get('ultimo_pescoco') or 53.0), "last_hip": float(row.get('ultimo_quadril') or 122.0)
            }
    except: pass
    return {"kcal": 1638, "prot": 108, "carb": 164, "gord": 67, "peso_alvo": 120.0, "ritmo_semanal": 0.8, "altura_cm": 178, "idade": 41, "genero": "Masculino", "last_waist": 133.0, "last_neck": 53.0, "last_hip": 122.0}

inicializar_banco()
p = get_metas_do_banco() # 'p' para compatibilidade com código do dash
METAS = p 

# ============================================================================
# 4. FUNÇÕES DE CÁLCULO
# ============================================================================
def calc_bf_weltman_obese(waist, weight_kg, height_cm, gender):
    if waist <= 0 or weight_kg <= 0: return 0.0
    try:
        if gender == 'Masculino': return (0.31457 * waist) - (0.10969 * weight_kg) + 10.8336
        else: return (0.11077 * waist) - (0.17666 * height_cm) + (0.14354 * weight_kg) + 51.03301
    except: return 0.0

def processar_texto_ia(texto_usuario, api_key):
    client = Groq(api_key=api_key)
    prompt_system = f"""Aja como Nutricionista Matemático. Hoje: {get_now_br().strftime('%Y-%m-%d')}.
    DIRETRIZES RÍGIDAS DE CÁLCULO: (Densidades: Vegetais 0.3, Arroz 1.3, Carnes 1.5, Bolos 3.0, Queijos 4-9 kcal/g).
    GORDURA OCULTA: Restaurante/Grelhado +5g a +10g. Retorne APENAS JSON:
    {{ "analise": "txt", "alimentos": [ {{ "data": "YYYY-MM-DD", "alimento": "txt", "quantidade_g": 0, "kcal": 0, "p": 0, "c": 0, "g": 0, "gluten": "txt" }} ] }}"""
    try:
        completion = client.chat.completions.create(messages=[{"role": "system", "content": prompt_system}, {"role": "user", "content": texto_usuario}], model="llama-3.3-70b-versatile", response_format={"type": "json_object"})
        raw = completion.choices[0].message.content
        cleaned = raw.replace("```json", "").replace("```", "").strip()
        start, end = cleaned.find('{'), cleaned.rfind('}')
        if start != -1 and end != -1: cleaned = cleaned[start:end+1]
        content = json.loads(cleaned)
        return True, content
    except Exception as e: return False, str(e)

def gerar_excel_nutri(dt_ini, dt_fim):
    output = io.BytesIO()
    params = {'d1': dt_ini, 'd2': dt_fim}
    df_det = executar_sql("SELECT data, alimento, quantidade, kcal, proteina, carbo, gordura FROM public.consumo WHERE data >= :d1 AND data <= :d2 ORDER BY data DESC", params, True)
    df_p = executar_sql("SELECT data, peso_kg FROM public.peso WHERE data >= :d1 AND data <= :d2 ORDER BY data ASC", params, True)
    df_m = executar_sql("SELECT log_date as data, weight_kg as peso, waist_cm as cintura, body_fat_est as bf_estimado FROM public.body_measurements WHERE log_date >= :d1 AND log_date <= :d2 ORDER BY log_date DESC", params, True)
    df_bp = executar_sql("SELECT measurement_time as data_hora, systolic, diastolic, pulse FROM public.blood_pressure WHERE measurement_time >= :d1 AND measurement_time <= :d2 ORDER BY measurement_time DESC", params, True)
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df_det.to_excel(writer, sheet_name='Diário', index=False)
        df_p.to_excel(writer, sheet_name='Peso', index=False)
        df_m.to_excel(writer, sheet_name='Medidas', index=False)
        df_bp.to_excel(writer, sheet_name='Pressão', index=False)
    return output.getvalue()

# ============================================================================
# 5. BUSCA DE DADOS UNIFICADA
# ============================================================================
hoje = get_now_br().date()
df_peso_all = executar_sql("SELECT * FROM public.peso ORDER BY data ASC", is_select=True)
df_peso_last = executar_sql("SELECT peso_kg FROM public.peso ORDER BY data DESC, id DESC LIMIT 1", is_select=True)
df_medidas = executar_sql("SELECT * FROM public.body_measurements ORDER BY log_date ASC", is_select=True)
df_bp = executar_sql("SELECT * FROM public.blood_pressure ORDER BY measurement_time ASC", is_select=True)
df_hoje = executar_sql("SELECT * FROM public.consumo WHERE data = :d", {"d": hoje}, is_select=True)

DATA_INICIO_DASH = pd.to_datetime("2025-12-30").date()
df_hist_dash = executar_sql("""
    SELECT data, SUM(kcal) as tkcal, SUM(proteina) as tprot, SUM(carbo) as tcarb, 
           SUM(gordura) as tgord, SUM(quantidade) as tqtd
    FROM public.consumo WHERE data >= :d GROUP BY data ORDER BY data ASC
""", {"d": DATA_INICIO_DASH}, is_select=True)

PESO_ATUAL = float(df_peso_last.iloc[0]['peso_kg']) if not df_peso_last.empty else 141.9
k_act, p_act, c_act, g_act = (df_hoje['kcal'].sum(), df_hoje['proteina'].sum(), df_hoje['carbo'].sum(), df_hoje['gordura'].sum()) if not df_hoje.empty else (0,0,0,0)

# ============================================================================
# 6. INTERFACE
# ============================================================================
st.title("🦁 Leo Tracker Pro")

# SIDEBAR (Preservada do App.py)
st.sidebar.header("🎯 Status")
st.sidebar.metric("Peso Atual", f"{PESO_ATUAL} kg", f"Meta: {p['meta_peso_alvo']} kg")
st.sidebar.progress(min(max(0.0, (150 - PESO_ATUAL) / (150 - p['meta_peso_alvo'])), 1.0))

tab_dash, tab_daily, tab_hist, tab_saude, tab_rel, tab_admin = st.tabs(["📊 Visão Geral", "📝 Diário", "📜 Histórico", "❤️ Saúde", "📄 Relatórios", "⚙️ Configurações"])

# --- ABA 1: VISÃO GERAL (DASHBOARD) ---
with tab_dash:
    st.markdown(f"### 🦁 Leo's Performance | {hoje.strftime('%d/%m')}")
    
    # Variáveis de Saúde p/ Dash
    last_sys, last_dia, last_pulse = ("--", "--", "--")
    if not df_bp.empty:
        last_bp = df_bp.iloc[-1]
        last_sys, last_dia, last_pulse = last_bp['systolic'], last_bp['diastolic'], last_bp.get('pulse', "--")
    
    meta_agua = round((PESO_ATUAL * 35) / 1000, 1)

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("🔥 Calorias", f"{int(k_act)}", f"Meta: {p['meta_kcal']}")
    c2.metric("🥩 Proteína", f"{int(p_act)}g", f"Meta: {p['meta_proteina']}g")
    c3.metric("💧 Água", f"{meta_agua}L", "Meta Mínima")
    c4.metric("❤️ Pressão", f"{last_sys}x{last_dia}", f"Pulso: {last_pulse}")
    c5.metric("⚖️ Peso", f"{PESO_ATUAL}kg", f"Alvo: {p['meta_peso_alvo']}")

    st.divider()
    st.subheader("🎯 Projeção vs. Realidade")
    if not df_peso_all.empty:
        df_p_proj = df_peso_all.copy()
        df_p_proj['data_dt'] = pd.to_datetime(df_p_proj['data']).dt.date
        BASE_DATE = pd.to_datetime("2025-12-31").date()
        df_base = df_p_proj[df_p_proj['data_dt'] >= BASE_DATE].sort_values('data_dt')
        
        if not df_base.empty:
            peso_inicial = float(df_base.iloc[0]['peso_kg'])
            datas_proj = pd.date_range(start=BASE_DATE, end=hoje)
            ritmo_diario = p['ritmo_semanal'] / 7
            pesos_estimados = [peso_inicial - (i * ritmo_diario) for i in range(len(datas_proj))]
            peso_esperado_hoje = peso_inicial - ((hoje - BASE_DATE).days * ritmo_diario)
            dias_diff = (PESO_ATUAL - peso_esperado_hoje) / ritmo_diario
            
            cp1, cp2, cp3 = st.columns([2, 1, 1])
            with cp1:
                fig_proj = go.Figure()
                fig_proj.add_trace(go.Scatter(x=datas_proj, y=pesos_estimados, mode='lines', name='Meta', line=dict(color='#29B5E8', dash='dash')))
                fig_proj.add_trace(go.Scatter(x=df_base['data_dt'], y=df_base['peso_kg'], mode='lines+markers', name='Real', line=dict(color='#FF4B4B', width=3)))
                fig_proj.update_layout(height=350, margin=dict(l=10,r=10,t=20,b=10), legend=dict(orientation="h", y=1.1))
                st.plotly_chart(fig_proj, use_container_width=True)
            with cp2:
                st.write(""); st.metric("Peso Esperado (Hoje)", f"{peso_esperado_hoje:.1f} kg")
                status_cor = "normal" if dias_diff <= 0 else "inverse"
                st.metric("Status vs Cronograma", f"{abs(dias_diff):.1f} dias", "Adiantado" if dias_diff <= 0 else "Atrasado", delta_color=status_cor)
            with cp3:
                st.write(""); meta_atingir = PESO_ATUAL - p['meta_peso_alvo']
                st.metric("Distância do Alvo", f"{meta_atingir:.1f} kg")
                st.metric("Previsão de Chegada", (hoje + timedelta(weeks=meta_atingir/p['ritmo_semanal'])).strftime('%d/%m/%y'))

    st.divider()
    st.subheader("📉 Inteligência de Perda de Peso")
    col_a1, col_a2 = st.columns([2, 1])
    with col_a1:
        if not df_peso_all.empty:
            df_p_trend = df_peso_all.copy()
            df_p_trend['media_movel'] = df_p_trend['peso_kg'].rolling(window=7, min_periods=1).mean()
            fig_trend = go.Figure()
            fig_trend.add_trace(go.Scatter(x=df_p_trend['data'], y=df_p_trend['peso_kg'], mode='markers', name='Diário', marker=dict(color='gray', opacity=0.4)))
            fig_trend.add_trace(go.Scatter(x=df_p_trend['data'], y=df_p_trend['media_movel'], mode='lines', name='Tendência 7d', line=dict(color='#2ecc71', width=4)))
            fig_trend.update_layout(height=300, margin=dict(l=10,r=10,t=20,b=10), legend=dict(orientation="h", y=1.1))
            st.plotly_chart(fig_trend, use_container_width=True)
    with col_a2:
        st.markdown("##### 🏦 Banco de Gordura")
        if not df_hist_dash.empty and not df_peso_all.empty:
            df_h_b = df_hist_dash.copy(); df_p_b = df_peso_all.copy()
            df_h_b['data_dt'] = pd.to_datetime(df_h_b['data']).dt.date
            df_p_b['data_dt'] = pd.to_datetime(df_p_b['data']).dt.date
            df_merged = pd.merge(df_h_b, df_p_b[['data_dt', 'peso_kg']], on='data_dt', how='left').ffill()
            df_merged['get_dia'] = ((10 * df_merged['peso_kg']) + (6.25 * p['altura_cm']) - (5 * p['idade']) + 5) * 1.09 * 1.2
            deficit_total = (df_merged['get_dia'] - df_merged['tkcal']).sum()
            st.metric("Déficit Acumulado", f"{int(deficit_total)} kcal")
            st.metric("Gordura Eliminada (Teórica)", f"{(deficit_total/7700):.2f} kg")

    st.divider()
    st.subheader("🧬 Saúde & Composição Corporal")
    if not df_medidas.empty:
        l_m = df_medidas.iloc[-1]
        def safe_get(key, default=0.0):
            val = l_m.get(key); return float(val) if pd.notna(val) else default
        bf_est = safe_get('body_fat_est'); waist_val = safe_get('waist_cm')
        rcq = waist_val / safe_get('hip_cm') if safe_get('hip_cm') > 0 else 0
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("🐷 Gordura (Est.)", f"{bf_est:.1f}%")
        m2.metric("📏 Cintura", f"{waist_val} cm")
        m3.metric("🫀 Risco (RCQ)", f"{rcq:.2f}", "Moderado" if rcq > 0.9 else "Baixo")
        m4.metric("📐 Quadril", f"{safe_get('hip_cm')} cm")

# --- ABA 2: DIÁRIO (REGISTRO) ---
with tab_daily:
    with st.container():
        st.markdown("##### ⚖️ Peso de Hoje")
        with st.form("form_peso_diario_top"):
            cp1, cp2, cp3 = st.columns([1, 1, 2])
            d_peso_in = cp1.date_input("Data", value=hoje, label_visibility="collapsed")
            p_val_in = cp2.number_input("Peso (kg)", 40.0, 200.0, step=0.1, value=PESO_ATUAL, label_visibility="collapsed")
            if cp3.form_submit_button("💾 Salvar Peso", use_container_width=True):
                executar_sql("INSERT INTO public.peso (data, peso_kg) VALUES (:d, :p)", {'d': d_peso_in, 'p': p_val_in})
                st.cache_resource.clear(); st.rerun()
    st.divider()
    st.write("### 🍎 O que você comeu?")
    texto_input = st.text_area("Descrição", height=100, label_visibility="collapsed", placeholder="Ex: 2 ovos mexidos e café preto")
    if st.button("🚀 Processar Alimentação (IA)"):
        if texto_input:
            with st.spinner("Auditando..."):
                ok_ia, res = processar_texto_ia(texto_input, st.secrets["GROQ_API_KEY"])
                if ok_ia:
                    st.success(res.get('analise'))
                    for i in res.get('alimentos', []):
                        k_f = max((i.get('p',0)*4 + i.get('c',0)*4 + i.get('g',0)*9), float(i.get('kcal',0)))
                        params = {'dt': i.get('data') or hoje, 'ali': i.get('alimento'), 'qtd': i.get('quantidade_g'), 'kc': k_f, 'pr': i.get('p'), 'ca': i.get('c'), 'go': i.get('g'), 'gl': i.get('gluten')}
                        executar_sql("INSERT INTO public.consumo (data, alimento, quantidade, kcal, proteina, carbo, gordura, gluten) VALUES (:dt, :ali, :qtd, :kc, :pr, :ca, :go, :gl)", params)
                    st.cache_resource.clear(); st.rerun()
    with st.expander("📥 Importação JSON Manual"):
        json_manual = st.text_area("JSON", height=150)
        if st.button("Salvar JSON Manual"):
            try:
                cleaned = json_manual.replace('```json', '').replace('```', '')
                start, end = cleaned.find('['), cleaned.rfind(']')
                lista = json.loads(cleaned[start:end+1] if start != -1 else cleaned)
                for i in (lista if isinstance(lista, list) else [lista]):
                    dt = i.get('data') or hoje
                    k_f = max((float(i.get('p',0))*4 + float(i.get('c',0))*4 + float(i.get('g',0))*9), float(i.get('kcal',0)))
                    executar_sql("INSERT INTO public.consumo (data, alimento, quantidade, kcal, proteina, carbo, gordura, gluten) VALUES (:dt, :ali, :qtd, :kcal, :p, :c, :g, :gl)", {'dt':dt, 'ali':i.get('alimento'), 'qtd':i.get('quantidade_g'), 'kcal':k_f, 'p':i.get('p'), 'c':i.get('c'), 'g':i.get('g'), 'gl':i.get('gluten')})
                st.success("Importado!"); st.cache_resource.clear(); st.rerun()
            except Exception as e: st.error(f"Erro: {e}")

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

# --- ABAS RESTANTES (Histórico, Saúde, Relatórios, Config) ---
with tab_hist:
    st.dataframe(executar_sql("SELECT * FROM public.consumo ORDER BY data DESC LIMIT 50", is_select=True))

with tab_saude:
    st.subheader("🫀 Pressão Arterial")
    with st.form("bp_f"):
        c1, c2, c3 = st.columns(3)
        s = c1.number_input("Sistólica", 90, 200, 120); d = c2.number_input("Diastólica", 50, 130, 80); p_in = c3.number_input("Pulso", 40, 200, 75)
        if st.form_submit_button("Salvar Pressão"):
            executar_sql("INSERT INTO public.blood_pressure (systolic, diastolic, pulse) VALUES (:s, :d, :p)", {'s':s, 'd':d, 'p':p_in}); st.rerun()
    st.divider(); st.subheader("📏 Avaliação Corporal")
    with st.form("med_f"):
        d_m = st.date_input("Data", value=hoje); p_m = st.number_input("Peso", 40.0, 200.0, value=PESO_ATUAL)
        wa = st.number_input("Cintura", 50.0, 200.0, value=p['last_waist'])
        bf = calc_bf_weltman_obese(wa, p_m, p['altura_cm'], p['genero'])
        st.info(f"🧬 BF Weltman: {bf:.1f}%")
        if st.form_submit_button("Salvar Avaliação"):
            executar_sql("INSERT INTO public.body_measurements (log_date, weight_kg, waist_cm, body_fat_est) VALUES (:dt, :w, :wa, :bf)", {'dt':d_m, 'w':p_m, 'wa':wa, 'bf':bf})
            executar_sql("UPDATE public.perfil SET ultima_cintura=:wa WHERE id=1", {'wa':wa}); st.cache_resource.clear(); st.rerun()

with tab_rel:
    dt_ini = st.date_input("Início", hoje-timedelta(30)); dt_fim = st.date_input("Fim", hoje)
    if st.button("📊 Download Excel"):
        st.download_button("📥 Baixar", gerar_excel_nutri(dt_ini, dt_fim), "Relatorio_Leo.xlsx")

with tab_admin:
    with st.form("metas_f"):
        mk = st.number_input("Kcal", value=p['meta_kcal']); mp = st.number_input("Prot", value=p['meta_proteina'])
        mc = st.number_input("Carb", value=p['meta_carbo']); mg = st.number_input("Gord", value=p['meta_gordura'])
        pa = st.number_input("Peso Alvo", value=p['meta_peso_alvo']); ri = st.number_input("Ritmo", value=p['ritmo_semanal'])
        if st.form_submit_button("💾 Salvar Metas"):
            executar_sql("UPDATE public.perfil SET meta_kcal=:mk, meta_proteina=:mp, meta_carbo=:mc, meta_gordura=:mg, meta_peso_alvo=:pa, ritmo_semanal=:ri WHERE id=1", {'mk':mk, 'mp':mp, 'mc':mc, 'mg':mg, 'pa':pa, 'ri':ri})
            st.cache_resource.clear(); st.rerun()

st.caption("Leo Tracker Pro v7.0 | Unified System")
