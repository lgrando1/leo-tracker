import streamlit as st
import pandas as pd
import psycopg2
from psycopg2 import OperationalError, InterfaceError
from datetime import datetime, timedelta
import json
import os
import pytz  # Necessário para corrigir o fuso horário

# 1. CONFIGURAÇÃO DA PÁGINA
st.set_page_config(page_title="Leo Tracker Pro", page_icon="🦁", layout="wide")

# --- FUNÇÃO DE TEMPO (BRASÍLIA) ---
def get_now_br():
    """Retorna o datetime atual no fuso de Brasília."""
    return datetime.now(pytz.timezone('America/Sao_Paulo'))

# --- DADOS NUTRICIONAIS ---
nutrition_data = {
    "contexto_nutricional": {
        "dieta": "Restrição ao Glúten (foco auxiliar no controle da ansiedade).",
        "suplementacao_ativos": [
            "L-teanina",
            "Griffonia simplicifolia (5-HTP)",
            "L-triptofano",
            "GABA"
        ],
        "atencao_farmacologica": "Considerar interação com o uso contínuo de Bupropiona."
    },
    "substitutos": {
        "farinhas_espessantes": [
            "Farinha de Amêndoas ou Castanhas (baixo carboidrato)",
            "Farinha de Arroz (textura neutra)",
            "Polvilho Docce/Azedo ou Tapioca (para liga e elasticidade)",
            "Farinha de Aveia (certificada Gluten-Free)"
        ],
        "fontes_triptofano_gaba": [
            "Ovos, peixes e banana",
            "Cacau (chocolate amargo)",
            "Chá verde (fonte natural de L-teanina)"
        ]
    },
    "prompts_ia": {
        "encontrar_substituicao": (
            "Estou seguindo uma dieta estrita **sem glúten** e focada em alimentos anti-inflamatórios "
            "para controle de ansiedade. Quero fazer [NOME DA RECEITA/PRATO], mas a receita original leva "
            "[INGREDIENTE COM GLÚTEN, EX: FARINHA DE TRIGO].\n\n"
            "Por favor, liste 3 opções de substituição que funcionem quimicamente nessa receita (mantendo a textura) "
            "e que sejam seguras para minha dieta. Explique como ajustar a quantidade para cada opção."
        ),
        "avaliar_alimento": (
            "Atue como um nutricionista focado em saúde mental e dietas restritivas.\n\n"
            "**Meu Perfil:** Dieta sem glúten, uso de Bupropiona e suplementação de precursores de "
            "serotonina/GABA (L-teanina, Triptofano).\n\n"
            "**O Alimento:** [COLAR LISTA DE INGREDIENTES OU NOME DO PRATO AQUI]\n\n"
            "**Tarefa:**\n"
            "1. Este alimento contém glúten ou traços perigosos?\n"
            "2. Existe algum ingrediente que possa interagir negativamente com minha medicação ou piorar a ansiedade "
            "(ex: excesso de estimulantes, glutamato monossódico)?\n"
            "3. Dê uma nota de 0 a 10 para o quão seguro este alimento é para meu perfil."
        )
    }
}

# --- SISTEMA DE LOGIN ---
def check_password():
    if "password_correct" not in st.session_state:
        st.session_state["password_correct"] = False
    if st.session_state["password_correct"]: return True
    st.title("🦁 Leo Tracker Login")
    password = st.text_input("Senha:", type="password")
    if st.button("Entrar"):
        if password == st.secrets["PASSWORD"]:
            st.session_state["password_correct"] = True
            st.rerun()
        else: st.error("Incorreta!")
    return False

if not check_password(): st.stop()

# 2. CONEXÃO BLINDADA (Reconecta se cair)
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
            cur.execute("SET search_path TO public")
            cur.execute("SET timezone TO 'America/Sao_Paulo'")
            
            if is_select:
                df = pd.read_sql(sql, conn, params=params)
                for col in df.select_dtypes(include=['datetimetz', 'datetime']).columns:
                    df[col] = df[col].dt.tz_localize(None)
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
META_KCAL = 1600
META_PROTEINA = 150

# 4. FUNÇÕES DE BANCO
def inicializar_banco():
    executar_sql("CREATE TABLE IF NOT EXISTS public.tabela_taco (id SERIAL PRIMARY KEY, alimento TEXT, kcal REAL, proteina REAL, carbo REAL, gordura REAL);")
    executar_sql("CREATE TABLE IF NOT EXISTS public.consumo (id SERIAL PRIMARY KEY, data DATE, alimento TEXT, quantidade REAL, kcal REAL, proteina REAL, carbo REAL, gordura REAL, gluten TEXT DEFAULT 'Não informado');")
    executar_sql("CREATE TABLE IF NOT EXISTS public.peso (id SERIAL PRIMARY KEY, data DATE, peso_kg REAL);")

# 5. INICIALIZAÇÃO
inicializar_banco()

# 6. INTERFACE
st.title("🦁 Leo Tracker Pro")
tab_prato, tab_ia, tab_plano, tab_hist, tab_peso, tab_admin = st.tabs(["🍽️ Registro", "🤖 IA/JSON", "📝 Meu Plano", "📊 Histórico", "⚖️ Peso", "⚙️ Admin"])

