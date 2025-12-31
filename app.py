import streamlit as st
import pandas as pd
import psycopg2
from datetime import datetime, timedelta
import plotly.express as px
import plotly.graph_objects as go
import json
from contextlib import contextmanager

# 1. CONFIGURAÇÃO DA PÁGINA
st.set_page_config(page_title="Leo Tracker Pro", page_icon="🦁", layout="wide")

# --- SISTEMA DE LOGIN ---
def check_password():
    if "password_correct" not in st.session_state:
        st.session_state["password_correct"] = False
    if st.session_state["password_correct"]: return True
    st.title("🦁 Leo Tracker Login")
    password = st.text_input("Senha de acesso:", type="password")
    if st.button("Entrar"):
        if password == st.secrets["PASSWORD"]:
            st.session_state["password_correct"] = True
            st.rerun()
        else: st.error("Senha incorreta!")
    return False

if not check_password(): st.stop()

# 2. GERENCIAMENTO DE CONEXÃO (BIOHACKER AUTO-RECONNECT)
@st.cache_resource
def init_connection():
    return psycopg2.connect(st.secrets["DATABASE_URL"])

def get_connection():
    try:
        conn = init_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
        return conn
    except:
        st.cache_resource.clear()
        return init_connection()

@contextmanager
def get_cursor():
    conn = get_connection()
    cur = conn.cursor()
    try:
        yield cur
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cur.close()

# 3. METAS E INICIALIZAÇÃO
META_KCAL = 2000 
META_PROT = 160  

def inicializar_banco():
    with get_cursor() as cur:
        cur.execute("SET search_path TO public")
        cur.execute("CREATE TABLE IF NOT EXISTS tabela_taco (id SERIAL PRIMARY KEY, alimento TEXT, kcal REAL, proteina REAL, carbo REAL, gordura REAL);")
        cur.execute("""CREATE TABLE IF NOT EXISTS consumo (
            id SERIAL PRIMARY KEY, data_hora TIMESTAMP DEFAULT CURRENT_TIMESTAMP, 
            alimento TEXT, quantidade REAL, kcal REAL, proteina REAL, carbo REAL, gordura REAL, gluten TEXT DEFAULT 'Não informado'
        );""")
        cur.execute("CREATE TABLE IF NOT EXISTS peso (id SERIAL PRIMARY KEY, data DATE UNIQUE, peso_kg REAL);")

def limpar_valor_taco(valor):
    if pd.isna(valor) or str(valor).strip() in ['NA', 'TR', '', '*', '-']: return 0.0
    try: return float(str(valor).replace(',', '.'))
    except: return 0.0

try: inicializar_banco()
except Exception as e: st.error(f"Erro no banco: {e}"); st.stop()

# 5. INTERFACE
st.title("🦁 Leo Tracker Pro")
tabs = st.tabs(["🍽️ Registro", "🤖 IA Nutricional", "📈 Progresso", "📋 Plano & Sugestões", "⚖️ Peso & Admin"])

with tabs[0]:
    st.subheader("Busca Manual (TACO)")
    termo = st.text_input("🔍 Pesquisar alimento:")
    if termo:
        conn = get_connection()
        df_res = pd.read_sql("SELECT * FROM public.tabela_taco WHERE alimento ILIKE %s LIMIT 50", conn, params=(f'%{termo}%',))
        if not df_res.empty:
            escolha = st.selectbox("Selecione:", df_res["alimento"])
            dados = df_res[df_res["alimento"] == escolha].iloc[0]
            qtd = st.number_input("Gramas:", 0, 2000, 100)
            f = float(qtd) / 100.0
            if st.button("Salvar Alimento"):
                with get_cursor() as cur:
                    cur.execute("INSERT INTO consumo (alimento, quantidade, kcal, proteina, carbo, gordura) VALUES (%s,%s,%s,%s,%s,%s)", 
                                (escolha, float(qtd), dados['kcal']*f, dados['proteina']*f, dados['carbo']*f, dados['gordura']*f))
                st.success("Registrado!"); st.rerun()

with tabs[1]:
    st.subheader("🤖 Importar via IA")
    st.info("**Prompt:** Analise minha refeição (2000kcal/160g prot): [O QUE COMEU]. Retorne apenas o JSON: `[{\"alimento\": \"nome\", \"kcal\": 0, \"p\": 0, \"c\": 0, \"g\": 0, \"gluten\": \"...\"}]`")
    json_in = st.text_area("Cole o JSON aqui:", height=150)
    if st.button("Processar e Salvar"):
        try:
            dados = json.loads(json_in.replace('```json', '').replace('```', '').strip())
            with get_cursor() as cur:
                for i in dados:
                    cur.execute("INSERT INTO consumo (alimento, quantidade, kcal, proteina, carbo, gordura, gluten) VALUES (%s,1,%s,%s,%s,%s,%s)", 
                                (i['alimento'], i['kcal'], i['p'], i['c'], i['g'], i.get('gluten','Não informado')))
            st.success("Importado!"); st.rerun()
        except Exception as e: st.error(f"Erro: {e}")

