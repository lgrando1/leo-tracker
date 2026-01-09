import streamlit as st
import pandas as pd
import psycopg2
from datetime import datetime, timedelta
import json
import pytz 
from groq import Groq 
import io
from fpdf import FPDF
import math

# 1. CONFIGURAÇÃO E ACESSO
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

# 2. CONEXÃO E BANCO DE DADOS
@st.cache_resource(ttl=600)
def get_connection():
    return psycopg2.connect(st.secrets["DATABASE_URL"])

def executar_sql(sql, params=None, is_select=False):
    conn = None
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute("SET timezone TO 'America/Sao_Paulo';")
            if is_select:
                df = pd.read_sql(sql, conn, params=params)
                # Padroniza conversão de datas
                for col in ['data', 'log_date', 'measurement_time']:
                    if col in df.columns:
                        try: df[col] = pd.to_datetime(df[col])
                        except: pass
                return df
            else:
                cur.execute(sql, params)
                conn.commit()
                return True
    except Exception as e:
        if conn: conn.rollback()
        st.error(f"Erro no Banco: {e}")
        return pd.DataFrame() if is_select else False

# 3. SINCRONIZAÇÃO DO BANCO
def inicializar_banco():
    # Tabelas Básicas
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
    # Medidas Corporais
    executar_sql("""
        CREATE TABLE IF NOT EXISTS public.body_measurements (
            id SERIAL PRIMARY KEY, log_date DATE NOT NULL,
            waist_cm REAL, neck_cm REAL, hip_cm REAL, body_fat_est REAL, notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    try: executar_sql("ALTER TABLE public.body_measurements ADD COLUMN IF NOT EXISTS body_fat_est REAL;")
    except: pass

    # Pressão Arterial
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
                "altura": int(row.get('altura_cm', 178))
            }
    except: pass
    return {"kcal": 1683, "prot": 108, "carb": 164, "gord": 67, "peso_alvo": 120.0, "ritmo": 0.8, "altura": 178}

inicializar_banco()
METAS = get_metas_do_banco()

# CÁLCULO GORDURA
def calculate_body_fat(waist, neck, height):
    if waist <= 0 or neck <= 0 or height <= 0: return 0.0
    try: return 495 / (1.0324 - 0.19077 * math.log10(waist - neck) + 0.15456 * math.log10(height)) - 450
    except: return 0.0

# 4. FUNÇÕES DE RELATÓRIO (RESTAURADAS E ATUALIZADAS)
def gerar_excel(df_cons, df_peso, df_medidas, df_bp, d_inicio, d_fim):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        # Aba 1: Resumo Diário
        if not df_cons.empty:
            df_resumo = df_cons.groupby(df_cons['data'].dt.date)[['kcal', 'proteina', 'carbo', 'gordura']].sum().reset_index()
            df_resumo.columns = ['Data', 'Total Kcal', 'Total Prot (g)', 'Total Carbo (g)', 'Total Gord (g)']
            df_resumo.to_excel(writer, sheet_name='Resumo Diário', index=False)
            
            # Aba 2: Detalhado
            df_detalhe = df_cons[['data', 'alimento', 'quantidade', 'kcal', 'proteina', 'carbo', 'gordura', 'gluten']].copy()
            df_detalhe['data'] = df_detalhe['data'].dt.strftime('%d/%m/%Y')
            df_detalhe.to_excel(writer, sheet_name='Diário Detalhado', index=False)
        
        # Aba 3: Peso
        if not df_peso.empty:
            df_p = df_peso[['data', 'peso_kg']].copy()
            df_p['data'] = df_p['data'].dt.strftime('%d/%m/%Y')
            df_p.to_excel(writer, sheet_name='Histórico Peso', index=False)

        # Aba 4: Medidas
        if not df_medidas.empty:
            df_m = df_medidas[['log_date', 'waist_cm', 'neck_cm', 'hip_cm', 'body_fat_est']].copy()
            df_m.columns = ['Data', 'Cintura (cm)', 'Pescoço (cm)', 'Quadril (cm)', '% Gordura Est.']
            df_m['Data'] = df_m['Data'].dt.strftime('%d/%m/%Y')
            df_m.to_excel(writer, sheet_name='Medidas Corporais', index=False)

        # Aba 5: Pressão (NOVO)
        if not df_bp.empty:
            df_b = df_bp[['measurement_time', 'systolic', 'diastolic', 'pulse']].copy()
            df_b.columns = ['Data/Hora', 'Sistólica', 'Diastólica', 'Pulso']
            df_b['Data/Hora'] = df_b['Data/Hora'].dt.strftime('%d/%m/%Y %H:%M')
            df_b.to_excel(writer, sheet_name='Pressão Arterial', index=False)
            
    return output.getvalue()

def gerar_pdf(df_cons, df_peso, df_medidas, d_inicio, d_fim):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    
    # Cabeçalho
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(200, 10, txt="Relatório Nutricional - Leonardo Grando", ln=True, align='C')
    pdf.set_font("Arial", size=10)
    pdf.cell(200, 10, txt=f"Período: {d_inicio.strftime('%d/%m/%Y')} a {d_fim.strftime('%d/%m/%Y')}", ln=True, align='C')
    pdf.ln(10)
    
    # Metas
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(200, 10, txt="Metas Atuais:", ln=True)
    pdf.set_font("Arial", size=10)
    pdf.cell(0, 5, txt=f"Kcal: {METAS['kcal']} | Prot: {METAS['prot']}g | Carb: {METAS['carb']}g | Gord: {METAS['gord']}g", ln=True)
    pdf.ln(5)
    
    # Resumo Peso
    if not df_peso.empty:
        p_ini = df_peso.iloc[0]['peso_kg']
        p_fim = df_peso.iloc[-1]['peso_kg']
        delta = p_fim - p_ini
        pdf.set_font("Arial", 'B', 12)
        pdf.cell(0, 10, txt=f"Evolução de Peso ({len(df_peso)} registros)", ln=True)
        pdf.set_font("Arial", size=10)
        pdf.cell(0, 5, txt=f"Inicial: {p_ini}kg -> Atual: {p_fim}kg (Variação: {delta:.1f}kg)", ln=True)
        pdf.ln(5)

    # Resumo Medidas
    if not df_medidas.empty:
        m_ini = df_medidas.iloc[0]['waist_cm']
        m_fim = df_medidas.iloc[-1]['waist_cm']
        fat_atual = df_medidas.iloc[-1]['body_fat_est']
        
        pdf.set_font("Arial", 'B', 12)
        pdf.cell(0, 10, txt="Evolução Corporal", ln=True)
        pdf.set_font("Arial", size=10)
        pdf.cell(0, 5, txt=f"Cintura Inicial: {m_ini}cm -> Atual: {m_fim}cm", ln=True)
        if fat_atual:
            pdf.cell(0, 5, txt=f"Estimativa de Gordura Atual: {fat_atual:.1f}%", ln=True)
        pdf.ln(5)

    # Resumo Médio Dieta
    if not df_cons.empty:
        media_kcal = df_cons.groupby(df_cons['data'].dt.date)['kcal'].sum().mean()
        media_prot = df_cons.groupby(df_cons['data'].dt.date)['proteina'].sum().mean()
        pdf.set_font("Arial", 'B', 12)
        pdf.cell(0, 10, txt="Média Diária no Período", ln=True)
        pdf.set_font("Arial", size=10)
        pdf.cell(0, 5, txt=f"Consumo Médio: {int(media_kcal)} kcal/dia", ln=True)
        pdf.cell(0, 5, txt=f"Proteína Média: {int(media_prot)} g/dia", ln=True)
        pdf.ln(10)

    return pdf.output(dest='S').encode('latin-1', 'ignore') 

# 5. GROQ IA
def processar_texto_ia(texto_usuario, api_key):
    client = Groq(api_key=api_key)
    prompt_system = f"""
    Aja como nutricionista. Dieta Sem Glúten. Hoje é {get_now_br().strftime('%Y-%m-%d')}.
    Gerar JSON estrito: {{ "analise": "...", "alimentos": [ {{ "data": "AAAA-MM-DD", "alimento": "Nome", "quantidade_g": 0, "kcal": 0, "p": 0, "c": 0, "g": 0, "gluten": "Contém/Não contém" }} ] }}
    """
    try:
        completion = client.chat.completions.create(
            messages=[{"role": "system", "content": prompt_system}, {"role": "user", "content": texto_usuario}],
            model="llama-3.3-70b-versatile", temperature=0.1, response_format={"type": "json_object"}
        )
        raw = completion.choices[0].message.content
        clean = raw.replace('```json', '').replace('```', '').strip()
        return True, json.loads(clean)
    except Exception as e: return False, f"Erro na IA: {e}"

# 6. INTERFACE DO APP
st.title("🦁 Leo Tracker Pro")

data_hoje = get_now_br().date()
df_hoje = executar_sql("SELECT * FROM public.consumo WHERE data = %s", (data_hoje,), is_select=True)

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

# ABAS COMPLETAS
tab_add, tab_hist, tab_medidas, tab_rel, tab_admin = st.tabs(["➕ Inserir", "📜 Diário", "❤️ Saúde & Corpo", "📄 Relatórios", "⚙️ Configurações"])

with tab_add:
    st.write("### O que você comeu?")
    texto_input = st.text_area("", height=100, placeholder="Ex: 2 ovos mexidos e café preto.")
    if st.button("🚀 Processar com IA", type="primary"):
        api_key = st.secrets.get("GROQ_API_KEY")
        if texto_input and api_key:
            with st.spinner("Analisando..."):
                sucesso, res = processar_texto_ia(texto_input, api_key)
                if sucesso:
                    st.success(f"🤖 {res.get('analise')}")
                    for item in res.get('alimentos', []):
                        executar_sql("INSERT INTO public.consumo (data, alimento, quantidade, kcal, proteina, carbo, gordura, gluten) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                                     (item.get('data'), item.get('alimento'), item.get('quantidade_g'), item.get('kcal'), item.get('p'), item.get('c'), item.get('g'), item.get('gluten')))
                    st.rerun()
                else: st.error(f"Erro IA: {res}")
    with st.expander("Importação JSON Manual"):
        json_manual = st.text_area("Cole JSON do Gemini:")
        if st.button("Salvar JSON"):
            try:
                cleaned = json_manual.replace('```json', '').replace('```', '')
                start, end = cleaned.find('['), cleaned.rfind(']')
                if start != -1 and end != -1: cleaned = cleaned[start:end+1]
                lista = json.loads(cleaned)
                count = 0
                for item in (lista if isinstance(lista, list) else [lista]):
                    dt = item.get('data') if item.get('data') else data_hoje
                    executar_sql("INSERT INTO public.consumo (data, alimento, quantidade, kcal, proteina, carbo, gordura, gluten) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                                 (dt, item.get('alimento'), item.get('quantidade_g'), item.get('kcal'), item.get('p'), item.get('c'), item.get('g'), item.get('gluten')))
                    count += 1
                st.success(f"{count} salvos!"); st.rerun()
            except Exception as e: st.error(f"Erro: {e}")

with tab_hist:
    st.write(f"### Hoje ({data_hoje.strftime('%d/%m')})")
    if not df_hoje.empty:
        for i, row in df_hoje.iterrows():
            with st.container():
                cc1, cc2, cc3, cc4 = st.columns([3, 2, 1.5, 0.5])
                cc1.markdown(f"**{row['alimento']}**")
                cc2.caption(f"{int(row['kcal'])} kcal | P:{int(row['proteina'])} C:{int(row['carbo'])} G:{int(row['gordura'])}")
                cc3.caption(f"Glúten: {row['gluten']}")
                if cc4.button("❌", key=f"del_{row['id']}"):
                    executar_sql("DELETE FROM public.consumo WHERE id = %s", (row['id'],)); st.rerun()
                st.markdown("---")
    else: st.info("Nada registrado hoje.")

with tab_medidas:
    # SEÇÃO 1: Cardio (Pressão)
    st.subheader("🫀 Monitor Cardíaco (Pressão)")
    cp1, cp2, cp3, cp4 = st.columns([1,1,1,1])
    sys_in = cp1.number_input("Sistólica (Alta)", 90, 200, 127)
    dia_in = cp2.number_input("Diastólica (Baixa)", 50, 130, 76)
    pulse_in = cp3.number_input("Pulsação (BPM)", 40, 200, 75)
    
    if cp4.button("❤️ Gravar PA"):
        executar_sql("INSERT INTO public.blood_pressure (systolic, diastolic, pulse, notes) VALUES (%s, %s, %s, 'Registro Manual')", (sys_in, dia_in, pulse_in))
        st.success("Pressão registrada!"); st.rerun()
    
    df_bp = executar_sql("SELECT measurement_time, systolic, diastolic, pulse FROM public.blood_pressure ORDER BY measurement_time DESC LIMIT 3", is_select=True)
    if not df_bp.empty:
        st.caption("Últimas leituras:")
        for idx, row in df_bp.iterrows():
            dt_fmt = row['measurement_time'].strftime('%d/%m %H:%M')
            st.caption(f"📅 {dt_fmt} | **{row['systolic']}x{row['diastolic']}** mmHg | ❤️ {row['pulse']} bpm")
    
    st.divider()

    # SEÇÃO 2: Corpo & Medidas
    st.subheader("📏 Medidas & Gordura")
    col_left, col_right = st.columns(2)
    
    with col_left:
        st.write(f"**Balança**")
        c_dt, c_val = st.columns([1, 1])
        dt_lanc = c_dt.date_input("Data:", value=data_hoje, key="dt_peso")
        
        ultimo = executar_sql("SELECT peso_kg FROM public.peso ORDER BY data DESC LIMIT 1", is_select=True)
        val_padrao = float(ultimo.iloc[0]['peso_kg']) if not ultimo.empty else 125.0
        p_val = c_val.number_input("Peso (kg):", 40.0, 200.0, step=0.1, value=val_padrao)
        
        if st.button("💾 Salvar Apenas Peso", use_container_width=True):
            executar_sql("INSERT INTO public.peso (data, peso_kg) VALUES (%s, %s)", (dt_lanc, p_val))
            st.success("Peso salvo!"); st.rerun()

    with col_right:
        st.write(f"**Fita Métrica**")
        cm1, cm2, cm3 = st.columns(3)
        waist = cm1.number_input("Cintura (Umbigo):", 60.0, 150.0, step=0.5, key="m_waist")
        neck = cm2.number_input("Pescoço:", 30.0, 60.0, step=0.5, key="m_neck")
        hip = cm3.number_input("Quadril:", 80.0, 150.0, step=0.5, key="m_hip")
        notes = st.text_input("Notas:", placeholder="Ex: Jejum...")
        
        fat_est = calculate_body_fat(waist, neck, METAS['altura'])
        if waist > 0: st.caption(f"Gordura (Navy): **{fat_est:.1f}%**")
        
        if st.button("💾 Salvar Medidas Completas", use_container_width=True):
            executar_sql("""
                INSERT INTO public.body_measurements 
                (log_date, weight_kg, waist_cm, neck_cm, hip_cm, body_fat_est, notes) 
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (dt_lanc, p_val, waist, neck, hip, fat_est, notes))
            executar_sql("INSERT INTO public.peso (data, peso_kg) VALUES (%s, %s)", (dt_lanc, p_val))
            st.success("Registro completo salvo!"); st.rerun()

