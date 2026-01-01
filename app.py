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

# --- DADOS NUTRICIONAIS E PROMPTS ---
nutrition_data = {
    "contexto_nutricional": {
        "dieta": "Restrição ao Glúten (foco auxiliar no controle da ansiedade).",
        "suplementacao_ativos": ["L-teanina", "Griffonia simplicifolia (5-HTP)", "L-triptofano", "GABA"],
        "atencao_farmacologica": "Considerar interação com o uso contínuo de Bupropiona."
    },
    "prompts_ia": {
        "encontrar_substituicao": (
            "Estou seguindo uma dieta estrita **sem glúten** e focada em alimentos anti-inflamatórios.\n"
            "Receita original: [NOME DA RECEITA] com [INGREDIENTE COM GLÚTEN].\n\n"
            "Liste 3 substituições sem glúten que mantenham a textura e sejam baratas."
        ),
        "avaliar_alimento": (
            "Atue como nutricionista (foco em saúde mental/sem glúten).\n"
            "Alimento: [NOME/INGREDIENTES]\n\n"
            "1. Tem glúten?\n2. Interage com Bupropiona?\n3. Nota de segurança (0-10)."
        )
    }
}

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
                # Garante que colunas de data sejam datetime objects reais
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
META_KCAL = 1600
META_PROTEINA = 150 
META_PESO = 120.0
PERDA_SEMANAL_KG = 0.8 # Ritmo saudável e "adequado"

# 4. INICIALIZAÇÃO DAS TABELAS
def inicializar_banco():
    queries = [
        "CREATE TABLE IF NOT EXISTS public.consumo (id SERIAL PRIMARY KEY, data DATE, alimento TEXT, quantidade REAL, kcal REAL, proteina REAL, carbo REAL, gordura REAL, gluten TEXT DEFAULT 'Não informado');",
        "CREATE TABLE IF NOT EXISTS public.peso (id SERIAL PRIMARY KEY, data DATE, peso_kg REAL);",
        "CREATE TABLE IF NOT EXISTS public.tabela_taco (id SERIAL PRIMARY KEY, alimento TEXT, kcal REAL, proteina REAL, carbo REAL, gordura REAL);"
    ]
    for q in queries: executar_sql(q)

inicializar_banco()

# 5. INTERFACE DO APP
st.title("🦁 Leo Tracker Pro")
st.markdown(f"**Data Atual (BR):** {get_now_br().strftime('%d/%m/%Y %H:%M')}")

tab_prato, tab_ia, tab_plano, tab_hist, tab_peso, tab_admin, tab_prompts = st.tabs(["🍽️ Registrar", "🤖 Importar IA", "📝 Plano", "📊 Gráficos & Metas", "⚖️ Peso (120kg)", "⚙️ Admin", "💡 Prompts"])

# --- ABA 1: REGISTRO MANUAL ---
with tab_prato:
    st.subheader("Resumo do Dia")
    
    data_hoje = get_now_br().date()
    df_hoje = executar_sql("SELECT * FROM public.consumo WHERE data = %s", (data_hoje,), is_select=True)
    
    kcal_hoje = float(df_hoje['kcal'].sum()) if not df_hoje.empty else 0.0
    prot_hoje = float(df_hoje['proteina'].sum()) if not df_hoje.empty else 0.0
    
    c1, c2, c3 = st.columns(3)
    c1.metric("Kcal", f"{int(kcal_hoje)}", f"Meta: {META_KCAL}")
    c2.metric("Proteína", f"{int(prot_hoje)}g", f"Meta: {META_PROTEINA}g")
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
            
            if col_btn.button("✅ Registrar"):
                fator = float(qtd) / 100.0
                executar_sql(
                    """INSERT INTO public.consumo (data, alimento, quantidade, kcal, proteina, carbo, gordura, gluten) 
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""", 
                    (data_hoje, str(escolha), float(qtd), float(round(dados['kcal']*fator)), float(round(dados['proteina']*fator, 1)), float(round(dados['carbo']*fator, 1)), float(round(dados['gordura']*fator, 1)), "Não informado")
                )
                st.success("Registrado!")
                st.rerun()
        else:
            st.warning("Não encontrado na base.")
            with st.expander("Registrar Manualmente"):
                nm_man = st.text_input("Nome:")
                kc_man = st.number_input("Kcal:", 0, 2000)
                pt_man = st.number_input("Proteína (g):", 0, 200)
                if st.button("Salvar Manual"):
                     executar_sql("INSERT INTO public.consumo (data, alimento, quantidade, kcal, proteina, carbo, gordura) VALUES (%s, %s, 1, %s, %s, 0, 0)", 
                                  (data_hoje, nm_man, kc_man, pt_man))
                     st.rerun()

# --- ABA 2: IMPORTAR JSON (IA) ---
with tab_ia:
    st.header("🤖 Importação Inteligente")
    st.markdown("**Copie este prompt para o Gemini:**")
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
    
    if st.button("Processar JSON"):
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

