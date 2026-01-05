import streamlit as st
import pandas as pd
import psycopg2
from datetime import datetime, timedelta
import pytz
import plotly.graph_objects as go

# 1. CONFIGURAÇÃO E CONEXÃO
st.set_page_config(page_title="Leo's Nutrition Dash", page_icon="🦁", layout="wide")

@st.cache_resource(ttl=300)
def get_connection():
    return psycopg2.connect(st.secrets["DATABASE_URL"])

def run_query(query, params=None, is_select=True):
    conn = None
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute("SET timezone TO 'America/Sao_Paulo';")
            if is_select:
                return pd.read_sql(query, conn, params=params)
            else:
                cur.execute(query, params)
                conn.commit()
                return True
    except Exception as e:
        if conn: conn.rollback() # Limpa transações abortadas
        st.error(f"Erro DB: {e}")
        return pd.DataFrame() if is_select else False

# --- ACESSO ---
if st.query_params.get("token") != st.secrets.get("DASH_ACCESS_TOKEN"):
    st.stop()

# --- INICIALIZAÇÃO E CARREGAMENTO ---
run_query("""
    CREATE TABLE IF NOT EXISTS public.perfil (
        id INTEGER PRIMARY KEY, genero TEXT, idade INTEGER, altura_cm INTEGER, 
        atividade TEXT, ritmo_semanal REAL, meta_kcal INTEGER, 
        meta_proteina INTEGER, meta_carbo INTEGER, meta_gordura INTEGER, meta_peso_alvo REAL
    );
""", is_select=False)

df_perfil = run_query("SELECT * FROM public.perfil WHERE id = 1")
df_peso_last = run_query("SELECT peso_kg FROM public.peso ORDER BY data DESC LIMIT 1")

p = df_perfil.iloc[0] if not df_perfil.empty else {
    'genero': 'Masculino', 'idade': 41, 'altura_cm': 185, 'atividade': 'Sedentário (1.2)', 
    'ritmo_semanal': 0.8, 'meta_kcal': 1650, 'meta_proteina': 110, 'meta_carbo': 150, 'meta_gordura': 50, 'meta_peso_alvo': 120.0
}
PESO_ATUAL = float(df_peso_last.iloc[0]['peso_kg']) if not df_peso_last.empty else 141.9

# --- 2. BARRA LATERAL COM CÁLCULO DINÂMICO ---
st.sidebar.header("🧮 Perfil Biométrico")

# Usamos a barra lateral fora do form para o cálculo ser instantâneo ao mudar os números
gen = st.sidebar.radio("Gênero:", ["Masculino", "Feminino"], index=0 if p['genero'] == "Masculino" else 1)
idade = st.sidebar.number_input("Idade:", value=int(p['idade']))
alt = st.sidebar.number_input("Altura (cm):", value=int(p['altura_cm']))
peso_ref = st.sidebar.number_input("Peso para Cálculo (kg):", value=PESO_ATUAL)

ativ_ops = {"Sedentário (1.2)": 1.2, "Leve (1.375)": 1.375, "Moderado (1.55)": 1.55, "Alto (1.725)": 1.725}
ativ_sel = st.sidebar.selectbox("Fator de Movimento:", list(ativ_ops.keys()), index=list(ativ_ops.keys()).index(p['atividade']))

# CÁLCULO CIENTÍFICO AUTOMÁTICO
tmb = (10 * peso_ref) + (6.25 * alt) - (5 * idade) + (5 if gen == "Masculino" else -161)
get_total = tmb * ativ_ops[ativ_sel]
sugestao_kcal = int(get_total - 500) # Déficit moderado padrão

st.sidebar.info(f"🧬 **Cálculo Atual:**\nBasal: {int(tmb)} kcal\nGasto Total: {int(get_total)} kcal\nSugestão Dieta: {sugestao_kcal} kcal")

with st.sidebar.form("salvar_metas"):
    st.write("### Ajuste Final e Salvar")
    mkcal = st.number_input("Meta Kcal Final:", value=int(p['meta_kcal']))
    mprot = st.number_input("Meta Proteína (g):", value=int(p['meta_proteina']))
    mcarb = st.number_input("Meta Carbo (g):", value=int(p.get('meta_carbo', 150)))
    mgord = st.number_input("Meta Gordura (g):", value=int(p.get('meta_gordura', 50)))
    palvo = st.number_input("Peso Alvo (kg):", value=float(p['meta_peso_alvo']))
    ritmo = st.slider("Ritmo (kg/sem):", 0.1, 2.0, float(p['ritmo_semanal']))

    if st.form_submit_button("💾 Salvar Perfil no SQL"):
        run_query("""
            INSERT INTO public.perfil (id, genero, idade, altura_cm, atividade, ritmo_semanal, meta_kcal, meta_proteina, meta_carbo, meta_gordura, meta_peso_alvo)
            VALUES (1, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET 
            genero=EXCLUDED.genero, idade=EXCLUDED.idade, altura_cm=EXCLUDED.altura_cm, atividade=EXCLUDED.atividade,
            ritmo_semanal=EXCLUDED.ritmo_semanal, meta_kcal=EXCLUDED.meta_kcal, meta_proteina=EXCLUDED.meta_proteina,
            meta_carbo=EXCLUDED.meta_carbo, meta_gordura=EXCLUDED.meta_gordura, meta_peso_alvo=EXCLUDED.meta_peso_alvo;
        """, (gen, idade, alt, ativ_sel, ritmo, mkcal, mprot, mcarb, mgord, palvo), is_select=False)
        st.rerun()

# --- 3. GRÁFICOS (ORIGINAIS) ---
# ... (O restante do código de gráficos permanece igual ao que você já aprovou)
