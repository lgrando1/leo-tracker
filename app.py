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

# 3. SINCRONIZAÇÃO DO BANCO (COMPLETO)
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
            weight_kg REAL, waist_cm REAL, neck_cm REAL, hip_cm REAL, body_fat_est REAL, notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    # Adiciona colunas se faltarem (migração)
    try: executar_sql("ALTER TABLE public.body_measurements ADD COLUMN IF NOT EXISTS body_fat_est REAL;")
    except: pass
    try: executar_sql("ALTER TABLE public.body_measurements ADD COLUMN IF NOT EXISTS weight_kg REAL;")
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

# 4. FUNÇÕES DE RELATÓRIO (COMPLETO)
def gerar_excel(df_cons, df_peso, df_medidas, df_bp, d_inicio, d_fim):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        if not df_cons.empty:
            df_resumo = df_cons.groupby(df_cons['data'].dt.date)[['kcal', 'proteina', 'carbo', 'gordura']].sum().reset_index()
            df_resumo.columns = ['Data', 'Total Kcal', 'Total Prot (g)', 'Total Carbo (g)', 'Total Gord (g)']
            df_resumo.to_excel(writer, sheet_name='Resumo Diário', index=False)
            df_detalhe = df_cons[['data', 'alimento', 'quantidade', 'kcal', 'proteina', 'carbo', 'gordura', 'gluten']].copy()
            df_detalhe['data'] = df_detalhe['data'].dt.strftime('%d/%m/%Y')
            df_detalhe.to_excel(writer, sheet_name='Diário Detalhado', index=False)
        if not df_peso.empty:
            df_p = df_peso[['data', 'peso_kg']].copy()
            df_p['data'] = df_p['data'].dt.strftime('%d/%m/%Y')
            df_p.to_excel(writer, sheet_name='Histórico Peso', index=False)
        if not df_medidas.empty:
            df_m = df_medidas[['log_date', 'waist_cm', 'neck_cm', 'hip_cm', 'body_fat_est']].copy()
            df_m.columns = ['Data', 'Cintura (cm)', 'Pescoço (cm)', 'Quadril (cm)', '% Gordura Est.']
            df_m['Data'] = df_m['Data'].dt.strftime('%d/%m/%Y')
            df_m.to_excel(writer, sheet_name='Medidas Corporais', index=False)
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
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(200, 10, txt="Relatório Nutricional - Leonardo Grando", ln=True, align='C')
    pdf.set_font("Arial", size=10)
    pdf.cell(200, 10, txt=f"Período: {d_inicio.strftime('%d/%m/%Y')} a {d_fim.strftime('%d/%m/%Y')}", ln=True, align='C')
    pdf.ln(10)
    
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(200, 10, txt="Metas Atuais:", ln=True)
    pdf.set_font("Arial", size=10)
    pdf.cell(0, 5, txt=f"Kcal: {METAS['kcal']} | Prot: {METAS['prot']}g | Carb: {METAS['carb']}g | Gord: {METAS['gord']}g", ln=True)
    pdf.ln(5)
    
    if not df_peso.empty:
        p_ini = df_peso.iloc[0]['peso_kg']
        p_fim = df_peso.iloc[-1]['peso_kg']
        delta = p_fim - p_ini
        pdf.set_font("Arial", 'B', 12)
        pdf.cell(0, 10, txt=f"Evolução de Peso ({len(df_peso)} registros)", ln=True)
        pdf.set_font("Arial", size=10)
        pdf.cell(0, 5, txt=f"Inicial: {p_ini}kg -> Atual: {p_fim}kg (Variação: {delta:.1f}kg)", ln=True)
        pdf.ln(5)

    if not df_medidas.empty:
        m_ini = df_medidas.iloc[0]['waist_cm']
        m_fim = df_medidas.iloc[-1]['waist_cm']
        fat_atual = df_medidas.iloc[-1]['body_fat_est']
        pdf.set_font("Arial", 'B', 12)
        pdf.cell(0, 10, txt="Evolução Corporal", ln=True)
        pdf.set_font("Arial", size=10)
        pdf.cell(0, 5, txt=f"Cintura Inicial: {m_ini}cm -> Atual: {m_fim}cm", ln=True)
        if fat_atual: pdf.cell(0, 5, txt=f"Estimativa de Gordura Atual: {fat_atual:.1f}%", ln=True)
        pdf.ln(5)

    if not df_cons.empty:
        media_kcal = df_cons.groupby(df_cons['data'].dt.date)['kcal'].sum().mean()
        media_prot = df_cons.groupby(df_cons['data'].dt.date)['proteina'].sum().mean()
        pdf.set_font("Arial", 'B', 12)
        pdf.cell(0, 10, txt="Média Diária no Período", ln=True)
        pdf.set_font("Arial", size=10)
        pdf.cell(0, 5, txt=f"Consumo Médio: {int(media_kcal)} kcal/dia", ln=True)
        pdf.cell(0, 5, txt=f"Proteína Média: {int(media_prot)} g/dia", ln=True)

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

