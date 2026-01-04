import streamlit as st
import pandas as pd
import psycopg2
from psycopg2 import OperationalError
from datetime import datetime, timedelta
import json
import pytz 
from groq import Groq 

# 1. CONFIGURAÇÃO DA PÁGINA
st.set_page_config(page_title="Leo Tracker Pro", page_icon="🦁", layout="wide")

# --- FUNÇÃO DE TEMPO (BRASÍLIA) ---
def get_now_br():
    """Retorna o datetime atual no fuso de Brasília."""
    return datetime.now(pytz.timezone('America/Sao_Paulo'))

# --- DADOS DO PLANO ALIMENTAR ---
PLANO_ALIMENTAR = {
    "Café da Manhã": {
        "Premium (Nutri)": "Whey Protein (17g) + Morangos (200g) + Linhaça/Chia",
        "Econômico (Raiz)": "3 Ovos cozidos/mexidos + 1 Banana Prata + Aveia (Sem Glúten)",
        "Dica": "O ovo é a fonte de proteína mais barata e biodisponível."
    },
    "Almoço": {
        "Premium (Nutri)": "Salmão (120g) + Espinafre + Quinoa/Mandioquinha",
        "Econômico (Raiz)": "Sardinha (lata) ou Peito de Frango + Couve refogada + Arroz com Feijão",
        "Dica": "Arroz e Feijão = combinação perfeita. Sardinha substitui o Salmão."
    },
    "Lanche da Tarde": {
        "Premium (Nutri)": "Frutas Vermelhas/Pera + Castanha do Pará",
        "Econômico (Raiz)": "1 Maçã ou Banana + Pasta de Amendoim (1 colher) ou Ovo cozido",
        "Dica": "Pasta de amendoim rende mais que castanhas."
    },
    "Jantar": {
        "Premium (Nutri)": "Filé Mignon/Contra-filé magro + Brócolis + Batata Inglesa",
        "Econômico (Raiz)": "Patinho Moído ou Fígado + Repolho refogado + Batata Doce",
        "Dica": "Patinho moído é versátil e barato."
    },
    "Ceia": {
        "Premium (Nutri)": "Iogurte Proteico + Mel + Torrada sem glúten",
        "Econômico (Raiz)": "Pipoca de panela (sem óleo) + 1 fatia de Queijo Minas",
        "Dica": "Pipoca é excelente para saciedade noturna."
    }
}

# --- SISTEMA DE LOGIN ---
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

# 2. CONEXÃO AO BANCO NEON
@st.cache_resource(ttl=600)
def get_connection_raw():
    return psycopg2.connect(st.secrets["DATABASE_URL"])

def executar_sql(sql, params=None, is_select=False):
    conn = None
    try:
        conn = get_connection_raw()
        if conn.closed != 0:
            st.cache_resource.clear()
            conn = get_connection_raw()
            
        with conn.cursor() as cur:
            cur.execute("SET timezone TO 'America/Sao_Paulo';")
            
            if is_select:
                df = pd.read_sql(sql, conn, params=params)
                if 'data' in df.columns:
                    df['data'] = pd.to_datetime(df['data'])
                return df
            else:
                cur.execute(sql, params)
                conn.commit()
                return True
    except Exception as e:
        if conn: conn.rollback()
        st.error(f"Erro no Banco de Dados: {e}")
        return pd.DataFrame() if is_select else False

# 3. CONSTANTES E METAS
META_KCAL = 1650 
META_PROTEINA = 110 
META_PESO = 120.0
PERDA_SEMANAL_KG = 0.8

