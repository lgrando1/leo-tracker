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

# 3. SINCRONIZAÇÃO COM O DASHBOARD
def inicializar_banco():
    # Tabelas de registros
    executar_sql("CREATE TABLE IF NOT EXISTS public.consumo (id SERIAL PRIMARY KEY, data DATE, alimento TEXT, quantidade REAL, kcal REAL, proteina REAL, carbo REAL, gordura REAL, gluten TEXT DEFAULT 'Não informado');")
    executar_sql("CREATE TABLE IF NOT EXISTS public.peso (id SERIAL PRIMARY KEY, data DATE, peso_kg REAL);")
    
    # Tabela de Perfil (Compatível com o Dashboard)
    # Se não existir, cria. Se existir, mantém.
    executar_sql("""
        CREATE TABLE IF NOT EXISTS public.perfil (
            id SERIAL PRIMARY KEY, 
            genero TEXT, idade INT, altura_cm INT, atividade TEXT, 
            objetivo TEXT, ritmo_semanal REAL, 
            meta_kcal REAL, meta_proteina REAL, meta_carbo REAL, meta_gordura REAL, meta_peso_alvo REAL
        );
    """)

def get_metas_do_banco():
    """Puxa as metas definidas no Dashboard (Tabela perfil ID 1)."""
    try:
        df = executar_sql("SELECT * FROM public.perfil WHERE id = 1", is_select=True)
        if not df.empty:
            row = df.iloc[0]
            return {
                "kcal": int(row['meta_kcal']),
                "prot": int(row['meta_proteina']),
                "carb": int(row.get('meta_carbo', 164)), # Fallback seguro
                "gord": int(row.get('meta_gordura', 67)),
                "peso_alvo": float(row.get('meta_peso_alvo', 120.0)),
                "ritmo": float(row.get('ritmo_semanal', 0.8))
            }
    except Exception as e:
        st.warning(f"Usando metas padrão (Erro leitura: {e})")
    
    # Seus valores fixos padrão (caso o banco esteja vazio)
    return {
        "kcal": 1683, "prot": 108, "carb": 164, "gord": 67, 
        "peso_alvo": 120.0, "ritmo": 0.8
    }

inicializar_banco()
METAS = get_metas_do_banco()

# 4. INTELIGÊNCIA ARTIFICIAL (GROQ) - COM LIMPEZA JSON
def processar_texto_ia(texto_usuario, api_key):
    client = Groq(api_key=api_key)
    
    prompt_system = f"""
    Aja como nutricionista. Dieta Sem Glúten. Hoje é {get_now_br().strftime('%Y-%m-%d')}.
    
    Sua tarefa:
    1. Analisar o texto.
    2. Gerar JSON estrito.
    
    Formato OBRIGATÓRIO (JSON puro, sem markdown):
    {{
        "analise": "Texto curto de feedback",
        "alimentos": [
            {{ "data": "AAAA-MM-DD", "alimento": "Nome", "quantidade_g": 0, "kcal": 0, "p": 0, "c": 0, "g": 0, "gluten": "Contém/Não contém" }}
        ]
    }}
    """
    
    try:
        completion = client.chat.completions.create(
            messages=[{"role": "system", "content": prompt_system}, {"role": "user", "content": texto_usuario}],
            model="llama-3.3-70b-versatile",
            temperature=0.1,
            response_format={"type": "json_object"}
        )
        # Limpeza robusta para a Groq
        raw = completion.choices[0].message.content
        clean = raw.replace('```json', '').replace('```', '').strip()
        return True, json.loads(clean)
    except Exception as e:
        return False, f"Erro na IA: {e}"

# 5. INTERFACE DO APP
st.title("🦁 Leo Tracker Pro")

# --- DASHBOARD DE HOJE ---
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

# --- ABAS ---
tab_add, tab_hist, tab_peso, tab_admin = st.tabs(["➕ Inserir", "📜 Diário", "⚖️ Peso", "⚙️ Metas (Sync)"])

