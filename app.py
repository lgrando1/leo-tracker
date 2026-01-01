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
            # Garante esquema public e fuso horário correto na sessão do banco
            cur.execute("SET search_path TO public")
            cur.execute("SET timezone TO 'America/Sao_Paulo'")
            
            if is_select:
                if params: return pd.read_sql(sql, conn, params=params)
                else: return pd.read_sql(sql, conn)
            else:
                cur.execute(sql, params)
                conn.commit()
                return True

    except (InterfaceError, OperationalError) as e:
        st.cache_resource.clear()
        try:
            conn = get_connection_raw()
            with conn.cursor() as cur:
                cur.execute("SET search_path TO public")
                cur.execute("SET timezone TO 'America/Sao_Paulo'")
                if is_select:
                    if params: return pd.read_sql(sql, conn, params=params)
                    else: return pd.read_sql(sql, conn)
                else:
                    cur.execute(sql, params)
                    conn.commit()
                    return True
        except Exception as e2:
            st.error(f"Erro fatal de conexão: {e2}")
            return pd.DataFrame() if is_select else False

    except Exception as e:
        if conn: conn.rollback()
        st.error(f"Erro na operação: {e}")
        return pd.DataFrame() if is_select else False

# 3. METAS
META_KCAL = 1600
META_PROTEINA = 150

# 4. FUNÇÕES DE BANCO
def inicializar_banco():
    executar_sql("""
        CREATE TABLE IF NOT EXISTS public.tabela_taco (
            id SERIAL PRIMARY KEY, alimento TEXT, kcal REAL, proteina REAL, carbo REAL, gordura REAL
        );
    """)
    executar_sql("""
        CREATE TABLE IF NOT EXISTS public.consumo (
            id SERIAL PRIMARY KEY, data DATE, alimento TEXT, quantidade REAL, kcal REAL, proteina REAL, carbo REAL, gordura REAL, gluten TEXT DEFAULT 'Não informado'
        );
    """)
    executar_sql("""
        DO $$ 
        BEGIN 
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='consumo' AND column_name='gluten') THEN
                ALTER TABLE public.consumo ADD COLUMN gluten TEXT DEFAULT 'Não informado';
            END IF;
        END $$;
    """)
    executar_sql("""
        CREATE TABLE IF NOT EXISTS public.peso (
            id SERIAL PRIMARY KEY, data DATE, peso_kg REAL
        );
    """)

def carregar_csv_completo():
    if not os.path.exists('alimentos.csv'): return False
    try:
        df = pd.read_csv('alimentos.csv', sep=';', encoding='latin-1')
        conn = get_connection_raw()
        cur = conn.cursor()
        cur.execute("TRUNCATE TABLE public.tabela_taco")
        
        for _, row in df.iterrows():
            val = lambda x: float(str(x).replace(',', '.')) if str(x).strip() not in ['NA', 'TR', '', '-'] else 0.0
            cur.execute(
                "INSERT INTO public.tabela_taco (alimento, kcal, proteina, carbo, gordura) VALUES (%s, %s, %s, %s, %s)",
                (str(row.iloc[2]), val(row.iloc[4]), val(row.iloc[6]), val(row.iloc[9]), val(row.iloc[7]))
            )
        conn.commit()
        return True
    except:
        st.cache_resource.clear()
        return False

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
    st.divider()

    termo = st.text_input("🔍 Pesquisar alimento (ex: banana):")
    if termo:
        df_res = executar_sql("SELECT * FROM public.tabela_taco WHERE alimento ILIKE %s ORDER BY alimento ASC LIMIT 50", (f'%{termo}%',), is_select=True)
        if not df_res.empty:
            escolha = st.selectbox("Selecione:", df_res["alimento"])
            dados = df_res[df_res["alimento"] == escolha].iloc[0]
            
            qtd = st.number_input("Peso (g):", 0, 2000, 100)
            fator = float(qtd) / 100.0
            
            k = float(round(float(dados['kcal']) * fator))
            p = float(round(float(dados['proteina']) * fator, 1))
            c = float(round(float(dados['carbo']) * fator, 1))
            g = float(round(float(dados['gordura']) * fator, 1))
            
            st.info(f"🥘 {k} kcal | P: {p}g | C: {c}g")
            
            if st.button("Confirmar Refeição"):
                sucesso = executar_sql("""
                    INSERT INTO public.consumo (data, alimento, quantidade, kcal, proteina, carbo, gordura, gluten) 
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                """, (get_now_br().date(), str(escolha), float(qtd), k, p, c, g, "Não informado"))
                
                if sucesso:
                    st.success("Registrado!")
                    st.rerun()