# 4. INICIALIZAÇÃO DAS TABELAS
def inicializar_banco():
    queries = [
        "CREATE TABLE IF NOT EXISTS public.consumo (id SERIAL PRIMARY KEY, data DATE, alimento TEXT, quantidade REAL, kcal REAL, proteina REAL, carbo REAL, gordura REAL, gluten TEXT DEFAULT 'Não informado');",
        "CREATE TABLE IF NOT EXISTS public.peso (id SERIAL PRIMARY KEY, data DATE, peso_kg REAL);",
        "CREATE TABLE IF NOT EXISTS public.tabela_taco (id SERIAL PRIMARY KEY, alimento TEXT, kcal REAL, proteina REAL, carbo REAL, gordura REAL);"
    ]
    for q in queries: executar_sql(q)

inicializar_banco()

# --- FUNÇÃO NOVA: TEXTO -> GROQ (JSON + ANÁLISE) ---
def processar_texto_ia(texto_usuario, api_key):
    """Envia texto para Groq e retorna JSON com 'analise' e 'alimentos'."""
    client = Groq(api_key=api_key)
    
    prompt_system = f"""
    Aja como um nutricionista focado em:
    1. Dieta Sem Glúten (Restrição severa).
    2. Controle de Ansiedade (Alimentos anti-inflamatórios).
    3. Hipertrofia (Meta proteica).
    
    Hoje é: {get_now_br().strftime('%Y-%m-%d')}.
    
    Sua tarefa:
    1. Analisar o texto do usuário.
    2. Gerar uma breve "analise" (máx 3 frases): Destaque pontos positivos ou negativos (ex: alertar sobre glúten ou excesso de gordura/açúcar, elogiar proteína).
    3. Gerar a lista técnica "alimentos" com macros estimados.
    
    SAÍDA OBRIGATÓRIA: Um JSON com duas chaves ("analise" e "alimentos").
    Exemplo:
    {{
        "analise": "Cuidado! O pastel é frito e a massa tem glúten, o que pode aumentar a inflamação. Tente evitar.",
        "alimentos": [
            {{
                "data": "AAAA-MM-DD",
                "alimento": "Pastel de Carne Frito",
                "quantidade_g": 100,
                "kcal": 350,
                "p": 10,
                "c": 35,
                "g": 20,
                "gluten": "Contém"
            }}
        ]
    }}
    """

    try:
        completion = client.chat.completions.create(
            messages=[
                {"role": "system", "content": prompt_system},
                {"role": "user", "content": texto_usuario}
            ],
            model="llama-3.3-70b-versatile", 
            temperature=0.3, # Um pouco de criatividade para a análise
            response_format={"type": "json_object"}
        )
        
        resposta_json = completion.choices[0].message.content
        dados = json.loads(resposta_json)
        
        # Garante estrutura
        if "alimentos" not in dados:
             # Fallback caso a IA esqueça a estrutura (raro)
             return False, "Erro na estrutura do JSON da IA."
            
        return True, dados
    except Exception as e:
        return False, f"Erro na IA: {e}"

# 5. INTERFACE DO APP
st.title("🦁 Leo Tracker Pro")
st.markdown(f"**Data Atual (BR):** {get_now_br().strftime('%d/%m/%Y %H:%M')}")

# Abas
tab_groq, tab_json, tab_plano, tab_hist, tab_peso, tab_admin = st.tabs(["🍽️ IA Rápida", "🤖 JSON (Gemini)", "📝 Plano", "📊 Gráficos & Metas", "⚖️ Peso (120kg)", "⚙️ Admin"])