# ABA 1: INSERIR
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
                        executar_sql(
                            "INSERT INTO public.consumo (data, alimento, quantidade, kcal, proteina, carbo, gordura, gluten) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                            (item.get('data'), item.get('alimento'), item.get('quantidade_g'), item.get('kcal'), item.get('p'), item.get('c'), item.get('g'), item.get('gluten'))
                        )
                    st.rerun()
                else:
                    st.error(f"Erro IA: {res}")
    
    with st.expander("Importação JSON (Gemini/ChatGPT) - MODO CIRÚRGICO"):
        st.info("Pode colar o texto bagunçado do Gemini. O sistema vai extrair apenas o JSON.")
        json_manual = st.text_area("Cole a resposta do Gemini:")
        
        if st.button("Salvar JSON Importado"):
            if json_manual:
                try:
                    # --- LIMPEZA CIRÚRGICA ---
                    # 1. Remove formatação markdown
                    cleaned = json_manual.replace('```json', '').replace('```', '').strip()
                    
                    # 2. Busca o primeiro '[' e o último ']'
                    start = cleaned.find('[')
                    end = cleaned.rfind(']')
                    
                    if start != -1 and end != -1:
                        # Pega apenas o conteúdo entre colchetes
                        cleaned = cleaned[start : end + 1]
                    
                    # 3. Converte
                    lista = json.loads(cleaned)
                    
                    # 4. Salva
                    count = 0
                    for item in (lista if isinstance(lista, list) else [lista]):
                        dt = item.get('data') if item.get('data') else data_hoje
                        executar_sql("INSERT INTO public.consumo (data, alimento, quantidade, kcal, proteina, carbo, gordura, gluten) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                                    (dt, item.get('alimento'), item.get('quantidade_g'), item.get('kcal'), item.get('p'), item.get('c'), item.get('g'), item.get('gluten')))
                        count += 1
                    
                    st.success(f"{count} itens salvos!")
                    st.rerun()
                except Exception as e: 
                    st.error(f"Não foi possível ler o JSON. Erro técnico: {e}")

# ABA 2: HISTÓRICO
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
                    executar_sql("DELETE FROM public.consumo WHERE id = %s", (row['id'],))
                    st.rerun()
                st.markdown("---")
    else:
        st.info("Nada registrado hoje.")

# ABA 3: PESO
with tab_peso:
    st.write(f"### Rumo aos {METAS['peso_alvo']}kg")
    
    # Input Peso
    c_dt, c_val, c_btn = st.columns([1.5, 1.5, 1])
    dt_lanc = c_dt.date_input("Data:", value=data_hoje)
    
    # Pega último peso
    ultimo = executar_sql("SELECT peso_kg FROM public.peso ORDER BY data DESC LIMIT 1", is_select=True)
    val_padrao = float(ultimo.iloc[0]['peso_kg']) if not ultimo.empty else 125.0
    p_val = c_val.number_input("Peso (kg):", 40.0, 200.0, step=0.1, value=val_padrao)
    
    c_btn.write("")
    c_btn.write("")
    if c_btn.button("💾 Salvar"):
        executar_sql("INSERT INTO public.peso (data, peso_kg) VALUES (%s, %s)", (dt_lanc, p_val))
        st.success("Salvo!"); st.rerun()

    st.divider()
    
    # Gráfico (Igual ao Dashboard)
    df_p = executar_sql("SELECT * FROM public.peso ORDER BY data ASC", is_select=True)
    if not df_p.empty and len(df_p) > 0:
        df_p['data'] = pd.to_datetime(df_p['data'])
        df_p = df_p.sort_values('data')
        
        # INÍCIO DO REGIME EM 30/12/2025 (Fixo conforme pedido)
        DATA_INICIO_REGIME = pd.to_datetime("2025-12-30").date()
        
        # Encontra peso referência na data de início
        df_p['diff'] = abs(df_p['data'].dt.date - DATA_INICIO_REGIME)
        idx_ref = df_p['diff'].idxmin()
        peso_start = df_p.loc[idx_ref, 'peso_kg']
        
        # Projeção
        u_dia = max(df_p['data'].max().date(), data_hoje) + timedelta(days=45)
        dias_proj = (u_dia - DATA_INICIO_REGIME).days
        
        if dias_proj > 0:
            lst_data = [DATA_INICIO_REGIME + timedelta(days=x) for x in range(dias_proj + 1)]
            # Usa o ritmo definido no Dashboard
            lst_peso = [max(METAS['peso_alvo'], peso_start - (x * (METAS['ritmo']/7))) for x in range(dias_proj + 1)]
            
            df_meta = pd.DataFrame({'data': lst_data, 'Meta': lst_peso}).set_index('data')
            df_real = df_p[['data', 'peso_kg']].set_index('data')
            
            st.line_chart(df_real.join(df_meta, how='outer'), color=["#0000FF", "#AAAAAA"])
            st.caption(f"Meta: Perder {METAS['ritmo']}kg/semana (Configurado no Dashboard).")

# ABA 4: CONFIGURAR METAS (Sincronizado)
with tab_admin:
    st.header("⚙️ Sincronia de Metas")
    st.info("Estas metas são compartilhadas com o Dashboard. Alterar aqui reflete lá e vice-versa.")
    
    with st.form("form_sync"):
        c1, c2 = st.columns(2)
        nk = c1.number_input("Meta Kcal:", value=METAS['kcal'], step=50)
        np = c2.number_input("Meta Proteína (g):", value=METAS['prot'], step=5)
        
        c3, c4 = st.columns(2)
        nc = c3.number_input("Meta Carbo (g):", value=METAS['carb'], step=5)
        ng = c4.number_input("Meta Gordura (g):", value=METAS['gord'], step=5)
        
        st.divider()
        c5, c6 = st.columns(2)
        npa = c5.number_input("Peso Alvo Final (kg):", value=METAS['peso_alvo'], step=1.0)
        nrs = c6.number_input("Ritmo Semanal (kg/sem):", value=METAS['ritmo'], step=0.1)
        
        if st.form_submit_button("💾 Atualizar Banco de Dados"):
            # Atualiza mantendo compatibilidade com as colunas do Dashboard
            executar_sql("""
                UPDATE public.perfil 
                SET meta_kcal=%s, meta_proteina=%s, meta_carbo=%s, meta_gordura=%s, meta_peso_alvo=%s, ritmo_semanal=%s
                WHERE id=1
            """, (nk, np, nc, ng, npa, nrs))
            st.success("Sincronizado! Recarregando...")
            st.rerun()

st.caption(f"Leo Tracker Pro v3.2 | Sync Mode Active")
