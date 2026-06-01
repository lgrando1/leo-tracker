import streamlit as st
import pandas as pd
import numpy as np
import requests
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta
from sqlalchemy import create_engine

st.set_page_config(page_title="Impacto do Ciclismo", layout="wide")

st.title("Leo-Tracker: Observação Fisiológica Longitudinal")
st.markdown("Monitoramento de recomposição corporal, carga mecânica e nutrição.")

# ============================================================================
# 1. CONEXÕES E EXTRAÇÃO DE DADOS
# ============================================================================
@st.cache_data(ttl=3600)
def buscar_dados_intervals(dias=150):
    ath_id = st.secrets["intervals"]["ATHLETE_ID"]
    key = st.secrets["intervals"]["API_KEY"]
    inicio = (datetime.now() - timedelta(days=dias)).strftime('%Y-%m-%dT00:00:00')
    fim = datetime.now().strftime('%Y-%m-%dT23:59:59')
    url = f"https://intervals.icu/api/v1/athlete/{ath_id}/activities?oldest={inicio}&newest={fim}"
    
    try:
        res = requests.get(url, auth=("API_KEY", key))
        return res.json() if res.status_code == 200 else []
    except Exception:
        return []

@st.cache_data(ttl=3600)
def buscar_dados_neon(data_inicio='2025-12-30'):
    engine = create_engine(st.secrets["database"]["DATABASE_URL"])
    
    query_peso = f"SELECT data, peso_kg FROM peso WHERE peso_kg IS NOT NULL AND data >= '{data_inicio}' ORDER BY data ASC"
    query_medidas = f"SELECT log_date as data, waist_cm FROM body_measurements WHERE waist_cm IS NOT NULL AND log_date >= '{data_inicio}' ORDER BY log_date ASC"
    query_consumo = f"SELECT data, kcal, proteina, carbo, gordura FROM consumo WHERE data >= '{data_inicio}' ORDER BY data ASC"
    
    try:
        df_peso = pd.read_sql(query_peso, engine)
        df_medidas = pd.read_sql(query_medidas, engine)
        df_consumo = pd.read_sql(query_consumo, engine)
        
        df_peso['data'] = pd.to_datetime(df_peso['data']).dt.normalize()
        df_medidas['data'] = pd.to_datetime(df_medidas['data']).dt.normalize()
        df_consumo['data'] = pd.to_datetime(df_consumo['data']).dt.normalize()
        
        return df_peso, df_medidas, df_consumo
    except Exception as e:
        st.error(f"Erro ao conectar no Neon: {e}")
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

# ============================================================================
# 2. PROCESSAMENTO MATEMÁTICO E AGRUPAMENTO (Pandas)
# ============================================================================
dados_brutos = buscar_dados_intervals()
df_peso, df_medidas, df_consumo = buscar_dados_neon()