# --- ABA 1: IA RÁPIDA (GROQ) ---
with tab_groq:
    st.subheader("Resumo do Dia")
    data_hoje = get_now_br().date()
    df_hoje = executar_sql("SELECT * FROM public.consumo WHERE data = %s", (data_hoje,), is_select=True)
    
    kcal_hoje = float(df_hoje['kcal'].sum()) if not df_hoje.empty else 0.0
    prot_hoje = float(df_hoje['proteina'].sum()) if not df_hoje.empty else 0.0
    
    c1, c2, c3 = st.columns(3)
    c1.metric("Kcal", f"{int(kcal_hoje)}", f"Meta: {META_KCAL}")
    c2.metric("Proteína", f"{int(prot_hoje)}g", f"Meta: {META_PROTEINA}g")
    c3.progress(min(kcal_hoje/META_KCAL, 1.0))
    
    st.divider()
    
    st.write("#### 💬 O que você comeu?")
    st.caption("A IA vai analisar seus macros e te dar um feedback sobre a dieta.")
    
    texto_input = st.text_area("Descreva aqui:", height=100)
    
    if st.button("🚀 Processar"):
        api_key = st.secrets.get("GROQ_API_KEY")
        if not api_key:
            st.error("⚠️ Configure a GROQ_API_KEY nos secrets!")
        elif not texto_input:
            st.warning("Digite algo primeiro.")
        else:
            with st.spinner("Analisando nutricionalmente..."):
                sucesso, resultado = processar_texto_ia(texto_input, api_key)
                
                if sucesso:
                    # 1. Exibe a Análise da Nutri IA
                    analise = resultado.get('analise', 'Sem análise.')
                    
                    # Define cor da caixa baseada no texto (simples heurística)
                    if "cuidado" in analise.lower() or "evit" in analise.lower() or "glúten" in analise.lower():
                        st.warning(f"👩‍⚕️ **Feedback da IA:**\n\n{analise}")
                    else:
                        st.success(f"👩‍⚕️ **Feedback da IA:**\n\n{analise}")
                    
                    # 2. Exibe os Itens Técnicos
                    st.markdown("---")
                    st.write("**Itens identificados:**")
                    
                    count = 0
                    lista_alimentos = resultado.get('alimentos', [])
                    
                    for item in lista_alimentos:
                        col_ico, col_txt = st.columns([0.5, 4])
                        col_ico.info("🍽️")
                        col_txt.write(f"**{item['alimento']}** ({item['quantidade_g']}g) | 🔥 {item['kcal']} kcal | 🥩 {item['p']}g prot")
                        
                        # Salva no banco
                        executar_sql(
                            """INSERT INTO public.consumo (data, alimento, quantidade, kcal, proteina, carbo, gordura, gluten) 
                               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""", 
                            (
                                item.get('data'), item.get('alimento'), float(item.get('quantidade_g', 1)), 
                                float(item.get('kcal', 0)), float(item.get('p', 0)), 
                                float(item.get('c', 0)), float(item.get('g', 0)), item.get('gluten', 'NI')
                            )
                        )
                        count += 1
                    
                    if count > 0:
                        st.success("✅ Dados salvos no banco!")
                        import time
                        # AUMENTADO PARA 15 SEGUNDOS PARA DAR TEMPO DE LER
                        time.sleep(15) 
                        st.rerun()
                else:
                    st.error(f"Erro: {resultado}")

# --- ABA 2: IMPORTAR JSON (MANUAL/GEMINI) ---
with tab_json:
    st.header("🤖 Importação via JSON (Gemini)")
    st.markdown("**Copie este prompt para o Gemini (com foto):**")
    prompt_json = """
    Analise a imagem. Atue como nutricionista.
    Gere APENAS um JSON (sem texto) neste formato de lista:
    [
      {
        "data": "2024-05-20", 
        "alimento": "Nome",
        "quantidade_g": 100,
        "kcal": 150,
        "p": 20,
        "c": 10,
        "g": 5,
        "gluten": "Contém" ou "Não contém"
      }
    ]
    (Se a data não for informada, use a data de hoje AAAA-MM-DD).
    """
    st.code(prompt_json, language="text")
    json_input = st.text_area("Cole o JSON aqui:", height=150)
    
    if st.button("Processar JSON Manual"):
        if json_input:
            try:
                limpo = json_input.replace('```json', '').replace('```', '').strip()
                lista = json.loads(limpo)
                if isinstance(lista, dict): lista = [lista]
                
                count = 0
                for item in lista:
                    dt_final = item.get('data') if item.get('data') else get_now_br().date()
                    executar_sql(
                        """INSERT INTO public.consumo (data, alimento, quantidade, kcal, proteina, carbo, gordura, gluten) 
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""", 
                        (dt_final, item.get('alimento', '?'), float(item.get('quantidade_g', 1)), float(item.get('kcal', 0)), float(item.get('p', 0)), float(item.get('c', 0)), float(item.get('g', 0)), item.get('gluten', 'NI'))
                    )
                    count += 1
                st.success(f"{count} itens importados!")
                st.rerun()
            except Exception as e: st.error(f"Erro: {e}")