# --- ABA 2: IMPORTAR DA IA ---
with tab_ia:
    st.subheader("Importar JSON da IA")
    st.info("**Prompt:** Analise minha refeição (2000kcal/160g prot): [O QUE COMEU]. Retorne apenas o JSON: `[{\"alimento\": \"nome\", \"kcal\": 0, \"p\": 0, \"c\": 0, \"g\": 0, \"gluten\": \"...\"}]`")
    json_input = st.text_area("JSON:", height=150)
    
    if st.button("Processar JSON"):
        if json_input:
            try:
                limpo = json_input.replace('```json', '').replace('```', '').strip()
                dados_ia = json.loads(limpo)
                for item in dados_ia:
                    gluten_status = item.get('gluten', 'Não informado')
                    executar_sql("""
                        INSERT INTO public.consumo (data, alimento, quantidade, kcal, proteina, carbo, gordura, gluten) 
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                    """, (get_now_br().date(), item['alimento'], 1.0, float(item['kcal']), float(item['p']), float(item['c']), float(item['g']), gluten_status))
                st.success("Importação concluída!")
                st.rerun()
            except Exception as e:
                st.error(f"Erro no JSON: {e}")

# --- ABA 3: PLANO ---
with tab_plano:
    st.header("📋 Plano Alimentar & Estratégia")
    
    c_info, c_warn = st.columns(2)
    with c_info:
        st.info(f"**Foco da Dieta:**\n{nutrition_data['contexto_nutricional']['dieta']}")
    with c_warn:
        st.warning(f"**Atenção Farmacológica:**\n{nutrition_data['contexto_nutricional']['atencao_farmacologica']}")
        
    st.markdown("### 💊 Suplementação Atual (Ativos)")
    st.write(", ".join(nutrition_data['contexto_nutricional']['suplementacao_ativos']))
    
    st.divider()
    
    st.subheader("🔄 Substituições Inteligentes")
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("#### 🚫 Substitutos de Glúten")
        for item in nutrition_data['substitutos']['farinhas_espessantes']:
            st.markdown(f"- {item}")
    with col2:
        st.markdown("#### 🧠 Fontes Triptofano/GABA")
        for item in nutrition_data['substitutos']['fontes_triptofano_gaba']:
            st.markdown(f"- {item}")

    st.divider()

    st.subheader("📋 Estratégia Nutricional: Premium vs. Econômica")
    
    with st.expander("☕ Café da Manhã (Shake/Sólido)", expanded=True):
        c1, c2 = st.columns(2)
        with c1:
            st.info("💎 **Original (PDF)**")
            st.markdown("* **Prot:** Whey Protein (17g)\n* **Fruta:** Morango (200g)\n* **Gordura:** Chia/Linhaça\n* **Líquido:** Leite/Água")
        with c2:
            st.success("💰 **Opção Econômica**")
            st.markdown("* **Prot:** 3 Ovos\n* **Fruta:** Banana/Maçã\n* **Gordura:** Farelo de Aveia\n* **Líquido:** Água/Chá")

    with st.expander("🥗 Almoço (Refeição Principal)"):
        c1, c2 = st.columns(2)
        with c1:
            st.info("💎 **Original (PDF)**")
            st.markdown("* **Prot:** Salmão/Atum\n* **Carbo:** Quinoa/Mandioquinha\n* **Vegetal:** Espinafre\n* **Legume:** Lentilha")
        with c2:
            st.success("💰 **Opção Econômica**")
            st.markdown("* **Prot:** Sardinha/Frango\n* **Carbo:** Arroz e Feijão\n* **Vegetal:** Repolho/Abobrinha\n* **Legume:** Feijão comum")

    st.divider()

    st.subheader("🤖 Prompts para Copiar")
    with st.expander("1. Prompt: Encontrar Substituição"):
        st.code(nutrition_data['prompts_ia']['encontrar_substituicao'], language="text")
    with st.expander("2. Prompt: Avaliar Segurança"):
        st.code(nutrition_data['prompts_ia']['avaliar_alimento'], language="text")

# --- ABA 4: HISTÓRICO ---
with tab_hist:
    st.subheader("Últimos 7 dias")
    agora_br = get_now_br()
    data_limite = (agora_br - timedelta(days=7)).date()
    df_hist = executar_sql("SELECT * FROM public.consumo WHERE data >= %s ORDER BY data DESC, id DESC", (data_limite,), is_select=True)
    
    if not df_hist.empty:
        for i, row in df_hist.iterrows():
            c1, c2, c3 = st.columns([3, 2, 0.5])
            gl_tag = "🚫" if row['gluten'] == "Contém" else ""
            c1.write(f"**{row['alimento']}**")
            c2.write(f"{int(row['kcal'])} kcal {gl_tag}")
            if c3.button("🗑️", key=f"d_{row['id']}"):
                executar_sql("DELETE FROM public.consumo WHERE id = %s", (row['id'],))
                st.rerun()

# --- ABA 5: PESO ---
with tab_peso:
    c1, c2 = st.columns([1,2])
    with c1:
        p_val = st.number_input("Peso (kg):", 40.0, 200.0, 145.0)
        if st.button("Gravar Peso"):
            executar_sql("INSERT INTO public.peso (data, peso_kg) VALUES (%s, %s)", (get_now_br().date(), float(p_val)))
            st.rerun()
    with c2:
        df_p = executar_sql("SELECT * FROM public.peso ORDER BY data DESC", is_select=True)
        if not df_p.empty:
            st.line_chart(df_p.set_index('data'))
            st.dataframe(df_p)

# --- ABA 6: ADMIN ---
with tab_admin:
    if st.button("Sincronizar CSV"):
        if carregar_csv_completo():
            st.success("Feito!")
            st.rerun()
