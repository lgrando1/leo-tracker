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
    st.subheader("📋 Estratégia: Detox Gástrico & Anti-inflamatório")
    st.markdown("Foco: Recuperar a mucosa do estômago, digestão facilitada e zero glúten.")

    # --- CAFÉ DA MANHÃ ---
    with st.expander("☕ Café da Manhã (Proteção & Digestão)", expanded=True):
        c1, c2 = st.columns(2)
        with c1:
            st.info("💎 **Original**")
            st.markdown("""
            * **Prot:** Whey Protein (17g)
            * **Fruta:** Morango ou Mamão Papaia
            * **Fibra:** Chia ou Linhaça Dourada
            * **Líquido:** Leite ou Água
            """)
        with c2:
            st.success("💰 **Econômica (Detox)**")
            st.markdown("""
            * **Prot:** 3 Ovos (Cozidos ou mexidos sem gordura). A clara é rica em albumina (cicatrizante).
            * **Fruta:** **Mamão Formosa** (Mais barato e rico em papaína, que ajuda a digerir proteínas).
            * **Fibra:** **Linhaça Marrom Hidratada** (Deixe na água à noite. O "gel" que forma reveste e protege o estômago).
            * **Líquido:** Chá de Espinheira Santa ou Camomila (Morno).
            """)

    # --- ALMOÇO ---
    with st.expander("🥗 Almoço (Leve & Cozido)"):
        c1, c2 = st.columns(2)
        with c1:
            st.info("💎 **Original**")
            st.markdown("""
            * **Prot:** Salmão ou Sardinha
            * **Carbo:** Quinoa ou Mandioquinha
            * **Vegetal:** Espinafre ou Couve
            """)
        with c2:
            st.success("💰 **Econômica (Detox)**")
            st.markdown("""
            * **Prot:** **Sardinha** (Ômega-3 desinflama) ou Peito de Frango desfiado/moído.
            * **Carbo:** **Arroz bem cozido ("unidos")**. Evite grãos integrais duros agora. Se tolerar, caldo de feijão.
            * **Vegetal:** **Chuchu, Cenoura ou Abobrinha cozidos**. Evite folhas cruas e duras por enquanto.
            """)

    # --- LANCHE ---
    with st.expander("🍎 Lanche da Tarde (Cicatrizante)"):
        c1, c2 = st.columns(2)
        with c1:
            st.info("💎 **Original**")
            st.markdown("""
            * **Fruta:** Pera ou Morango
            * **Gordura:** Castanha do Pará
            """)
        with c2:
            st.success("💰 **Econômica (Detox)**")
            st.markdown("""
            * **Fruta:** **Maçã Cozida com Canela**. (A pectina da maçã cozida é excelente para "acalmar" o estômago).
            * **Gordura:** Sementes de Girassol (sem sal) ou apenas o azeite da refeição principal.
            """)

    # --- JANTAR ---
    with st.expander("Moon Jantar (Consistência Pastosa)"):
        c1, c2 = st.columns(2)
        with c1:
            st.info("💎 **Original**")
            st.markdown("""
            * **Prot:** Filé Mignon ou Alcatra
            * **Carbo:** Batata Sauté ou Inhame
            * **Vegetal:** Brócolis ou Shimeji
            """)
        with c2:
            st.success("💰 **Econômica (Detox)**")
            st.markdown("""
            * **Prot:** Carne Moída magra (Patinho/Acém) ou Omelete. Carnes fibrosas dificultam a digestão.
            * **Carbo:** **Purê** de Batata, Mandioca ou Abóbora. A textura de purê facilita muito o trabalho gástrico.
            * **Vegetal:** Vegetais cozidos no vapor até ficarem bem macios.
            """)

    # --- CEIA ---
    with st.expander("🌙 Ceia (Reparação Noturna)"):
        c1, c2 = st.columns(2)
        with c1:
            st.info("💎 **Original**")
            st.markdown("""
            * **Base:** Iogurte Proteico
            * **Extra:** Pipoca ou Bolacha de Arroz
            """)
        with c2:
            st.success("💰 **Econômica (Detox)**")
            st.markdown("""
            * **Base:** Iogurte Natural (Probióticos para o intestino).
            * **Extra:** **Gelatina Incolor** (Rica em glicina, ajuda na parede do estômago) ou Fruta cozida.
            * **Obs:** Evite pipoca nesta fase (a casca do milho pode irritar a inflamação).
            """)

    st.markdown("---")
    st.warning("⚠️ **Biohacking Gástrico:** Mastigue até o alimento virar líquido na boca. Evite beber líquidos 30min antes e depois de comer para não diluir o suco gástrico.")

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
