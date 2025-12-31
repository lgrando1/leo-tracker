import pandas as pd
import psycopg2
import streamlit as st

# Conexão usando seus Secrets
conn = psycopg2.connect(st.secrets["DATABASE_URL"])
cur = conn.cursor()

def limpar_valor(valor):
    """Converte valores da TACO (NA, Tr, etc) para número"""
    if pd.isna(valor) or str(valor).strip().upper() == 'NA' or str(valor).strip().upper() == 'TR':
        return 0.0
    try:
        # Substitui vírgula por ponto se necessário
        return float(str(valor).replace(',', '.'))
    except:
        return 0.0

def carregar_taco_do_csv():
    st.info("Lendo arquivo CSV...")
    # Lendo o arquivo enviado (ajustado para o delimitador ';' da TACO)
    df = pd.read_csv('alimentos.csv', encoding='latin-1', sep=';')
    
    st.info("Limpando dados...")
    # Mapeando e limpando as colunas necessárias
    tabela_limpa = []
    for _, row in df.iterrows():
        tabela_limpa.append((
            str(row['Descrição dos alimentos']),
            limpar_valor(row['Energia (kcal)']),
            limpar_valor(row['Proteína (g)']),
            limpar_valor(row['Carboidrato (g)']),
            limpar_valor(row['Lipídeos (g)'])
        ))

    st.warning("Limpando banco de dados atual...")
    cur.execute("TRUNCATE TABLE tabela_taco")
    
    st.info(f"Inserindo {len(tabela_limpa)} alimentos no Neon...")
    cur.executemany(
        "INSERT INTO tabela_taco (alimento, kcal, proteina, carbo, gordura) VALUES (%s, %s, %s, %s, %s)", 
        tabela_limpa
    )
    
    conn.commit()
    cur.close()
    conn.close()
    st.success("✅ Sucesso! A tabela TACO completa foi carregada no seu banco de dados.")

st.title("🚀 Carga de Dados TACO via CSV")
if st.button("Iniciar Processamento do CSV"):
    carregar_taco_do_csv()