# --- ABA 3: PLANO ALIMENTAR ---
with tab_plano:
    st.header("📋 Plano: Nutri vs. Econômico")
    for ref, dados in PLANO_ALIMENTAR.items():
        with st.expander(ref, expanded=True):
            c_a, c_b = st.columns(2)
            c_a.markdown(f"💎 **Ideal**\n\n{dados['Premium (Nutri)']}")
            c_b.markdown(f"💰 **Econômico**\n\n{dados['Econômico (Raiz)']}")
            st.caption(f"💡 {dados['Dica']}")

# --- ABA 4: HISTÓRICO E GRÁFICOS ---
with tab_hist:
    st.subheader("📊 Performance Diária")
    dt_inicio = (get_now_br() - timedelta(days=14)).date() 
    sql_chart = """
        SELECT data, SUM(kcal) as kcal, SUM(proteina) as proteina 
        FROM public.consumo WHERE data >= %s GROUP BY data ORDER BY data ASC
    """
    df_chart = executar_sql(sql_chart, (dt_inicio,), is_select=True)
    
    if not df_chart.empty:
        df_chart = df_chart.sort_values(by='data')
        df_chart['Meta Kcal'] = META_KCAL
        df_chart['Meta Proteína'] = META_PROTEINA
        df_chart.set_index('data', inplace=True)
        
        c_graf1, c_graf2 = st.columns(2)
        with c_graf1:
            st.markdown("#### 🔥 Calorias")
            st.line_chart(df_chart[['kcal', 'Meta Kcal']], color=["#FF4B4B", "#00FF00"])
        with c_graf2:
            st.markdown("#### 🥩 Proteínas")
            st.line_chart(df_chart[['proteina', 'Meta Proteína']], color=["#3366CC", "#00FF00"])
    
    st.divider()
    st.subheader("📜 Diário de Consumo")
    df_detalhe = executar_sql("SELECT * FROM public.consumo WHERE data >= %s ORDER BY data DESC, id DESC", (dt_inicio,), is_select=True)
    
    if not df_detalhe.empty:
        for i, row in df_detalhe.iterrows():
            col_dt, col_nm, col_kc, col_del = st.columns([1.5, 3, 1.5, 1])
            data_vis = pd.to_datetime(row['data']).strftime('%d/%m/%Y')
            col_dt.write(f"**{data_vis}**")
            col_nm.write(f"{row['alimento']}")
            col_kc.write(f"{int(row['kcal'])} kcal")
            if col_del.button("❌", key=f"del_{row['id']}"):
                executar_sql("DELETE FROM public.consumo WHERE id = %s", (row['id'],))
                st.rerun()

# --- ABA 5: PESO ---
with tab_peso:
    st.subheader(f"⚖️ Rumo aos {int(META_PESO)}kg")
    c_input, c_meta = st.columns([2, 1])
    p_val = c_input.number_input("Registrar Peso Atual (kg):", 40.0, 200.0, step=0.1)
    
    if c_input.button("Gravar Peso"):
        executar_sql("INSERT INTO public.peso (data, peso_kg) VALUES (%s, %s)", (get_now_br().date(), float(p_val)))
        st.success("Peso registrado!")
        st.rerun()

    df_p = executar_sql("SELECT * FROM public.peso ORDER BY data ASC", is_select=True)
    if not df_p.empty and len(df_p) > 0:
        df_p['data'] = pd.to_datetime(
