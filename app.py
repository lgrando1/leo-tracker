import streamlit as st
import pandas as pd
import psycopg2
from datetime import datetime, timedelta
import json
import pytz 
from groq import Groq 

# 1. CONFIGURAÇÃO E TEMPO
st.set_page_config(page_title="Leo Tracker Pro", page_icon="🦁", layout="wide")

def get_now_br():
    return datetime.now(pytz.timezone('America/Sao_Paulo'))

# 2. CONEXÃO E BANCO
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
        st.error(f"Erro: {e}")
        return pd.DataFrame() if is_select else False

# 3. METAS
META_KCAL = 1650 
META_PROTEINA = 110 

# 4. FUNÇÃO IA (GROQ)
def processar_texto_ia(texto_usuario, api_key):
    client = Groq(api_key=api_key)
    prompt_system = f"""Aja como nutricionista. Dieta Sem Glúten. 
    Hoje é {get_now_br().strftime('%Y-%m-%d')}.
    Retorne um JSON com 'analise' (breve) e 'alimentos' (lista com data, alimento, quantidade_g, kcal, p, c, g, gluten)."""
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

# 5. INTERFACE PRINCIPAL
st.title("🦁 Leo Tracker Pro")

# --- DASHBOARD DE HOJE ---
data_hoje = get_now_br().date()
df_hoje = executar_sql("SELECT * FROM public.consumo WHERE data = %s", (data_hoje,), is_select=True)

kcal_hoje = float(df_hoje['kcal'].sum()) if not df_hoje.empty else 0.0
prot_hoje = float(df_hoje['proteina'].sum()) if not df_hoje.empty else 0.0
carbo_hoje = float(df_hoje['carbo'].sum()) if not df_hoje.empty else 0.0

c1, c2, c3 = st.columns(3)
c1.metric("🔥 Calorias", f"{int(kcal_hoje)} / {META_KCAL}")
c2.metric("🥩 Proteína", f"{int(prot_hoje)}g / {META_PROTEINA}g")
c3.metric("🍞 Carboidratos", f"{int(carbo_hoje)}g")
st.progress(min(kcal_hoje/META_KCAL, 1.0))

st.divider()

# --- ABAS SIMPLIFICADAS ---
tab_add, tab_hist, tab_peso = st.tabs(["➕ Inserir Alimento", "📜 Diário de Hoje", "⚖️ Peso"])

with tab_add:
    st.write("#### 💬 O que você comeu?")
    texto_input = st.text_area("Ex: Almoço 150g frango, vagem e suco de limão com açúcar", height=70)
    
    col1, col2 = st.columns(2)
    if col1.button("🚀 Processar IA"):
        api_key = st.secrets.get("GROQ_API_KEY")
        if texto_input and api_key:
            with st.spinner("Analisando..."):
                sucesso, res = processar_texto_ia(texto_input, api_key)
                if sucesso:
                    st.info(f"👩‍⚕️ {res.get('analise')}")
                    for item in res.get('alimentos', []):
                        executar_sql(
                            "INSERT INTO public.consumo (data, alimento, quantidade, kcal, proteina, carbo, gordura, gluten) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                            (item.get('data'), item.get('alimento'), item.get('quantidade_g'), item.get('kcal'), item.get('p'), item.get('c'), item.get('g'), item.get('gluten'))
                        )
                    st.success("Salvo!")
                    st.rerun()
    
    if col2.button("🤖 Usar JSON Gemini"):
        st.info("Cole o JSON abaixo:")
        json_manual = st.text_area("JSON:")
        if st.button("Salvar JSON"):
            try:
                lista = json.loads(json_manual)
                for item in (lista if isinstance(lista, list) else [lista]):
                    executar_sql("INSERT INTO public.consumo (data, alimento, quantidade, kcal, proteina, carbo, gordura, gluten) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                                (item.get('data', data_hoje), item.get('alimento'), item.get('quantidade_g'), item.get('kcal'), item.get('p'), item.get('c'), item.get('g'), item.get('gluten')))
                st.rerun()
            except: st.error("JSON Inválido")

with tab_hist:
    st.write(f"#### Detalhes de {data_hoje.strftime('%d/%m')}")
    if not df_hoje.empty:
        for i, row in df_hoje.iterrows():
            cc1, cc2, cc3 = st.columns([3, 1.5, 1])
            cc1.write(f"🍴 {row['alimento']}")
            cc2.write(f"{int(row['kcal'])} kcal | {int(row['proteina'])}g P")
            if cc3.button("🗑️", key=f"del_h_{row['id']}"):
                executar_sql("DELETE FROM public.consumo WHERE id = %s", (row['id'],))
                st.rerun()
    else:
        st.write("Nenhum registro hoje.")

with tab_peso:
    st.subheader("⚖️ Registro de Peso")
    p_val = st.number_input("Peso Atual (kg):", 40.0, 200.0, step=0.1)
    if st.button("Gravar Peso"):
        executar_sql("INSERT INTO public.peso (data, peso_kg) VALUES (%s, %s)", (data_hoje, p_val))
        st.success("Peso gravado!")
        st.rerun()

st.divider()
st.caption("Leo Tracker Pro v2.0 | Foco em Perda de Peso e Detox de Glúten")
