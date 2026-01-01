import streamlit as st
import pandas as pd
import psycopg2
from psycopg2 import OperationalError
from datetime import datetime, timedelta
import json
import pytz 

# 1. CONFIGURAÇÃO DA PÁGINA
st.set_page_config(page_title="Leo Tracker Pro", page_icon="🦁", layout="wide")

# --- FUNÇÃO DE TEMPO (BRASÍLIA) ---
def get_now_br():
    """Retorna o datetime atual no fuso de Brasília."""
    return datetime.now(pytz.timezone('America/Sao_Paulo'))

# --- DADOS DO PLANO ALIMENTAR (PDF + VERSÃO ECONÔMICA) ---
PLANO_ALIMENTAR = {
    "Café da Manhã": {
        "Premium (Nutri)": "Whey Protein (17g) + Morangos (200g) + Linhaça/Chia",
        "Econômico (Raiz)": "3 Ovos cozidos/mexidos + 1 Banana Prata + Aveia (Sem Glúten)",
        "Dica": "O ovo é a fonte de proteína mais barata e biodisponível para substituir o Whey."
    },
    "Almoço": {
        "Premium (Nutri)": "Salmão (120g) + Espinafre + Quinoa/Mandioquinha",
        "Econômico (Raiz)": "Sardinha (lata) ou Peito de Frango + Couve refogada + Arroz com Feijão",
        "Dica": "Arroz e Feijão é a combinação perfeita sem glúten. Sardinha em lata substitui o Salmão no Ômega 3."
    },
    "Lanche da Tarde": {
        "Premium (Nutri)": "Frutas Vermelhas/Pera + Castanha do Pará",
        "Econômico (Raiz)": "1 Maçã ou Banana + Pasta de Amendoim (1 colher) ou Ovo cozido",
        "Dica": "Pasta de amendoim rende muito mais que castanhas nobres."
    },
    "Jantar": {
        "Premium (Nutri)": "Filé Mignon/Contra-filé magro + Brócolis + Batata Inglesa",
        "Econômico (Raiz)": "Patinho Moído ou Fígado + Repolho refogado + Batata Doce",
        "Dica": "Patinho moído é versátil e muito mais barato que cortes nobres."
    },
    "Ceia": {
        "Premium (Nutri)": "Iogurte Proteico + Mel + Torrada sem glúten",
        "Econômico (Raiz)": "Pipoca de panela (sem óleo/pouco azeite) + 1 fatia de Queijo Minas",
        "Dica": "Pipoca é um carboidrato complexo barato e excelente para saciedade noturna."
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
        # Em produção, use st.secrets["PASSWORD"]
        if password == st.secrets.get("PASSWORD", "admin"): 
            st.session_state["password_correct"] = True
            st.rerun()
        else: st.error("Senha incorreta!")
    return False

if not check_password(): st.stop()

# 2. CONEXÃO AO BANCO NEON (Postgres)
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
            # Força o timezone da SESSÃO para BRT
            cur.execute("SET timezone TO 'America/Sao_Paulo';")
            
            if is_select:
                df = pd.read_sql(sql, conn, params=params)
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
META_KCAL = 1600
META_PROTEINA = 150 

# 4. INICIALIZAÇÃO DAS TABELAS
def inicializar_banco():
    executar_sql("""
        CREATE TABLE IF NOT EXISTS public.consumo (
            id SERIAL PRIMARY KEY, 
            data DATE, 
            alimento TEXT, 
            quantidade REAL, 
            kcal REAL, 
            proteina REAL, 
            carbo REAL, 
            gordura REAL, 
            gluten TEXT DEFAULT 'Não informado'
        );
    """)
    executar_sql("""
        CREATE TABLE IF NOT EXISTS public.peso (
            id SERIAL PRIMARY KEY, 
            data DATE, 
            peso_kg REAL
        );
    """)
    executar_sql("""
        CREATE TABLE IF NOT EXISTS public.tabela_taco (
            id SERIAL PRIMARY KEY, 
            alimento TEXT, 
            kcal REAL, 
            proteina REAL, 
            carbo REAL, 
            gordura REAL
        );
    """)

inicializar_banco()

# 5. INTERFACE DO APP
st.title("🦁 Leo Tracker Pro")
st.markdown(f"**Data Atual (BR):** {get_now_br().strftime('%d/%m/%Y %H:%M')}")

tab_prato, tab_ia, tab_plano, tab_hist, tab_peso, tab_admin = st.tabs(["🍽️ Registrar", "🤖 Importar IA", "📝 Plano", "📊 Histórico", "⚖️ Peso", "⚙️ Admin"])

# --- ABA 1: REGISTRO MANUAL ---
with tab_prato:
    st.subheader("Resumo do Dia")
    
    data_hoje = get_now_br().date()
    df_hoje = executar_sql("SELECT * FROM public.consumo WHERE data = %s", (data_hoje,), is_select=True)
    
    kcal_hoje = float(df_hoje['kcal'].sum()) if not df_hoje.empty else 0.0
    prot_hoje = float(df_hoje['proteina'].sum()) if not df_hoje.empty else 0.0
    
    c1, c2, c3 = st.columns(3)
    c1.metric("Kcal Consumidas", f"{int(kcal_hoje)}", f"Meta: {META_KCAL}")
    c2.metric("Proteína (g)", f"{int(prot_hoje)}", f"Meta: {META_PROTEINA}g")
    saldo = int(META_KCAL - kcal_hoje)
    c3.metric("Saldo Kcal", f"{saldo}", delta_color="normal" if saldo > 0 else "inverse")
    
    st.progress(min(kcal_hoje/META_KCAL, 1.0))

    st.divider()
    st.write("#### Adicionar Alimento (Busca TACO)")
    termo = st.text_input("🔍 Digite o nome do alimento:", placeholder="Ex: Frango, Arroz, Ovo...")
    
    if termo:
        df_res = executar_sql("SELECT * FROM public.tabela_taco WHERE alimento ILIKE %s LIMIT 20", (f'%{termo}%',), is_select=True)
        
        if not df_res.empty:
            escolha = st.selectbox("Selecione o alimento:", df_res["alimento"])
            dados = df_res[df_res["alimento"] == escolha].iloc[0]
            
            col_qtd, col_btn = st.columns([2, 1])
            qtd = col_qtd.number_input("Quantidade (gramas):", 0, 2000, 100)
            
            if col_btn.button("✅ Registrar", use_container_width=True):
                fator = float(qtd) / 100.0
                executar_sql(
                    """INSERT INTO public.consumo 
                       (data, alimento, quantidade, kcal, proteina, carbo, gordura, gluten) 
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""", 
                    (
                        data_hoje, 
                        str(escolha), 
                        float(qtd), 
                        float(round(dados['kcal']*fator)), 
                        float(round(dados['proteina']*fator, 1)), 
                        float(round(dados['carbo']*fator, 1)), 
                        float(round(dados['gordura']*fator, 1)), 
                        "Não informado"
                    )
                )
                st.success(f"{escolha} registrado!")
                st.rerun()
        else:
            st.warning("Nenhum alimento encontrado na base TACO com esse nome.")
            with st.expander("Registrar Manualmente"):
                nm_man = st.text_input("Nome do Alimento:")
                kc_man = st.number_input("Kcal:", 0, 2000)
                pt_man = st.number_input("Proteína (g):", 0, 200)
                if st.button("Salvar Manual"):
                     executar_sql("INSERT INTO public.consumo (data, alimento, quantidade, kcal, proteina, carbo, gordura) VALUES (%s, %s, %s, %s, %s, 0, 0)", 
                                  (data_hoje, nm_man, 1, kc_man, pt_man))
                     st.rerun()

# --- ABA 2: IMPORTAR JSON (IA) ---
with tab_ia:
    st.header("🤖 Importação Inteligente")
    st.markdown("""
    **Passo 1:** Copie o prompt abaixo e envie para o Gemini junto com a foto da sua comida.
    """)
    
    prompt_json = """
    Analise a imagem e identifique os alimentos.
    Atue como nutricionista. Calcule as macros estimadas.
    Gere APENAS um JSON (sem texto antes ou depois) seguindo estritamente este formato de lista:
    [
      {
        "alimento": "Nome do alimento",
        "quantidade_g": 100,
        "kcal": 150,
        "p": 20,
        "c": 10,
        "g": 5,
        "gluten": "Contém" ou "Não contém"
      }
    ]
    """
    st.code(prompt_json, language="text")
    
    st.markdown("**Passo 2:** Cole a resposta do Gemini (o JSON) aqui embaixo:")
    
    json_input = st.text_area("Cole o JSON aqui:", height=150)
    
    if st.button("Processar JSON da IA"):
        if json_input:
            try:
                limpo = json_input.replace('```json', '').replace('```', '').strip()
                lista_alimentos = json.loads(limpo)
                if isinstance(lista_alimentos, dict): lista_alimentos = [lista_alimentos]
                
                count = 0
                for item in lista_alimentos:
                    executar_sql(
                        """INSERT INTO public.consumo 
                           (data, alimento, quantidade, kcal, proteina, carbo, gordura, gluten) 
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""", 
                        (
                            get_now_br().date(), 
                            item.get('alimento', 'Desconhecido'), 
                            float(item.get('quantidade_g', 1)), 
                            float(item.get('kcal', 0)), 
                            float(item.get('p', 0)), 
                            float(item.get('c', 0)), 
                            float(item.get('g', 0)), 
                            item.get('gluten', 'Não informado')
                        )
                    )
                    count += 1
                st.success(f"{count} itens importados com sucesso!")
                st.rerun()
            except Exception as e: st.error(f"Erro ao ler JSON: {e}")

# --- ABA 3: PLANO ALIMENTAR ---
with tab_plano:
    st.header("📋 Plano: Nutri vs. Econômico")
    
    for refeicao, dados in PLANO_ALIMENTAR.items():
        with st.expander(f"{refeicao}", expanded=True):
            col_a, col_b = st.columns(2)
            with col_a:
                st.markdown(f"💎 **Ideal**\n\n{dados['Premium (Nutri)']}")
            with col_b:
                st.markdown(f"💰 **Econômico**\n\n{dados['Econômico (Raiz)']}")
            st.caption(f"💡 *{dados['Dica']}*")

# --- ABA 4: HISTÓRICO E GRÁFICOS ---
with tab_hist:
    st.subheader("📊 Evolução (Últimos 7 dias)")
    
    dt_inicio = (get_now_br() - timedelta(days=7)).date()
    
    # Gráfico
    sql_chart = "SELECT data, SUM(kcal) as total_kcal FROM public.consumo WHERE data >= %s GROUP BY data ORDER BY data ASC"
    df_chart = executar_sql(sql_chart, (dt_inicio,), is_select=True)
    
    if not df_chart.empty:
        # Formatação forçada da data para String DD/MM para o gráfico não errar o fuso
        df_chart['data_str'] = pd.to_datetime(df_chart['data']).dt.strftime('%d/%m')
        st.bar_chart(df_chart, x='data_str', y='total_kcal', color="#4CAF50")
    
    st.divider()
    st.subheader("📜 Detalhamento")
    df_detalhe = executar_sql("SELECT * FROM public.consumo WHERE data >= %s ORDER BY data DESC, id DESC", (dt_inicio,), is_select=True)
    
    if not df_detalhe.empty:
        for i, row in df_detalhe.iterrows():
            col_dt, col_nm, col_kc, col_del = st.columns([1.5, 3, 1.5, 1])
            
            # TRUQUE DO FUSO HORÁRIO:
            # Como o banco pode retornar datetime com fuso errado, convertemos apenas a DATA
            data_vis = pd.to_datetime(row['data']).strftime('%d/%m/%Y')
            
            col_dt.write(f"📅 **{data_vis}**")
            col_nm.write(f"{row['alimento']}")
            col_kc.write(f"{int(row['kcal'])} kcal")
            
            if col_del.button("❌", key=f"del_{row['id']}"):
                executar_sql("DELETE FROM public.consumo WHERE id = %s", (row['id'],))
                st.rerun()

# --- ABA 5: PESO ---
with tab_peso:
    st.subheader("Acompanhamento de Peso")
    p_val = st.number_input("Peso (kg):", 40.0, 150.0, step=0.1)
    if st.button("Gravar Peso"):
        executar_sql("INSERT INTO public.peso (data, peso_kg) VALUES (%s, %s)", (get_now_br().date(), float(p_val)))
        st.rerun()
    df_p = executar_sql("SELECT * FROM public.peso ORDER BY data ASC", is_select=True)
    if not df_p.empty:
        df_p['data_str'] = pd.to_datetime(df_p['data']).dt.strftime('%d/%m')
        st.line_chart(df_p, x='data_str', y='peso_kg')

# --- ABA 6: ADMIN (RESTAURADA E MELHORADA) ---
with tab_admin:
    st.subheader("⚙️ Configurações de Administrador")
    
    st.divider()
    st.write("### 🛠️ Corretor de Fuso Horário")
    st.info("Use isto se seus registros estiverem caindo no dia seguinte ou anterior.")

    hoje_br = get_now_br().date()
    amanha_br = hoje_br + timedelta(days=1)
    ontem_br = hoje_br - timedelta(days=1)

    c1, c2 = st.columns(2)
    
    with c1:
        if st.button("⏪ Mover de AMANHÃ para HOJE"):
            # Move registros que estão com data de amanhã para a data de hoje real
            sql_fix = "UPDATE public.consumo SET data = %s WHERE data = %s"
            if executar_sql(sql_fix, (hoje_br, amanha_br)):
                st.success(f"Registros de {amanha_br} movidos para {hoje_br}!")
                st.rerun()
                
    with c2:
        if st.button("⏩ Mover de ONTEM para HOJE"):
            sql_fix = "UPDATE public.consumo SET data = %s WHERE data = %s"
            if executar_sql(sql_fix, (hoje_br, ontem_br)):
                st.success(f"Registros de {ontem_br} movidos para {hoje_br}!")
                st.rerun()

    st.warning("Zona de Perigo")
    if st.button("🗑️ Limpar TODAS as datas futuras"):
        executar_sql("UPDATE public.consumo SET data = %s WHERE data > %s", (hoje_br, hoje_br))
        st.success("Datas futuras trazidas para hoje.")
        st.rerun()