with tabs[2]:
    st.subheader("📊 Progresso do Dia")
    conn = get_connection()
    
    # --- AJUSTE DE FUSO HORÁRIO (FIX UTC-3) ---
    df_raw = pd.read_sql("SELECT * FROM consumo ORDER BY data_hora DESC LIMIT 100", conn)
    
    if not df_raw.empty:
        # Converte para datetime e subtrai 3 horas
        df_raw['data_hora'] = pd.to_datetime(df_raw['data_hora']) - pd.Timedelta(hours=3)
        
        # Filtra apenas o que é de HOJE
        df_hoje = df_raw[df_raw['data_hora'].dt.date == datetime.now().date()]
        
        if not df_hoje.empty:
            c1, c2 = st.columns(2)
            k, p = df_hoje['kcal'].sum(), df_hoje['proteina'].sum()
            c1.metric("Energia", f"{int(k)}/{META_KCAL} kcal", f"{int(k-META_KCAL)}")
            c2.metric("Proteína", f"{int(p)}/{META_PROT}g", f"{int(p-META_PROT)}g")
            
            with st.expander("Ver itens de hoje", expanded=True):
                for _, r in df_hoje.iterrows():
                    col_h1, col_h2, col_h3 = st.columns([1, 4, 1])
                    col_h1.write(r['data_hora'].strftime('%H:%M'))
                    col_h2.write(f"**{r['alimento']}** - {int(r['kcal'])} kcal")
                    # Este botão estava sendo duplicado lá embaixo, causando o erro
                    if col_h3.button("🗑️", key=f"del_{r['id']}"):
                        with get_cursor() as cur: cur.execute("DELETE FROM consumo WHERE id = %s", (r['id'],))
                        st.rerun()
        else:
            st.info("Nenhum registro para hoje (considerando horário local).")
    else:
        st.info("Banco de dados vazio.")

    st.divider()
    
    # --- GRÁFICO 30 DIAS ---
    st.subheader("📅 Histórico de Calorias (30 Dias)")
    try:
        df_hist_raw = pd.read_sql("SELECT data_hora, kcal FROM consumo", conn)
        
        if not df_hist_raw.empty:
            df_hist_raw['data_hora'] = pd.to_datetime(df_hist_raw['data_hora']) - pd.Timedelta(hours=3)
            df_hist_raw['data'] = df_hist_raw['data_hora'].dt.date
            df_chart = df_hist_raw.groupby('data')['kcal'].sum().reset_index().sort_values('data', ascending=False).head(30)
            df_chart = df_chart.sort_values('data') 
            
            fig_cal = px.bar(df_chart, x='data', y='kcal', title="Consumo Diário vs Meta", text_auto='.0f')
            fig_cal.add_hline(y=META_KCAL, line_dash="dot", annotation_text="Meta (2000)", line_color="red")
            fig_cal.update_traces(marker_color='#4CAF50')
            st.plotly_chart(fig_cal, use_container_width=True)
        else:
            st.caption("Sem dados históricos.")
    except Exception as e: st.error(f"Erro gráfico: {e}")

