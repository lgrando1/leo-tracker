import streamlit as st
import pandas as pd
import psycopg2
from datetime import datetime, timedelta
import json
import pytz 
from groq import Groq 
import io
from fpdf import FPDF

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
                if 'data' in df.columns: df['data'] = pd.to_datetime(df['data'])
                return df
            else:
                cur.execute(sql, params)
                conn.commit()
                return True
    except Exception as e:
        if conn: conn.rollback()
        st.error(f"Erro no Banco: {e}")
        return pd.DataFrame() if is_select else False

# 3. SINCRONIZAÇÃO COM O DASHBOARD
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

def get_metas_do_banco():
    try:
        df = executar_sql("SELECT * FROM public.perfil WHERE id = 1", is_select=True)
        if not df.empty:
            row = df.iloc[0]
            return {
                "kcal": int(row['meta_kcal']),
                "prot": int(row['meta_proteina']),
                "carb": int(row.get('meta_carbo', 164)),
                "gord": int(row.get('meta_gordura', 67)),
                "peso_alvo": float(row.get('meta_peso_alvo', 120.0)),
                "ritmo": float(row.get('ritmo_semanal', 0.8))
            }
    except: pass
    return {"kcal": 1683, "prot": 108, "carb": 164, "gord": 67, "peso_alvo": 120.0, "ritmo": 0.8}

inicializar_banco()
METAS = get_metas_do_banco()

# 4. FUNÇÕES DE RELATÓRIO (NOVO)
def gerar_excel(df_cons, df_peso, d_inicio, d_fim):
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
            
    return output.getvalue()

def gerar_pdf(df_cons, df_peso, d_inicio, d_fim):
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

    # Resumo Médio
    if not df_cons.empty:
        media_kcal = df_cons.groupby(df_cons['data'].dt.date)['kcal'].sum().mean()
        media_prot = df_cons.groupby(df_cons['data'].dt.date)['proteina'].sum().mean()
        pdf.set_font("Arial", 'B', 12)
        pdf.cell(0, 10, txt="Média Diária no Período", ln=True)
        pdf.set_font("Arial", size=10)
        pdf.cell(0, 5, txt=f"Consumo Médio: {int(media_kcal)} kcal/dia", ln=True)
        pdf.cell(0, 5, txt=f"Proteína Média: {int(media_prot)} g/dia", ln=True)
        pdf.ln(10)
        
        # Logs (Simplificado para não quebrar página)
        pdf.set_font("Arial", 'B', 12)
        pdf.cell(0, 10, txt="Diário Resumido (Últimos dias)", ln=True)
        pdf.set_font("Arial", size=8)
        
        dias = df_cons['data'].dt.date.unique()
        for dia in sorted(dias, reverse=True)[:10]: # Top 10 dias recentes
            soma = df_cons[df_cons['data'].dt.date == dia]['kcal'].sum()
            # Tratamento básico de caracteres latinos
            data_str = dia.strftime('%d/%m')
            pdf.cell(0, 5, txt=f"{data_str}: {int(soma)} kcal", ln=True)

    return pdf.output(dest='S').encode('latin-1', 'ignore') # Encode para bytes

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

# ABAS
tab_add, tab_hist, tab_peso, tab_rel, tab_admin = st.tabs(["➕ Inserir", "📜 Diário", "⚖️ Peso", "📄 Relatórios", "⚙️ Metas"])

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

with tab_peso:
    st.write(f"### Rumo aos {METAS['peso_alvo']}kg")
    c_dt, c_val, c_btn = st.columns([1.5, 1.5, 1])
    dt_lanc = c_dt.date_input("Data:", value=data_hoje)
    ultimo = executar_sql("SELECT peso_kg FROM public.peso ORDER BY data DESC LIMIT 1", is_select=True)
    val_padrao = float(ultimo.iloc[0]['peso_kg']) if not ultimo.empty else 125.0
    p_val = c_val.number_input("Peso (kg):", 40.0, 200.0, step=0.1, value=val_padrao)
    c_btn.write(""); c_btn.write("")
    if c_btn.button("💾 Salvar"):
        executar_sql("INSERT INTO public.peso (data, peso_kg) VALUES (%s, %s)", (dt_lanc, p_val))
        st.success("Salvo!"); st.rerun()
    st.divider()
    df_p = executar_sql("SELECT * FROM public.peso ORDER BY data ASC", is_select=True)
    if not df_p.empty:
        df_p['data'] = pd.to_datetime(df_p['data'])
        st.line_chart(df_p.set_index('data')['peso_kg'])

# --- NOVA ABA DE RELATÓRIOS ---
with tab_rel:
    st.header("📄 Relatórios para Nutricionista")
    st.write("Selecione o período e baixe os dados para compartilhar.")
    
    col_d1, col_d2 = st.columns(2)
    d_inicio = col_d1.date_input("Data Início:", value=data_hoje - timedelta(days=30))
    d_fim = col_d2.date_input("Data Fim:", value=data_hoje)
    
    if st.button("🔍 Gerar Arquivos"):
        df_cons_rel = executar_sql("SELECT * FROM public.consumo WHERE data >= %s AND data <= %s ORDER BY data ASC", (d_inicio, d_fim), is_select=True)
        df_peso_rel = executar_sql("SELECT * FROM public.peso WHERE data >= %s AND data <= %s ORDER BY data ASC", (d_inicio, d_fim), is_select=True)
        
        if not df_cons_rel.empty:
            # Excel
            excel_data = gerar_excel(df_cons_rel, df_peso_rel, d_inicio, d_fim)
            st.download_button(
                label="📥 Baixar Excel Completo (.xlsx)",
                data=excel_data,
                file_name=f"Relatorio_Leo_Tracker_{d_inicio}_{d_fim}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
            
            # PDF
            try:
                pdf_data = gerar_pdf(df_cons_rel, df_peso_rel, d_inicio, d_fim)
                st.download_button(
                    label="📥 Baixar Resumo PDF (.pdf)",
                    data=pdf_data,
                    file_name=f"Resumo_Leo_{d_inicio}_{d_fim}.pdf",
                    mime="application/pdf"
                )
            except Exception as e:
                st.error(f"Erro ao gerar PDF (pode ser problema de fonte no servidor): {e}")
                
        else:
            st.warning("Nenhum dado de consumo encontrado neste período.")

with tab_admin:
    st.header("⚙️ Sincronia de Metas")
    with st.form("form_sync"):
        c1, c2 = st.columns(2)
        nk = c1.number_input("Meta Kcal:", value=METAS['kcal'], step=50)
        np = c2.number_input("Meta Proteína:", value=METAS['prot'], step=5)
        c3, c4 = st.columns(2)
        nc = c3.number_input("Meta Carbo:", value=METAS['carb'], step=5)
        ng = c4.number_input("Meta Gordura:", value=METAS['gord'], step=5)
        if st.form_submit_button("💾 Atualizar Banco"):
            executar_sql("UPDATE public.perfil SET meta_kcal=%s, meta_proteina=%s, meta_carbo=%s, meta_gordura=%s WHERE id=1", (nk, np, nc, ng))
            st.success("Sincronizado!"); st.rerun()

st.caption(f"Leo Tracker Pro v3.3 | Reports Active")