if not df_peso.empty:
    
    df_peso = df_peso.sort_values('data').drop_duplicates(subset=['data'], keep='last')
    peso_semanal = df_peso.set_index('data').resample('W-SUN', closed='left', label='left').agg(
        peso_medio=('peso_kg', 'mean'),
        peso_std=('peso_kg', 'std')
    ).reset_index()
    peso_semanal.rename(columns={'data': 'semana_dt', 'peso_medio': 'peso_kg'}, inplace=True)
    peso_semanal['perda_semanal_kg'] = peso_semanal['peso_kg'].diff() * -1
    peso_semanal['peso_std'] = peso_semanal['peso_std'].fillna(0)

    if not df_medidas.empty:
        df_medidas = df_medidas.sort_values('data').drop_duplicates(subset=['data'], keep='last')
        cintura_semanal = df_medidas.set_index('data').resample('W-SUN', closed='left', label='left').agg({'waist_cm': 'mean'}).reset_index()
        cintura_semanal['waist_cm'] = cintura_semanal['waist_cm'].interpolate(method='linear')
        cintura_semanal.rename(columns={'data': 'semana_dt'}, inplace=True)
    else:
        cintura_semanal = pd.DataFrame({'semana_dt': peso_semanal['semana_dt'], 'waist_cm': np.nan})

    if not df_consumo.empty:
        consumo_semanal = df_consumo.set_index('data').resample('W-SUN', closed='left', label='left').agg({
            'kcal': 'sum', 'proteina': 'sum', 'carbo': 'sum', 'gordura': 'sum'
        }).reset_index()
        consumo_semanal[['kcal', 'proteina', 'carbo', 'gordura']] = consumo_semanal[['kcal', 'proteina', 'carbo', 'gordura']] / 7
        consumo_semanal.rename(columns={'data': 'semana_dt'}, inplace=True)
    else:
        consumo_semanal = pd.DataFrame(columns=['semana_dt', 'kcal', 'proteina', 'carbo', 'gordura'])

    df_bike = pd.DataFrame(dados_brutos)
    primeiro_pedal = None
    if not df_bike.empty:
        df_bike = df_bike[df_bike['type'].isin(['Ride', 'VirtualRide'])].copy()
        df_bike['data'] = pd.to_datetime(df_bike['start_date_local']).dt.normalize()
        primeiro_pedal = df_bike['data'].min()
        
        df_bike['tss'] = df_bike['icu_training_load']
        df_bike['atl'] = df_bike['icu_atl']
        df_bike['ctl'] = df_bike['icu_ctl']
        df_bike['distancia_km'] = df_bike['distance'] / 1000
        df_bike['duracao_h'] = df_bike['moving_time'] / 3600
        df_bike['cadencia'] = df_bike['average_cadence']
        
        bike_semanal = df_bike.set_index('data').resample('W-SUN', closed='left', label='left').agg({
            'tss': 'sum', 'atl': 'last', 'ctl': 'last', 'distancia_km': 'sum', 'duracao_h': 'sum', 'cadencia': 'mean'
        }).reset_index()
        bike_semanal.rename(columns={'data': 'semana_dt'}, inplace=True)
        bike_semanal['tsb'] = bike_semanal['ctl'] - bike_semanal['atl']
    else:
        bike_semanal = pd.DataFrame(columns=['semana_dt', 'tss', 'atl', 'ctl', 'tsb', 'distancia_km', 'duracao_h', 'cadencia'])

    df_analise = pd.merge(peso_semanal, cintura_semanal, on='semana_dt', how='left')
    df_analise = pd.merge(df_analise, consumo_semanal, on='semana_dt', how='left')
    df_analise = pd.merge(df_analise, bike_semanal, on='semana_dt', how='left')
    
    colunas_esforco = ['tss', 'distancia_km', 'duracao_h', 'cadencia', 'kcal', 'proteina', 'carbo', 'gordura']
    df_analise[colunas_esforco] = df_analise[colunas_esforco].fillna(0)
    df_analise[['ctl', 'atl']] = df_analise[['ctl', 'atl']].ffill().fillna(0)
    df_analise['tsb'] = df_analise['ctl'] - df_analise['atl']
    df_analise['prot_kg_dia'] = df_analise['proteina'] / df_analise['peso_kg']
    df_analise['diario_contexto'] = "Sem registros."
    
    df_analise = df_analise.dropna(subset=['peso_kg']).sort_values('semana_dt').reset_index(drop=True)
    df_analise['semana_num'] = [i+1 for i in range(len(df_analise))]
    
    tickvals_full = df_analise['semana_dt']
    ticktext_full = [f"S{row['semana_num']}<br>{row['semana_dt'].strftime('%d/%m')}" for _, row in df_analise.iterrows()]

    df_bike_vis = df_analise[df_analise['semana_dt'] >= primeiro_pedal].copy() if primeiro_pedal else pd.DataFrame()
    if not df_bike_vis.empty:
        tickvals_bike = df_bike_vis['semana_dt']
        ticktext_bike = [f"S{row['semana_num']}<br>{row['semana_dt'].strftime('%d/%m')}" for _, row in df_bike_vis.iterrows()]

    # ============================================================================
    # 3. INTERFACE DE OBSERVAÇÃO E CARDS
    # ============================================================================
    st.divider()
    
    hoje = pd.Timestamp(datetime.now().date())
    ultima_semana_dt = df_analise['semana_dt'].iloc[-1]
    fim_ultima_semana = ultima_semana_dt + timedelta(days=6)
    
    if ultima_semana_dt <= hoje <= fim_ultima_semana:
        st.warning(f"Atenção: A Semana {df_analise['semana_num'].iloc[-1]} ({ultima_semana_dt.strftime('%d/%m')}) está em andamento. Os registros de carga, volume e nutrição representam uma fração do período e podem gerar distorções visuais.")

    peso_inicial = df_analise['peso_kg'].iloc[0]
    peso_atual = df_analise['peso_kg'].iloc[-1]
    delta_peso = peso_inicial - peso_atual

    cintura_inicial = df_analise['waist_cm'].dropna().iloc[0] if not df_analise['waist_cm'].dropna().empty else 0
    cintura_atual = df_analise['waist_cm'].iloc[-1] if not pd.isna(df_analise['waist_cm'].iloc[-1]) else 0
    delta_cintura = cintura_inicial - cintura_atual

    ctl_atual = df_analise['ctl'].iloc[-1]
    tsb_atual = df_analise['tsb'].iloc[-1]

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Peso Atual", f"{peso_atual:.1f} kg", f"-{delta_peso:.1f} kg desde o início", delta_color="inverse")
    col2.metric("Cintura Atual", f"{cintura_atual:.1f} cm", f"-{delta_cintura:.1f} cm" if delta_cintura > 0 else "0 cm", delta_color="inverse")
    col3.metric("Fitness Consolidado (CTL)", f"{ctl_atual:.0f}")
    
    if tsb_atual < -20:
        col4.metric("Prontidão (TSB)", f"{tsb_atual:.0f}", "Alta Fadiga Cumulativa", delta_color="inverse")
    elif tsb_atual > 10:
        col4.metric("Prontidão (TSB)", f"{tsb_atual:.0f}", "Destreinamento ou Repouso", delta_color="normal")
    else:
        col4.metric("Prontidão (TSB)", f"{tsb_atual:.0f}", "Fadiga Otimizada", delta_color="off")

    st.write("")

    # ============================================================================
    # 4. GRÁFICOS SEQUENCIAIS
    # ============================================================================
    
    st.markdown("### 1. Antropometria (Peso Médio e Cintura)")
    fig_corpo = make_subplots(specs=[[{"secondary_y": True}]])
    fig_corpo.add_trace(go.Scatter(x=df_analise['semana_dt'], y=df_analise['peso_kg'], name="Peso Médio (kg)", mode='lines+markers', line=dict(color='#ef4444', width=3)), secondary_y=False)
    fig_corpo.add_trace(go.Scatter(x=df_analise['semana_dt'], y=df_analise['waist_cm'], name="Cintura (cm)", mode='lines+markers', line=dict(color='#f59e0b', width=2, dash='dot')), secondary_y=True)
    fig_corpo.update_layout(height=400, template="plotly_dark", hovermode="x unified", margin=dict(t=30, b=10))
    fig_corpo.update_xaxes(tickmode='array', tickvals=tickvals_full, ticktext=ticktext_full, tickangle=0)
    fig_corpo.update_yaxes(title_text="Peso (kg)", secondary_y=False)
    fig_corpo.update_yaxes(title_text="Cintura (cm)", secondary_y=True)
    st.plotly_chart(fig_corpo, use_container_width=True)

    st.markdown("### 2. Dieta (Média de Ingestão Diária)")
    fig_dieta = make_subplots(specs=[[{"secondary_y": True}]])
    fig_dieta.add_trace(go.Bar(x=df_analise['semana_dt'], y=df_analise['proteina'], name="Prot/Dia (g)", marker_color='#3b82f6'), secondary_y=False)
    fig_dieta.add_trace(go.Bar(x=df_analise['semana_dt'], y=df_analise['carbo'], name="Carbo/Dia (g)", marker_color='#10b981'), secondary_y=False)
    fig_dieta.add_trace(go.Scatter(x=df_analise['semana_dt'], y=df_analise['kcal'], name="Kcal/Dia", mode='lines+markers', line=dict(color='#06b6d4', width=2)), secondary_y=True)
    fig_dieta.update_layout(height=400, template="plotly_dark", hovermode="x unified", barmode='stack', margin=dict(t=30, b=10))
    fig_dieta.update_xaxes(tickmode='array', tickvals=tickvals_full, ticktext=ticktext_full, tickangle=0)
    fig_dieta.update_yaxes(title_text="Macros Diários (g)", secondary_y=False)
    fig_dieta.update_yaxes(title_text="Kcal Diárias", secondary_y=True, showgrid=False)
    st.plotly_chart(fig_dieta, use_container_width=True)

    st.divider()

    if not df_bike_vis.empty:
        st.markdown("### 3. Carga e Balanço de Prontidão (PMC)")
        fig_pmc = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.7, 0.3], vertical_spacing=0.08)
        
        fig_pmc.add_trace(go.Bar(x=df_bike_vis['semana_dt'], y=df_bike_vis['tss'], name="TSS (Volume Semanal)", marker_color='#8b5cf6', opacity=0.4), row=1, col=1)
        fig_pmc.add_trace(go.Scatter(x=df_bike_vis['semana_dt'], y=df_bike_vis['ctl'], name="Fitness (CTL)", mode='lines', line=dict(color='#3b82f6', width=3)), row=1, col=1)
        fig_pmc.add_trace(go.Scatter(x=df_bike_vis['semana_dt'], y=df_bike_vis['atl'], name="Fadiga Aguda (ATL)", mode='lines', line=dict(color='#ec4899', width=2, dash='dot')), row=1, col=1)
        
        cores_tsb = ['#10b981' if t > 0 else '#ef4444' for t in df_bike_vis['tsb']]
        fig_pmc.add_trace(go.Bar(x=df_bike_vis['semana_dt'], y=df_bike_vis['tsb'], name="Prontidão (TSB)", marker_color=cores_tsb), row=2, col=1)
        fig_pmc.add_hrect(y0=-10, y1=5, fillcolor="#10b981", opacity=0.15, row=2, col=1, annotation_text="Zona Ideal", annotation_position="top left", annotation_font_color="white")
        
        fig_pmc.update_layout(height=500, template="plotly_dark", hovermode="x unified", margin=dict(t=30, b=10))
        fig_pmc.update_xaxes(tickmode='array', tickvals=tickvals_bike, ticktext=ticktext_bike, tickangle=0, row=2, col=1)
        fig_pmc.update_yaxes(title_text="Carga", row=1, col=1)
        fig_pmc.update_yaxes(title_text="TSB", row=2, col=1)
        st.plotly_chart(fig_pmc, use_container_width=True)

        st.markdown("### 4. Volume do Ciclismo e Eficiência Neuromuscular")
        fig_vol = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.7, 0.3], vertical_spacing=0.08, specs=[[{"secondary_y": True}], [{"secondary_y": False}]])
        
        fig_vol.add_trace(go.Bar(x=df_bike_vis['semana_dt'], y=df_bike_vis['duracao_h'], name="Tempo (Horas)", marker_color='#0ea5e9', opacity=0.5), row=1, col=1, secondary_y=True)
        fig_vol.add_trace(go.Scatter(x=df_bike_vis['semana_dt'], y=df_bike_vis['distancia_km'], name="Distância (km)", mode='lines+markers', line=dict(color='#ef4444', width=2)), row=1, col=1, secondary_y=False)
        
        fig_vol.add_trace(go.Scatter(x=df_bike_vis['semana_dt'], y=df_bike_vis['cadencia'], name="Cadência Média (rpm)", mode='lines', line=dict(color='#f59e0b', width=2)), row=2, col=1, secondary_y=False)
        
        fig_vol.update_layout(height=500, template="plotly_dark", hovermode="x unified", margin=dict(t=30, b=10))
        fig_vol.update_xaxes(tickmode='array', tickvals=tickvals_bike, ticktext=ticktext_bike, tickangle=0, row=2, col=1)
        fig_vol.update_yaxes(title_text="Distância (km)", row=1, col=1, secondary_y=False)
        fig_vol.update_yaxes(title_text="Horas no Selim", row=1, col=1, secondary_y=True, showgrid=False)
        fig_vol.update_yaxes(title_text="RPM", row=2, col=1, secondary_y=False)
        st.plotly_chart(fig_vol, use_container_width=True)
    else:
        st.info("Aguardando o primeiro registro de ciclismo para renderizar gráficos de carga.")

    # ============================================================================
    # 5. DIÁRIO OBSERVACIONAL E TABELA DE DADOS
    # ============================================================================
    st.divider()
    st.markdown("### Diário Quantitativo e Qualitativo")
    
    df_tabela = df_analise[['semana_num', 'semana_dt', 'peso_kg', 'peso_std', 'perda_semanal_kg', 'waist_cm', 'prot_kg_dia', 'tss', 'tsb', 'distancia_km', 'diario_contexto']].copy()
    df_tabela['semana_dt'] = df_tabela['semana_dt'].dt.strftime('%d/%m/%Y')
    df_tabela.columns = ['Semana', 'Data Base', 'Peso Médio', 'DP Peso (Flut.)', 'Delta Peso', 'Cintura (cm)', 'Prot (g/kg/dia)', 'TSS', 'TSB', 'Volume (km)', 'Contexto/Notas']
    
    st.dataframe(df_tabela.style.format({
        'Peso Médio': '{:.2f} kg', 
        'DP Peso (Flut.)': '± {:.2f} kg',
        'Delta Peso': '{:.2f} kg',
        'Cintura (cm)': '{:.1f}',
        'Prot (g/kg/dia)': '{:.2f}',
        'TSS': '{:.0f}',
        'TSB': '{:.0f}',
        'Volume (km)': '{:.1f}'
    }), hide_index=True, use_container_width=True)

else:
    st.info("Aguardando sincronização de dados históricos do banco Neon.tech...")