# --- ABA 1: BUSCA MANUAL ---
with tab_prato:
    st.subheader("Registo Rápido (Base TACO)")
    agora_br = get_now_br()
    data_hoje = agora_br.date()
    df_hoje = executar_sql("SELECT * FROM public.consumo WHERE data = %s", (data_hoje,), is_select=True)
    
    kcal_hoje = float(df_hoje['kcal'].sum()) if not df_hoje.empty else 0.0
    prot_hoje = float(df_hoje['proteina'].sum()) if not df_hoje.empty else 0.0
    
    c1, c2 = st.columns(2)
    c1.metric("Kcal", f"{int(kcal_hoje)} / {META_KCAL}", f"Resta: {int(META_KCAL - kcal_hoje)}")
    c2.metric("Proteína", f"{int(prot_hoje)} / {META_PROTEINA}g", f"Resta: {int(META_PROTEINA - prot_hoje)}")
    st.progress(min(kcal_hoje/META_KCAL, 1.0))

    termo = st.text_input("🔍 Pesquisar alimento:")
    if termo:
        df_res = executar_sql("SELECT * FROM public.tabela_taco WHERE alimento ILIKE %s ORDER BY alimento ASC LIMIT 50", (f'%{termo}%',), is_select=True)
        if not df_res.empty:
            escolha = st.selectbox("Selecione:", df_res["alimento"])
            dados = df_res[df_res["alimento"] == escolha].iloc[0]
            qtd = st.number_input("Peso (g):", 0, 2000, 100)
            fator = float(qtd) / 100.0
            
            if st.button("Confirmar Refeição"):
                executar_sql("INSERT INTO public.consumo (data, alimento, quantidade, kcal, proteina, carbo, gordura, gluten) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)", 
                            (get_now_br().date(), str(escolha), float(qtd), float(round(dados['kcal']*fator)), float(round(dados['proteina']*fator,1)), float(round(dados['carbo']*fator,1)), float(round(dados['gordura']*fator,1)), "Não informado"))
                st.rerun()

# --- ABA 2: IMPORTAR DA IA ---
with tab_ia:
    st.subheader("Importar JSON da IA")
    json_input = st.text_area("JSON:", height=150)
    if st.button("Processar JSON"):
        if json_input:
            try:
                limpo = json_input.replace('```json', '').replace('```', '').strip()
                for item in json.loads(limpo):
                    executar_sql("INSERT INTO public.consumo (data, alimento, quantidade, kcal, proteina, carbo, gordura, gluten) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)", 
                                (get_now_br().date(), item['alimento'], 1.0, float(item['kcal']), float(item['p']), float(item['c']), float(item['g']), item.get('gluten', 'Não informado')))
                st.success("Importado!")
                st.rerun()
            except Exception as e: st.error(f"Erro: {e}")

# --- ABA 3: PLANO ---
with tab_plano:
    st.header("📋 Plano Alimentar & Estratégia")
    st.info(f"**Foco:** {nutrition_data['contexto_nutricional']['dieta']}")
    st.warning(f"**Atenção:** {nutrition_data['contexto_nutricional']['atencao_farmacologica']}")
    
    with st.expander("☕ Café da Manhã (Premium vs Econômico)"):
        c1, c2 = st.columns(2)
        c1.markdown("💎 **Original:** Whey, Morango, Chia")
        c2.markdown("💰 **Econômico:** 3 Ovos, Banana, Aveia")

# --- ABA 4: HISTÓRICO ---
with tab_hist:
    st.subheader("Últimos 7 dias")
    df_hist = executar_sql("SELECT * FROM public.consumo WHERE data >= %s ORDER BY data DESC, id DESC", ((get_now_br() - timedelta(days=7)).date(),), is_select=True)
    if not df_hist.empty:
        for i, row in df_hist.iterrows():
            c1, c2, c3 = st.columns([3, 2, 0.5])
            c1.write(f"**{row['alimento']}**")
            c2.write(f"{int(row['kcal'])} kcal {'🚫' if row['gluten'] == 'Contém' else ''}")
            if c3.button("🗑️", key=f"d_{row['id']}"):
                executar_sql("DELETE FROM public.consumo WHERE id = %s", (row['id'],))
                st.rerun()

# --- ABA 5: PESO ---
with tab_peso:
    p_val = st.number_input("Peso (kg):", 40.0, 200.0, 145.0)
    if st.button("Gravar Peso"):
        executar_sql("INSERT INTO public.peso (data, peso_kg) VALUES (%s, %s)", (get_now_br().date(), float(p_val)))
        st.rerun()
    df_p = executar_sql("SELECT * FROM public.peso ORDER BY data DESC", is_select=True)
    if not df_p.empty: st.line_chart(df_p.set_index('data'))

# --- ABA 6: ADMIN ---
with tab_admin:
    st.subheader("⚙️ Configurações de Administrador")
    if st.button("Sincronizar CSV de Alimentos"):
        # Chamada da função de carga (alimentos.csv)
        st.info("Iniciando sincronização...")

    st.divider()
    st.subheader("🛠️ Ferramentas de Dados & Fuso Horário")
    
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Corrigir Lançamentos Noturnos"):
            sql_fix_noite = """
                UPDATE public.consumo 
                SET data = data - INTERVAL '1 day' 
                WHERE data = CURRENT_DATE 
                AND (SELECT EXTRACT(HOUR FROM (CURRENT_TIMESTAMP AT TIME ZONE 'UTC' AT TIME ZONE 'America/Sao_Paulo'))) < 3;
            """
            if executar_sql(sql_fix_noite):
                st.success("Registros noturnos ajustados!")
                st.rerun()

    with col2:
        if st.button("Limpar Datas Futuras"):
            sql_fix_futuro = "UPDATE public.consumo SET data = CURRENT_DATE WHERE data > CURRENT_DATE"
            if executar_sql(sql_fix_futuro):
                st.success("Histórico futuro corrigido!")
                st.rerun()
                
    if st.button("Corrigir Tabela de Peso (Futuro)"):
        sql_fix_peso = "UPDATE public.peso SET data = CURRENT_DATE WHERE data > CURRENT_DATE"
        if executar_sql(sql_fix_peso):
            st.success("Datas da tabela de peso corrigidas!")
            st.rerun()