# --- ABA 4: HISTÓRICO E GRÁFICOS (MODIFICADA) ---
with tab_hist:
    st.subheader("📊 Performance Diária vs. Metas")
    
    dt_inicio = (get_now_br() - timedelta(days=14)).date() # Últimos 14 dias
    sql_chart = """
        SELECT data, SUM(kcal) as kcal, SUM(proteina) as proteina 
        FROM public.consumo 
        WHERE data >= %s 
        GROUP BY data 
        ORDER BY data ASC
    """
    df_chart = executar_sql(sql_chart, (dt_inicio,), is_select=True)
    
    if not df_chart.empty:
        # Garante ordenação cronológica pelo objeto datetime
        df_chart = df_chart.sort_values(by='data')
        
        # Cria colunas de Metas para aparecerem no gráfico
        df_chart['Meta Kcal'] = META_KCAL
        df_chart['Meta Proteína'] = META_PROTEINA
        
        # Formata o índice para exibição bonita, mas mantendo a ordem dos dados
        df_chart.set_index('data', inplace=True)
        
        c_graf1, c_graf2 = st.columns(2)
        
        with c_graf1:
            st.markdown("#### 🔥 Calorias (Meta: 1600)")
            # Plota Consumido vs Meta
            st.line_chart(df_chart[['kcal', 'Meta Kcal']], color=["#FF4B4B", "#00FF00"]) # Vermelho consumo, Verde meta
            
        with c_graf2:
            st.markdown("#### 🥩 Proteínas (Meta: 150g)")
            st.line_chart(df_chart[['proteina', 'Meta Proteína']], color=["#3366CC", "#00FF00"]) # Azul consumo, Verde meta

    else:
        st.info("Ainda não há dados suficientes para gráficos.")
    
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

# --- ABA 5: PESO E PROJEÇÃO (MODIFICADA) ---
with tab_peso:
    st.subheader(f"⚖️ Rumo aos {int(META_PESO)}kg")
    
    c_input, c_meta = st.columns([2, 1])
    p_val = c_input.number_input("Registrar Peso Atual (kg):", 40.0, 200.0, step=0.1)
    
    if c_input.button("Gravar Peso"):
        executar_sql("INSERT INTO public.peso (data, peso_kg) VALUES (%s, %s)", (get_now_br().date(), float(p_val)))
        st.success("Peso registrado!")
        st.rerun()

    # Recupera histórico
    df_p = executar_sql("SELECT * FROM public.peso ORDER BY data ASC", is_select=True)
    
    if not df_p.empty and len(df_p) > 0:
        df_p['data'] = pd.to_datetime(df_p['data'])
        df_p = df_p.sort_values('data') # Garante ordem
        
        # --- LÓGICA DE PROJEÇÃO "TEMPO ADEQUADO" ---
        # Pega o primeiro registro para traçar a linha ideal a partir de lá
        data_inicial = df_p['data'].iloc[0]
        peso_inicial = df_p['peso_kg'].iloc[0]
        
        # Calcula quantos dias passaram desde o início até hoje (ou último registro)
        ultimo_dia = df_p['data'].iloc[-1]
        dias_totais = (ultimo_dia - data_inicial).days + 30 # +30 dias para ver o futuro
        
        # Cria uma linha de "Meta Saudável" que cai 0.8kg por semana (aprox 0.11kg por dia)
        lista_datas_meta = [data_inicial + timedelta(days=x) for x in range(dias_totais)]
        lista_pesos_meta = [max(META_PESO, peso_inicial - (x * (PERDA_SEMANAL_KG/7))) for x in range(dias_totais)]
        
        df_meta = pd.DataFrame({'data': lista_datas_meta, 'Plano Saudável': lista_pesos_meta})
        df_meta.set_index('data', inplace=True)
        
        # Junta os dados reais com a meta
        df_p.set_index('data', inplace=True)
        df_combined = df_p[['peso_kg']].rename(columns={'peso_kg': 'Peso Real'})
        
        # Plota combinado (Peso Real vs Plano)
        st.line_chart(df_combined.join(df_meta, how='outer'), color=["#0000FF", "#AAAAAA"]) # Azul Real, Cinza Meta
        
        st.info(f"A linha cinza mostra o caminho ideal perdendo {PERDA_SEMANAL_KG}kg por semana até chegar a {int(META_PESO)}kg.")
    else:
        st.info("Registre seu peso hoje para começar a ver o gráfico de projeção.")

# --- ABA 6: ADMIN ---
with tab_admin:
    st.write("### 🛠️ Corretor de Fuso")
    hoje = get_now_br().date()
    c1, c2 = st.columns(2)
    if c1.button("⏪ Mover AMANHÃ -> HOJE"):
        executar_sql("UPDATE public.consumo SET data = %s WHERE data = %s", (hoje, hoje + timedelta(days=1)))
        st.success("Feito!")
        st.rerun()
    if c2.button("⏩ Mover ONTEM -> HOJE"):
        executar_sql("UPDATE public.consumo SET data = %s WHERE data = %s", (hoje, hoje - timedelta(days=1)))
        st.success("Feito!")
        st.rerun()

# --- ABA 7: PROMPTS ---
with tab_prompts:
    st.subheader("1. Substituição")
    st.code(nutrition_data['prompts_ia']['encontrar_substituicao'], language="markdown")
    st.subheader("2. Avaliação")
    st.code(nutrition_data['prompts_ia']['avaliar_alimento'], language="markdown")