with tabs[3]:
    st.subheader("📋 Estratégia: Detox & Anti-inflamatória")
    st.markdown("Foco em recuperar a mucosa gástrica com alimentos de fácil digestão e baixo custo.")

    # --- CAFÉ DA MANHÃ ---
    with st.expander("☕ Café da Manhã (Foco: Proteção Gástrica)", expanded=True):
        c1, c2 = st.columns(2)
        with c1:
            st.info("💎 **Original (PDF)**")
            st.markdown("""
            * [cite_start]**Prot:** Whey Protein (17g) [cite: 18]
            * [cite_start]**Fruta:** Morango (200g) ou Mamão Papaia [cite: 7, 8]
            * [cite_start]**Fibra:** Chia (30g) ou Linhaça Dourada [cite: 11, 12]
            * [cite_start]**Líquido:** Leite Desnatado ou Água [cite: 16, 22]
            """)
        with c2:
            st.success("💰 **Econômica (Detox)**")
            st.markdown("""
            * **Prot:** 3 Ovos Cozidos (Clara é excelente, gema com moderação se houver azia).
            * **Fruta:** **Mamão Formosa** (Mais barato que o Papaia e rico em papaína, que ajuda na digestão).
            * **Fibra:** **Linhaça Marrom** (Deixe de molho antes: o gel que ela forma protege o estômago).
            * **Líquido:** Água ou Chá de Espinheira Santa.
            """)

    # --- ALMOÇO ---
    with st.expander("🥗 Almoço (Leve & Nutritivo)"):
        c1, c2 = st.columns(2)
        with c1:
            st.info("💎 **Original (PDF)**")
            st.markdown("""
            * [cite_start]**Prot:** Salmão (120g) ou Sardinha [cite: 36, 37]
            * [cite_start]**Carbo:** Quinoa (160g) ou Mandioquinha [cite: 42, 43]
            * [cite_start]**Vegetal:** Espinafre ou Couve Refogada [cite: 32, 33]
            """)
        with c2:
            st.success("💰 **Econômica (Detox)**")
            st.markdown("""
            * **Prot:** **Sardinha** (Rica em Ômega-3, o maior anti-inflamatório natural) ou Peito de Frango desfiado.
            * **Carbo:** **Arroz bem cozido + Caldo de Feijão** (Evitar o grão do feijão se tiver gases).
            * **Vegetal:** Abobrinha ou Chuchu cozidos (Fáceis de digerir).
            """)

    # --- LANCHE ---
    with st.expander("🍎 Lanche da Tarde"):
        c1, c2 = st.columns(2)
        with c1:
            st.info("💎 **Original (PDF)**")
            st.markdown("""
            * [cite_start]**Fruta:** Pera Willians ou Morango [cite: 50, 51]
            * [cite_start]**Gordura:** Castanha do Pará [cite: 52]
            """)
        with c2:
            st.success("💰 **Econômica (Detox)**")
            st.markdown("""
            * **Fruta:** Maçã cozida com canela (Pura "medicina" para o estômago).
            * **Gordura:** Sementes de Girassol ou Abóbora (Baratas na zona cerealista).
            """)

    # --- JANTAR ---
    with st.expander("Moon Jantar (Fácil Digestão)"):
        c1, c2 = st.columns(2)
        with c1:
            st.info("💎 **Original (PDF)**")
            st.markdown("""
            * [cite_start]**Prot:** Filé Mignon ou Alcatra [cite: 63, 64]
            * [cite_start]**Carbo:** Batata Sauté ou Inhame [cite: 66, 68]
            * [cite_start]**Vegetal:** Brócolis ou Couve-flor [cite: 59, 60]
            """)
        with c2:
            st.success("💰 **Econômica (Detox)**")
            st.markdown("""
            * **Prot:** Carne Moída (Patinho ou Acém magro) ou Omelete.
            * **Carbo:** **Purê de Batata ou Mandioca** (A consistência pastosa facilita o trabalho do estômago).
            * **Vegetal:** Cenoura cozida.
            """)

    # --- CEIA ---
    with st.expander("🌙 Ceia"):
        c1, c2 = st.columns(2)
        with c1:
            st.info("💎 **Original (PDF)**")
            st.markdown("""
            * [cite_start]**Base:** Iogurte Natural [cite: 75]
            * [cite_start]**Extra:** Pipoca sem óleo ou Bolacha de Arroz [cite: 71, 74]
            """)
        with c2:
            st.success("💰 **Econômica (Detox)**")
            st.markdown("""
            * **Base:** Iogurte Natural Caseiro (Probióticos recuperam o intestino).
            * **Extra:** Gelatina incolor (Colágeno ajuda na mucosa) ou fruta cozida. Evitar pipoca se estiver com gastrite (casca dura).
            """)

    st.markdown("---")
    st.warning("⚠️ **Dica de Biohacker:** Para desinflamar, evite líquidos junto com a comida e mastigue até virar pasta. A digestão começa na boca!")

with tabs[4]:
    st.subheader("⚖️ Peso & Admin")
    p_v = st.number_input("Peso hoje (kg):", 40.0, 250.0, 145.0)
    if st.button("Gravar Peso"):
        with get_cursor() as cur: cur.execute("INSERT INTO peso (data, peso_kg) VALUES (%s,%s) ON CONFLICT (data) DO UPDATE SET peso_kg=EXCLUDED.peso_kg", (datetime.now().date(), float(p_v)))
        st.success("Peso gravado!")
        st.rerun()
    
    st.divider()
    st.subheader("📉 Evolução do Peso")
    try:
        df_peso = pd.read_sql("SELECT * FROM peso ORDER BY data ASC", get_connection())
        if not df_peso.empty:
            fig_peso = px.line(df_peso, x='data', y='peso_kg', markers=True, title="Histórico de Peso")
            fig_peso.update_traces(line_color='#FF4B4B')
            st.plotly_chart(fig_peso, use_container_width=True)
        else:
            st.info("Registre seu peso para ver o gráfico.")
    except Exception as e: st.error(f"Erro ao carregar peso: {e}")

    st.divider()
    if st.button("🚀 Sincronizar TACO (Corrigir Acentos)"):
        try:
            try: df_csv = pd.read_csv('alimentos.csv', sep=';', encoding='utf-8')
            except: df_csv = pd.read_csv('alimentos.csv', sep=';', encoding='latin-1')
            
            preparada = []
            for _, r in df_csv.iterrows():
                nome_limpo = str(r.iloc[2]).strip()
                preparada.append((nome_limpo, limpar_valor_taco(r.iloc[4]), limpar_valor_taco(r.iloc[6]), limpar_valor_taco(r.iloc[9]), limpar_valor_taco(r.iloc[7])))
            
            with get_cursor() as cur:
                cur.execute("TRUNCATE TABLE tabela_taco")
                cur.executemany("INSERT INTO tabela_taco (alimento, kcal, proteina, carbo, gordura) VALUES (%s,%s,%s,%s,%s)", preparada)
            st.success(f"Sucesso! {len(preparada)} alimentos sincronizados.")
        except Exception as e: st.error(f"Erro CSV: {e}")