# ABAS (Usando os nomes do seu código original)
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

# --- ABA DE SAÚDE OTIMIZADA (COM ST.FORM) ---
with tab_medidas:
    
    # 1. FORMULÁRIO DE PRESSÃO (Sem refresh ao digitar)
    st.subheader("🫀 Monitor Cardíaco (Pressão)")
    with st.form("form_pressao"):
        cp1, cp2, cp3 = st.columns(3)
        sys_in = cp1.number_input("Sistólica (Alta)", 90, 200, 127)
        dia_in = cp2.number_input("Diastólica (Baixa)", 50, 130, 76)
        pulse_in = cp3.number_input("Pulsação (BPM)", 40, 200, 75)
        
        # Botão dentro do form só envia quando clica
        if st.form_submit_button("❤️ Gravar Pressão"):
            executar_sql("INSERT INTO public.blood_pressure (systolic, diastolic, pulse, notes) VALUES (%s, %s, %s, 'Registro Manual')", (sys_in, dia_in, pulse_in))
            st.success("Registrado!")
            st.rerun()

    # Mostra histórico (fora do form)
    df_bp = executar_sql("SELECT measurement_time, systolic, diastolic, pulse FROM public.blood_pressure ORDER BY measurement_time DESC LIMIT 3", is_select=True)
    if not df_bp.empty:
        st.caption("Últimas leituras:")
        for idx, row in df_bp.iterrows():
            st.caption(f"📅 {row['measurement_time'].strftime('%d/%m %H:%M')} | **{row['systolic']}x{row['diastolic']}** mmHg | ❤️ {row['pulse']} bpm")
    
    st.divider()

    # 2. FORMULÁRIO DE MEDIDAS E PESO (Sem refresh ao digitar)
    st.subheader("📏 Medidas & Gordura")
    st.info("Preencha e clique em Salvar. A % de Gordura será calculada ao salvar.")
    
    with st.form("form_medidas"):
        c_dt, c_peso = st.columns([1, 1])
        dt_lanc = c_dt.date_input("Data:", value=data_hoje)
        
        # Busca último peso para facilitar
        ultimo = executar_sql("SELECT peso_kg FROM public.peso ORDER BY data DESC LIMIT 1", is_select=True)
        val_padrao = float(ultimo.iloc[0]['peso_kg']) if not ultimo.empty else 125.0
        p_val = c_peso.number_input("Peso (kg):", 40.0, 200.0, step=0.1, value=val_padrao)
        
        cm1, cm2, cm3 = st.columns(3)
        waist = cm1.number_input("Cintura (Umbigo):", 60.0, 150.0, step=0.5)
        neck = cm2.number_input("Pescoço:", 30.0, 60.0, step=0.5)
        hip = cm3.number_input("Quadril:", 80.0, 150.0, step=0.5)
        notes = st.text_input("Notas:", placeholder="Ex: Jejum...")
        
        if st.form_submit_button("💾 Salvar Peso e Medidas"):
            # Calcula gordura aqui, na hora do clique
            fat_est = calculate_body_fat(waist, neck, METAS['altura'])
            
            # Salva na tabela completa
            executar_sql("""
                INSERT INTO public.body_measurements 
                (log_date, weight_kg, waist_cm, neck_cm, hip_cm, body_fat_est, notes) 
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (dt_lanc, p_val, waist, neck, hip, fat_est, notes))
            
            # Salva também na tabela simples de peso (redundância útil)
            executar_sql("INSERT INTO public.peso (data, peso_kg) VALUES (%s, %s)", (dt_lanc, p_val))
            
            st.success(f"Salvo! Gordura Estimada: {fat_est:.1f}%")
            st.rerun()

    # Gráfico de Peso
    df_p = executar_sql("SELECT * FROM public.peso ORDER BY data ASC", is_select=True)
    if not df_p.empty:
        df_p['data'] = pd.to_datetime(df_p['data'])
        st.line_chart(df_p.set_index('data')['peso_kg'])

# ABA RELATÓRIOS
with tab_rel:
    st.header("📄 Relatórios para Nutricionista")
    col_d1, col_d2 = st.columns(2)
    d_inicio = col_d1.date_input("Data Início:", value=data_hoje - timedelta(days=30))
    d_fim = col_d2.date_input("Data Fim:", value=data_hoje)
    
    if st.button("🔍 Gerar Arquivos"):
        df_cons_rel = executar_sql("SELECT * FROM public.consumo WHERE data >= %s AND data <= %s ORDER BY data ASC", (d_inicio, d_fim), is_select=True)
        df_peso_rel = executar_sql("SELECT * FROM public.peso WHERE data >= %s AND data <= %s ORDER BY data ASC", (d_inicio, d_fim), is_select=True)
        df_medidas_rel = executar_sql("SELECT * FROM public.body_measurements WHERE log_date >= %s AND log_date <= %s ORDER BY log_date ASC", (d_inicio, d_fim), is_select=True)
        df_bp_rel = executar_sql("SELECT * FROM public.blood_pressure WHERE measurement_time >= %s AND measurement_time <= %s ORDER BY measurement_time ASC", (d_inicio, d_fim), is_select=True)
        
        if not df_cons_rel.empty:
            st.download_button("📥 Excel Completo (.xlsx)", gerar_excel(df_cons_rel, df_peso_rel, df_medidas_rel, df_bp_rel, d_inicio, d_fim), f"Relatorio_{d_inicio}.xlsx")
            try: st.download_button("📥 PDF Resumo (.pdf)", gerar_pdf(df_cons_rel, df_peso_rel, df_medidas_rel, d_inicio, d_fim), f"Resumo_{d_inicio}.pdf")
            except Exception as e: st.error(f"Erro PDF: {e}")
        else: st.warning("Sem dados no período.")

# ABA ADMIN (COM FORMULÁRIO PARA NÃO PISCAR)
with tab_admin:
    st.header("⚙️ Configuração")
    df_perfil = executar_sql("SELECT * FROM public.perfil WHERE id = 1", is_select=True)
    if not df_perfil.empty:
        p = df_perfil.iloc[0]
        # Helpers para pegar valor seguro
        def gv(k, d): return p[k] if k in p and pd.notnull(p[k]) else d
        c_gen, c_age, c_h, c_act = gv('genero','Masculino'), int(gv('idade',41)), int(gv('altura_cm',178)), gv('atividade','Sedentário (1.2)')
        c_mk, c_mp, c_mc, c_mg = int(gv('meta_kcal',1650)), int(gv('meta_proteina',130)), int(gv('meta_carbo',150)), int(gv('meta_gordura',59))
        c_pa, c_r = float(gv('meta_peso_alvo',120.0)), float(gv('ritmo_semanal',0.8))
    else:
        c_gen, c_age, c_h, c_act, c_mk, c_mp, c_mc, c_mg, c_pa, c_r = 'Masculino', 41, 178, 'Sedentário (1.2)', 1650, 130, 150, 59, 120.0, 0.8

    with st.form("form_config"):
        c1, c2, c3 = st.columns(3)
        genero = c1.selectbox("Gênero", ["Masculino", "Feminino"], index=0 if c_gen == 'Masculino' else 1)
        idade = c2.number_input("Idade", value=c_age)
        altura = c3.number_input("Altura (cm)", value=c_h)
        
        c4, c5 = st.columns(2)
        mapa = {"Sedentário (1.2)": 1.2, "Leve (1.375)": 1.375, "Moderado (1.55)": 1.55, "Intenso (1.725)": 1.725}
        idx = list(mapa.keys()).index(c_act) if c_act in mapa else 0
        atividade = c4.selectbox("Atividade", list(mapa.keys()), index=idx)
        
        st.divider()
        c_m1, c_m2, c_m3 = st.columns(3)
        n_kcal = c_m1.number_input("Meta Kcal", value=c_mk)
        n_prot = c_m2.number_input("Meta Prot", value=c_mp)
        n_peso = c_m3.number_input("Peso Alvo", value=c_pa)
        
        c_m4, c_m5, c_m6 = st.columns(3)
        n_carb = c_m4.number_input("Meta Carb", value=c_mc)
        n_gord = c_m5.number_input("Meta Gord", value=c_mg)
        n_ritmo = c_m6.slider("Ritmo kg/sem", 0.1, 2.0, c_r)

        if st.form_submit_button("💾 Salvar Configurações"):
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
            st.success("Perfil Salvo!")
            st.rerun()

st.caption("Leo Tracker Pro v4.0 | Full Features + No Refresh")