# --- ABA DE RELATÓRIOS (RESTAURADA) ---
with tab_rel:
    st.header("📄 Relatórios para Nutricionista")
    st.write("Selecione o período e baixe os dados consolidados.")
    
    col_d1, col_d2 = st.columns(2)
    d_inicio = col_d1.date_input("Data Início:", value=data_hoje - timedelta(days=30))
    d_fim = col_d2.date_input("Data Fim:", value=data_hoje)
    
    if st.button("🔍 Gerar Arquivos"):
        df_cons_rel = executar_sql("SELECT * FROM public.consumo WHERE data >= %s AND data <= %s ORDER BY data ASC", (d_inicio, d_fim), is_select=True)
        df_peso_rel = executar_sql("SELECT * FROM public.peso WHERE data >= %s AND data <= %s ORDER BY data ASC", (d_inicio, d_fim), is_select=True)
        df_medidas_rel = executar_sql("SELECT * FROM public.body_measurements WHERE log_date >= %s AND log_date <= %s ORDER BY log_date ASC", (d_inicio, d_fim), is_select=True)
        df_bp_rel = executar_sql("SELECT * FROM public.blood_pressure WHERE measurement_time >= %s AND measurement_time <= %s ORDER BY measurement_time ASC", (d_inicio, d_fim), is_select=True)
        
        if not df_cons_rel.empty:
            # Excel
            excel_data = gerar_excel(df_cons_rel, df_peso_rel, df_medidas_rel, df_bp_rel, d_inicio, d_fim)
            st.download_button(
                label="📥 Baixar Excel Completo (.xlsx)",
                data=excel_data,
                file_name=f"Relatorio_Leo_Tracker_{d_inicio}_{d_fim}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
            # PDF
            try:
                pdf_data = gerar_pdf(df_cons_rel, df_peso_rel, df_medidas_rel, d_inicio, d_fim)
                st.download_button(
                    label="📥 Baixar Resumo PDF (.pdf)",
                    data=pdf_data,
                    file_name=f"Resumo_Leo_{d_inicio}_{d_fim}.pdf",
                    mime="application/pdf"
                )
            except Exception as e: st.error(f"Erro PDF: {e}")
        else:
            st.warning("Nenhum dado de consumo encontrado neste período.")

with tab_admin:
    st.header("⚙️ Configuração de Perfil & Metas")
    df_perfil = executar_sql("SELECT * FROM public.perfil WHERE id = 1", is_select=True)
    if not df_perfil.empty:
        p = df_perfil.iloc[0]
        def get_val(col, default): return p[col] if col in p and pd.notnull(p[col]) else default
        current_gen, current_age, current_h, current_act = get_val('genero', 'Masculino'), int(get_val('idade', 41)), int(get_val('altura_cm', 178)), get_val('atividade', 'Sedentário (1.2)')
        current_mkcal, current_mprot, current_mcarb, current_mgord = int(get_val('meta_kcal', 1650)), int(get_val('meta_proteina', 130)), int(get_val('meta_carbo', 150)), int(get_val('meta_gordura', 59))
        current_peso_alvo, current_ritmo = float(get_val('meta_peso_alvo', 120.0)), float(get_val('ritmo_semanal', 0.8))
    else:
        current_gen, current_age, current_h, current_act, current_mkcal, current_mprot, current_mcarb, current_mgord, current_peso_alvo, current_ritmo = 'Masculino', 41, 178, 'Sedentário (1.2)', 1650, 130, 150, 59, 120.0, 0.8

    with st.form("form_metas_inteligente"):
        c_bio1, c_bio2, c_bio3 = st.columns(3)
        genero = c_bio1.selectbox("Gênero", ["Masculino", "Feminino"], index=0 if current_gen == 'Masculino' else 1)
        idade = c_bio2.number_input("Idade", value=current_age)
        altura = c_bio3.number_input("Altura (cm)", value=current_h)
        
        c_atv1, c_atv2 = st.columns(2)
        mapa_ativ = {"Sedentário (1.2)": 1.2, "Leve (1.375)": 1.375, "Moderado (1.55)": 1.55, "Intenso (1.725)": 1.725}
        idx_ativ = list(mapa_ativ.keys()).index(current_act) if current_act in mapa_ativ else 0
        atividade = c_atv1.selectbox("Nível de Atividade", list(mapa_ativ.keys()), index=idx_ativ)
        peso_ref = st.number_input("Peso Ref (kg)", value=float(df_hoje['peso_kg'].iloc[-1]) if 'peso_kg' in df_hoje.columns and not df_hoje.empty else 141.0)
        
        st.divider()
        fator = mapa_ativ[atividade]
        tmb = (10 * peso_ref) + (6.25 * altura) - (5 * idade) + (5 if genero == "Masculino" else -161)
        get = tmb * fator
        st.info(f"🧮 **Basal Sugerido:** ~{int(get - 750)} kcal (para déficit).")

        c_meta1, c_meta2, c_meta3 = st.columns(3)
        n_kcal = c_meta1.number_input("Meta Kcal", value=current_mkcal)
        n_prot = c_meta2.number_input("Meta Proteína (g)", value=current_mprot)
        n_peso = c_meta3.number_input("Peso Alvo (kg)", value=current_peso_alvo)
        
        c_meta4, c_meta5, c_meta6 = st.columns(3)
        n_carb = c_meta4.number_input("Meta Carbo (g)", value=current_mcarb)
        n_gord = c_meta5.number_input("Meta Gordura (g)", value=current_mgord)
        n_ritmo = c_meta6.slider("Ritmo (kg/sem)", 0.1, 2.0, current_ritmo)

        if st.form_submit_button("💾 Salvar Perfil"):
            sql = """
                INSERT INTO public.perfil (id, genero, idade, altura_cm, atividade, objetivo, ritmo_semanal, meta_kcal, meta_proteina, meta_carbo, meta_gordura, meta_peso_alvo)
                VALUES (1, %s, %s, %s, %s, 'Custom', %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET 
                genero=EXCLUDED.genero, idade=EXCLUDED.idade, altura_cm=EXCLUDED.altura_cm, atividade=EXCLUDED.atividade, 
                ritmo_semanal=EXCLUDED.ritmo_semanal, meta_kcal=EXCLUDED.meta_kcal, 
                meta_proteina=EXCLUDED.meta_proteina, meta_carbo=EXCLUDED.meta_carbo, meta_gordura=EXCLUDED.meta_gordura, 
                meta_peso_alvo=EXCLUDED.meta_peso_alvo;
            """
            executar_sql(sql, (genero, idade, altura, atividade, n_ritmo, n_kcal, n_prot, n_carb, n_gord, n_peso))
            st.success("Perfil atualizado!"); st.rerun()

st.caption(f"Leo Tracker Pro v3.6 | All Features Active")
