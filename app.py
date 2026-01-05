import streamlit as st
import pandas as pd
import psycopg2
from datetime import datetime, timedelta
import json
import pytz 
from groq import Groq 

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

# 3. INICIALIZAÇÃO E METAS DINÂMICAS
def inicializar_banco():
    # Garante que as tabelas de registro existam
    executar_sql("CREATE TABLE IF NOT EXISTS public.consumo (id SERIAL PRIMARY KEY, data DATE, alimento TEXT, quantidade REAL, kcal REAL, proteina REAL, carbo REAL, gordura REAL, gluten TEXT DEFAULT 'Não informado');")
    executar_sql("CREATE TABLE IF NOT EXISTS public.peso (id SERIAL PRIMARY KEY, data DATE, peso_kg REAL);")

def get_metas_usuario():
    """Busca as metas definidas no Dashboard (Tabela Perfil)"""
    try:
        df = executar_sql("SELECT meta_kcal, meta_proteina, meta_carbo, meta_gordura FROM public.perfil WHERE id = 1", is_select=True)
        if not df.empty:
            return {
                "kcal": int(df.iloc[0]['meta_kcal']),
                "prot": int(df.iloc[0]['meta_proteina']),
                "carb": int(df.iloc[0]['meta_carbo']), # Busca a meta de carbo
                "gord": int(df.iloc[0]['meta_gordura'])  # Busca a meta de gordura
            }
    except:
        pass
    # Fallback se não encontrar o perfil (valores de segurança)
    return {"kcal": 1650, "prot": 130, "carb": 150, "gord": 59}

inicializar_banco()
METAS = get_metas_usuario()

# 4. INTELIGÊNCIA ARTIFICIAL (GROQ)
def processar_texto_ia(texto_usuario, api_key):
    client = Groq(api_key=api_key)
    prompt_system = f"""Aja como nutricionista. Dieta Sem Glúten. Hoje é {get_now_br().strftime('%Y-%m-%d')}.
    Retorne um JSON com 'analise' (curta) e 'alimentos' (lista com: data, alimento, quantidade_g, kcal, p, c, g, gluten)."""
    try:
        completion = client.chat.completions.create(
            messages=[{"role": "system", "content": prompt_system}, {"role": "user", "content": texto_usuario}],
            model="llama-3.3-70b-versatile",
            temperature=0.1,
            response_format={"type": "json_object"}
        )
        return True, json.loads(completion.choices[0].message.content)
    except Exception as e:
        return False, f"Erro na IA: {e}"

# 5. INTERFACE DO APP
st.title("🦁 Leo Tracker Pro")

# --- DASHBOARD RÁPIDO ---
data_hoje = get_now_br().date()
df_hoje = executar_sql("SELECT * FROM public.consumo WHERE data = %s", (data_hoje,), is_select=True)

# Somas do dia
k_hoje = float(df_hoje['kcal'].sum()) if not df_hoje.empty else 0.0
p_hoje = float(df_hoje['proteina'].sum()) if not df_hoje.empty else 0.0
c_hoje = float(df_hoje['carbo'].sum()) if not df_hoje.empty else 0.0
g_hoje = float(df_hoje['gordura'].sum()) if not df_hoje.empty else 0.0

# Exibição dos KPIs conectados às metas do Dashboard
c1, c2, c3, c4 = st.columns(4)
c1.metric("🔥 Calorias", f"{int(k_hoje)} / {METAS['kcal']}")
c2.metric("🥩 Proteína", f"{int(p_hoje)}g / {METAS['prot']}g")
c3.metric("🍞 Carbo", f"{int(c_hoje)}g / {METAS['carb']}g")
c4.metric("🥑 Gordura", f"{int(g_hoje)}g / {METAS['gord']}g")

# Barra de progresso de Calorias
st.progress(min(k_hoje/METAS['kcal'], 1.0))

st.divider()

# --- ABAS DE AÇÃO ---
tab_add, tab_hist, tab_peso = st.tabs(["➕ Inserir Alimento", "📜 Diário de Hoje", "⚖️ Peso"])

with tab_add:
    st.write("### O que você comeu?")
    texto_input = st.text_area("", height=100, placeholder="Ex: 2 ovos mexidos, 1 tapioca com queijo e café preto.")
    
    if st.button("🚀 Processar com IA", type="primary"):
        api_key = st.secrets.get("GROQ_API_KEY")
        if texto_input and api_key:
            with st.spinner("Analisando calorias e macros..."):
                sucesso, res = processar_texto_ia(texto_input, api_key)
                if sucesso:
                    st.success(f"🤖 {res.get('analise')}")
                    for item in res.get('alimentos', []):
                        executar_sql(
                            "INSERT INTO public.consumo (data, alimento, quantidade, kcal, proteina, carbo, gordura, gluten) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                            (item.get('data'), item.get('alimento'), item.get('quantidade_g'), item.get('kcal'), item.get('p'), item.get('c'), item.get('g'), item.get('gluten'))
                        )
                    st.rerun()
                else:
                    st.error(res)
    
    with st.expander("Importação Avançada (JSON)"):
        json_manual = st.text_area("Cole o JSON aqui:")
        if st.button("Salvar JSON"):
            try:
                lista = json.loads(json_manual.replace('```json', '').replace('```', '').strip())
                for item in (lista if isinstance(lista, list) else [lista]):
                    executar_sql("INSERT INTO public.consumo (data, alimento, quantidade, kcal, proteina, carbo, gordura, gluten) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                                (item.get('data', data_hoje), item.get('alimento'), item.get('quantidade_g'), item.get('kcal'), item.get('p'), item.get('c'), item.get('g'), item.get('gluten')))
                st.rerun()
            except: st.error("JSON Inválido")

with tab_hist:
    st.write(f"### Refeições de Hoje ({data_hoje.strftime('%d/%m')})")
    if not df_hoje.empty:
        for i, row in df_hoje.iterrows():
            with st.container():
                cc1, cc2, cc3, cc4 = st.columns([3, 2, 1.5, 0.5])
                cc1.markdown(f"**{row['alimento']}**")
                cc2.caption(f"{int(row['kcal'])} kcal | P:{int(row['proteina'])} C:{int(row['carbo'])} G:{int(row['gordura'])}")
                cc3.caption(f"Glúten: {row['gluten']}")
                if cc4.button("❌", key=f"del_{row['id']}"):
                    executar_sql("DELETE FROM public.consumo WHERE id = %s", (row['id'],))
                    st.rerun()
                st.markdown("---")
    else:
        st.info("Nenhuma refeição registrada hoje.")

with tab_peso:
    st.write("### Registro de Peso")
    # Busca o último peso registrado para facilitar
    ultimo_peso = executar_sql("SELECT peso_kg FROM public.peso ORDER BY data DESC LIMIT 1", is_select=True)
    val_padrao = float(ultimo_peso.iloc[0]['peso_kg']) if not ultimo_peso.empty else 144.9
    
    p_val = st.number_input("Peso Atual (kg):", 40.0, 200.0, step=0.1, value=val_padrao, format="%.1f")
    
    if st.button("💾 Gravar Peso"):
        executar_sql("INSERT INTO public.peso (data, peso_kg) VALUES (%s, %s)", (data_hoje, p_val))
        st.success(f"Peso de {p_val}kg salvo com sucesso!")
        st.balloons()

st.caption(f"Leo Tracker Pro v2.0 | Conectado ao Dashboard")
