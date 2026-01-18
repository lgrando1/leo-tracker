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
# 3. SINCRONIZAÇÃO E CÁLCULOS
# ============================================================================
def inicializar_banco():
    # Tabelas Core
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
    # Colunas novas (migração automática)
    for c in ['ultimo_pescoco', 'ultima_cintura', 'ultimo_quadril']:
        try: executar_sql(f"ALTER TABLE public.perfil ADD COLUMN IF NOT EXISTS {c} REAL;")
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

# Fórmulas
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
    Aja como Nutricionista. Hoje: {get_now_br().strftime('%Y-%m-%d')}.
    Regras: GORDURA OCULTA (fritura/grelhado = +5g gordura).
    Retorne APENAS um JSON válido.
    Formato: {{ "analise": "txt", "alimentos": [ {{ "data": "YYYY-MM-DD", "alimento": "txt", "quantidade_g": 0, "kcal": 0, "p": 0, "c": 0, "g": 0, "gluten": "Não contém" }} ] }}
    """
    try:
        completion = client.chat.completions.create(messages=[{"role": "system", "content": prompt_system}, {"role": "user", "content": texto_usuario}], model="llama-3.3-70b-versatile", response_format={"type": "json_object"})
        raw = completion.choices[0].message.content.replace("```json", "").replace("```", "").strip()
        start, end = raw.find('{'), raw.rfind('}')
        if start != -1 and end != -1: raw = raw[start:end+1]
        content = json.loads(raw)
        if isinstance(content, list): content = {"analise": "Processado", "alimentos": content}
        return True, content
    except Exception as e: return False, f"Erro: {str(e)}"

# ============================================================================
# 5. GERADOR EXCEL
# ============================================================================
def gerar_excel_nutri(dt_ini, dt_fim):
    output = io.BytesIO()
    params = {'d1': dt_ini, 'd2': dt_fim}
    df_detalhado = executar_sql("SELECT data, alimento, quantidade, kcal, proteina, carbo, gordura FROM public.consumo WHERE data >= :d1 AND data <= :d2 ORDER BY data DESC", params, is_select=True)
    df_peso = executar_sql("SELECT data, peso_kg FROM public.peso WHERE data >= :d1 AND data <= :d2 ORDER BY data ASC", params, is_select=True)
    df_medidas = executar_sql("SELECT log_date as data, weight_kg as peso, waist_cm as cintura, body_fat_est as bf_estimado, notes FROM public.body_measurements WHERE log_date >= :d1 AND log_date <= :d2 ORDER BY log_date DESC", params, is_select=True)
    df_pressao = executar_sql("SELECT measurement_time as data_hora, systolic, diastolic, pulse FROM public.blood_pressure WHERE measurement_time >= :d1 AND measurement_time <= :d2 ORDER BY measurement_time DESC", params, is_select=True)
    
    if not df_detalhado.empty: df_macros = df_detalhado.groupby('data')[['kcal', 'proteina', 'carbo', 'gordura']].sum().reset_index()
    else: df_macros = pd.DataFrame(columns=['data', 'kcal'])
    
    if not df_peso.empty: df_peso = df_peso.drop_duplicates(subset='data', keep='last')
    
    df_resumo = pd.merge(df_macros, df_peso, on='data', how='outer').sort_values('data', ascending=False)
    if not df_resumo.empty: df_resumo['data'] = pd.to_datetime(df_resumo['data']).dt.strftime('%d/%m/%Y')

    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df_resumo.to_excel(writer, sheet_name='1. Resumo', index=False)
        df_detalhado.to_excel(writer, sheet_name='2. Detalhado', index=False)
        df_medidas.to_excel(writer, sheet_name='3. Medidas', index=False)
        df_pressao.to_excel(writer, sheet_name='4. Pressão', index=False)
    return output.getvalue()

# ============================================================================
# 6. INTERFACE UNIFICADA
# ============================================================================
st.title("🦁 Leo Tracker Pro")
data_hoje = get_now_br().date()
df_hoje = executar_sql("SELECT * FROM public.consumo WHERE data = :d", {'d': data_hoje}, is_select=True)

# SIDEBAR SIMPLIFICADA
ultimo_peso_df = executar_sql("SELECT peso_kg FROM public.peso ORDER BY data DESC LIMIT 1", is_select=True)
peso_atual = float(ultimo_peso_df.iloc[0]['peso_kg']) if not ultimo_peso_df.empty else 140.0
st.sidebar.metric("Peso Atual", f"{peso_atual} kg", f"Meta: {METAS['peso_alvo']} kg")
st.sidebar.progress(min(max(0.0, (150 - peso_atual) / (150 - METAS['peso_alvo'])), 1.0))
st.sidebar.divider()
st.sidebar.caption(f"v7.0 Unified | {data_hoje.strftime('%d/%m/%Y')}")

# ABAS DO SISTEMA
tab_dash, tab_daily, tab_hist, tab_medidas, tab_rel, tab_admin = st.tabs([
    "📊 Visão Geral", "📝 Diário", "📜 Histórico", "❤️ Saúde", "📄 Relatórios", "⚙️ Configurações"
])

# --- 1. DASHBOARD (NOVO) ---
with tab_dash:
    # Métricas do Dia
    k_h = df_hoje['kcal'].sum() if not df_hoje.empty else 0
    p_h = df_hoje['proteina'].sum() if not df_hoje.empty else 0
    c_h = df_hoje['carbo'].sum() if not df_hoje.empty else 0
    g_h = df_hoje['gordura'].sum() if not df_hoje.empty else 0
    meta_agua = round((peso_atual * 35) / 1000, 1)

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("🔥 Calorias", f"{int(k_h)}", f"Meta: {METAS['kcal']}")
    c2.metric("🥩 Proteína", f"{int(p_h)}g", f"Meta: {METAS['prot']}g")
    c3.metric("🍞 Carbo", f"{int(c_h)}g", f"Meta: {METAS['carb']}g")
    c4.metric("🥑 Gordura", f"{int(g_h)}g", f"Meta: {METAS['gord']}g")
    c5.metric("💧 Água Min.", f"{meta_agua}L", "Hidratação")
    st.divider()

    # Projeção vs Realidade
    st.subheader("🎯 Projeção vs. Realidade")
    df_peso_all = executar_sql("SELECT * FROM public.peso ORDER BY data ASC", is_select=True)
    if not df_peso_all.empty:
        df_peso_all['data'] = pd.to_datetime(df_peso_all['data'])
        BASE_DATE = pd.to_datetime("2025-12-31")
        
        # Filtra dados a partir da base
        df_base = df_peso_all[df_peso_all['data'] >= BASE_DATE].copy()
        
        if not df_base.empty:
            peso_inicial = float(df_base.iloc[0]['peso_kg'])
            ritmo_diario = METAS['ritmo'] / 7
            
            # Cria projeção até hoje
            hoje_dt = pd.to_datetime(data_hoje)
            dias_totais = (hoje_dt - BASE_DATE).days
            datas_proj = [BASE_DATE + timedelta(days=x) for x in range(dias_totais + 1)]
            pesos_estimados = [peso_inicial - (x * ritmo_diario) for x in range(len(datas_proj))]
            
            # Status
            peso_esperado_hoje = peso_inicial - (dias_totais * ritmo_diario)
            diferenca = peso_atual - peso_esperado_hoje
            dias_diff = diferenca / ritmo_diario
            
            col_g1, col_g2 = st.columns([3, 1])
            with col_g1:
                fig_proj = go.Figure()
                fig_proj.add_trace(go.Scatter(x=datas_proj, y=pesos_estimados, mode='lines', name='Meta (Previsto)', line=dict(color='#29B5E8', dash='dash')))
                fig_proj.add_trace(go.Scatter(x=df_base['data'], y=df_base['peso_kg'], mode='lines+markers', name='Realizado', line=dict(color='#FF4B4B', width=3)))
                fig_proj.update_layout(height=300, margin=dict(l=10,r=10,t=10,b=10), legend=dict(orientation="h", y=1.1))
                st.plotly_chart(fig_proj, use_container_width=True)
            
            with col_g2:
                status_cor = "normal" if dias_diff <= 0 else "inverse"
                label_status = "Adiantado" if dias_diff <= 0 else "Atrasado"
                st.metric("Status Cronograma", f"{abs(dias_diff):.1f} dias", label_status, delta_color=status_cor)
                st.metric("Distância Meta Final", f"{(peso_atual - METAS['peso_alvo']):.1f} kg")

            # Banco de Gordura
            st.subheader("🏦 Banco de Gordura (Teórico)")
            DATA_INICIO_BANCO = pd.to_datetime("2025-12-30")
            df_hist = executar_sql("SELECT data, SUM(kcal) as tkcal FROM public.consumo WHERE data >= :d GROUP BY data", {'d': DATA_INICIO_BANCO}, is_select=True)
            
            if not df_hist.empty and not df_base.empty:
                df_hist['data'] = pd.to_datetime(df_hist['data'])
                df_merged = pd.merge(df_hist, df_base[['data', 'peso_kg']], on='data', how='left').ffill()
                
                # GET Estimado
                df_merged['get_dia'] = ((10 * df_merged['peso_kg']) + (6.25 * METAS['altura']) - (5 * METAS['idade']) + 5) * 1.09 * 1.2
                deficit_total = (df_merged['get_dia'] - df_merged['tkcal']).sum()
                kg_gordura = deficit_total / 7700
                st.info(f"Desde 30/12/2025: **{int(deficit_total)} kcal** de déficit acumulado ≈ **{kg_gordura:.2f} kg** de gordura eliminada.")

# --- 2. DIÁRIO (MANUTENÇÃO DE REGISTRO) ---
with tab_daily:
    st.markdown("##### ⚖️ Registro Rápido")
    with st.form("form_peso_diario"):
        c1, c2, c3 = st.columns([1, 1, 2])
        d_p = c1.date_input("Data", data_hoje, label_visibility="collapsed")
        p_v = c2.number_input("Peso", 40.0, 200.0, step=0.1, value=peso_atual, label_visibility="collapsed")
        if c3.form_submit_button("💾 Salvar Peso", use_container_width=True):
            executar_sql("INSERT INTO public.peso (data, peso_kg) VALUES (:d, :p)", {'d': d_p, 'p': p_v})
            st.cache_resource.clear(); st.rerun()

    st.divider()
    st.write("### 🍎 Alimentação")
    txt_ia = st.text_area("Descreva sua refeição...", height=80)
    if st.button("🚀 Processar com IA"):
        key = st.secrets.get("GROQ_API_KEY")
        if txt_ia and key:
            ok, res = processar_texto_ia(txt_ia, key)
            if ok:
                for i in res.get('alimentos', []):
                    k_f = max((i.get('p',0)*4 + i.get('c',0)*4 + i.get('g',0)*9), float(i.get('kcal',0)))
                    p_sql = {'dt': i.get('data') or data_hoje, 'a': i.get('alimento'), 'q': i.get('quantidade_g'), 'k': k_f, 'p': i.get('p'), 'c': i.get('c'), 'g': i.get('g'), 'gl': i.get('gluten')}
                    executar_sql("INSERT INTO public.consumo (data, alimento, quantidade, kcal, proteina, carbo, gordura, gluten) VALUES (:dt, :a, :q, :k, :p, :c, :g, :gl)", p_sql)
                st.success("Registrado!"); st.cache_resource.clear(); st.rerun()
            else: st.error(f"Erro IA: {res}")

    with st.expander("📥 Importação JSON Manual"):
        js_in = st.text_area("Cole o JSON aqui", height=100)
        if st.button("Salvar JSON"):
            try:
                l = json.loads(js_in.replace("```json","").replace("```",""))
                for i in (l if isinstance(l, list) else [l]):
                    k_f = max((float(i.get('p',0))*4 + float(i.get('c',0))*4 + float(i.get('g',0))*9), float(i.get('kcal',0)))
                    p_sql = {'dt': i.get('data') or data_hoje, 'a': i.get('alimento'), 'q': i.get('quantidade_g'), 'k': k_f, 'p': i.get('p'), 'c': i.get('c'), 'g': i.get('g'), 'gl': i.get('gluten')}
                    executar_sql("INSERT INTO public.consumo (data, alimento, quantidade, kcal, proteina, carbo, gordura, gluten) VALUES (:dt, :a, :q, :k, :p, :c, :g, :gl)", p_sql)
                st.cache_resource.clear(); st.rerun()
            except Exception as e: st.error(f"Erro JSON: {e}")

    if not df_hoje.empty:
        st.markdown("---")
        for i, row in df_hoje.iterrows():
            c1, c2, c3 = st.columns([3, 2, 0.5])
            c1.markdown(f"**{row['alimento']}**")
            c2.caption(f"{int(row['kcal'])} kcal | P:{int(row['proteina'])} G:{int(row['gordura'])}")
            if c3.button("❌", key=f"del_{row['id']}"):
                executar_sql("DELETE FROM public.consumo WHERE id=:id", {'id': row['id']})
                st.cache_resource.clear(); st.rerun()

# --- 3. HISTÓRICO ---
with tab_hist:
    st.dataframe(executar_sql("SELECT * FROM public.consumo ORDER BY data DESC LIMIT 50", is_select=True))

# --- 4. SAÚDE (MEDIDAS) ---
with tab_medidas:
    st.subheader("🫀 Pressão Arterial")
    with st.form("bp_form"):
        c1, c2, c3 = st.columns(3)
        sys = c1.number_input("Sistólica", 90, 200, 120); dia = c2.number_input("Diastólica", 50, 130, 80); pul = c3.number_input("Pulso", 40, 200, 75)
        if st.form_submit_button("Salvar Pressão"):
            executar_sql("INSERT INTO public.blood_pressure (systolic, diastolic, pulse, notes) VALUES (:s, :d, :p, 'App')", {'s': sys, 'd': dia, 'p': pul})
            st.success("Salvo!"); st.rerun()

    st.divider(); st.subheader("📏 Avaliação Corporal")
    with st.form("medidas_form"):
        d_m = st.date_input("Data", data_hoje)
        w_m = st.number_input("Peso (kg)", value=peso_atual)
        wa_m = st.number_input("Cintura (cm)", value=METAS['last_waist'])
        bf_w = calc_bf_weltman_obese(wa_m, w_m, METAS['altura'], METAS['genero'])
        st.info(f"🧬 BF Weltman Estimado: **{bf_w:.1f}%**")
        if st.form_submit_button("Salvar Medidas"):
            p_sql = {'dt': d_m, 'w': w_m, 'wa': wa_m, 'ne': METAS['last_neck'], 'hi': METAS['last_hip'], 'bf': bf_w}
            executar_sql("INSERT INTO public.body_measurements (log_date, weight_kg, waist_cm, neck_cm, hip_cm, body_fat_est, body_fat_weltman) VALUES (:dt, :w, :wa, :ne, :hi, :bf, :bf)", p_sql)
            executar_sql("INSERT INTO public.peso (data, peso_kg) VALUES (:dt, :w)", {'dt': d_m, 'w': w_m})
            executar_sql("UPDATE public.perfil SET ultima_cintura=:wa WHERE id=1", {'wa': wa_m})
            st.cache_resource.clear(); st.rerun()

# --- 5. RELATÓRIOS ---
with tab_rel:
    d1, d2 = st.columns(2)
    dt_i = d1.date_input("Início", data_hoje - timedelta(days=30))
    dt_f = d2.date_input("Fim", data_hoje)
    if st.button("📥 Baixar Excel Completo"):
        st.download_button("Download .xlsx", gerar_excel_nutri(dt_i, dt_f), "Leo_Tracker_Full.xlsx")

# --- 6. CONFIGURAÇÕES ---
with tab_admin:
    with st.form("cfg_metas"):
        st.subheader("Configuração de Metas")
        c1, c2 = st.columns(2)
        nk = c1.number_input("Meta Kcal", value=METAS['kcal']); np = c2.number_input("Meta Prot", value=METAS['prot'])
        nc = c1.number_input("Meta Carb", value=METAS['carb']); ng = c2.number_input("Meta Gord", value=METAS['gord'])
        npa = c1.number_input("Peso Alvo", value=METAS['peso_alvo']); nr = c2.number_input("Ritmo (kg/sem)", value=METAS['ritmo'])
        if st.form_submit_button("Salvar Configurações"):
            p_sql = {'mk': nk, 'mp': np, 'mc': nc, 'mg': ng, 'mpa': npa, 'rit': nr}
            executar_sql("UPDATE public.perfil SET meta_kcal=:mk, meta_proteina=:mp, meta_carbo=:mc, meta_gordura=:mg, meta_peso_alvo=:mpa, ritmo_semanal=:rit WHERE id=1", p_sql)
            st.cache_resource.clear(); st.rerun()
