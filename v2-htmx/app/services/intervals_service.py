from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
import requests
from sqlalchemy import text
from sqlalchemy.engine import Engine
from app.config import INTERVALS_API_KEY, INTERVALS_ATHLETE_ID
from app.database import get_engine


def conectar_intervals(dias_retroativos: int = 7) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
    """
    Busca atividades dos últimos N dias na API do Intervals.icu,
    reproduzindo a função conectar_intervals(dias_retroativos=7) de @app.py.
    """
    if not INTERVALS_API_KEY or not INTERVALS_ATHLETE_ID:
        return (
            None,
            "Credenciais do Intervals.icu (INTERVALS_API_KEY e INTERVALS_ATHLETE_ID) não encontradas no arquivo .env!",
        )

    hoje_dt = datetime.now()
    data_inicio = (hoje_dt - timedelta(days=dias_retroativos)).strftime("%Y-%m-%dT00:00:00")
    data_fim = hoje_dt.strftime("%Y-%m-%dT23:59:59")

    url = f"https://intervals.icu/api/v1/athlete/{INTERVALS_ATHLETE_ID}/activities?oldest={data_inicio}&newest={data_fim}"
    auth = ("API_KEY", INTERVALS_API_KEY)

    try:
        res = requests.get(url, auth=auth, timeout=20)
        res.raise_for_status()
        dataset = res.json()
    except Exception as e:
        return None, f"Erro na conexão com o Intervals.icu: {e}"

    treinos: List[Dict[str, Any]] = []
    if dataset and isinstance(dataset, list):
        for atv in dataset:
            data_hora_local = atv.get("start_date_local", "") or ""
            treinos.append(
                {
                    "id_atividade": str(atv.get("id")),
                    "data": data_hora_local[:10] if len(data_hora_local) >= 10 else None,
                    "hora": data_hora_local[11:16] if len(data_hora_local) >= 16 else None,
                    "tipo": "Intervals - " + (atv.get("type") or "Workout"),
                    "nome_treino": atv.get("name") or "Treino",
                    "tempo_mov_min": round((atv.get("moving_time") or 0) / 60, 1),
                    "distancia_km": round((atv.get("distance") or 0) / 1000, 2),
                    "elevacao_m": round((atv.get("total_elevation_gain") or 0), 0),
                    "bpm_medio": round((atv.get("average_heartrate") or 0), 1),
                    "bpm_max": round((atv.get("max_heartrate") or 0), 1),
                    "cadencia_rpm": round((atv.get("average_cadence") or 0), 1),
                    "calorias_kcal": round((atv.get("calories") or 0), 2),
                    "carga_tss": round((atv.get("icu_training_load") or 0), 1),
                    "intensidade_if": round((atv.get("icu_intensity") or 0), 3),
                }
            )
        return treinos, None
    return [], None


def sincronizar_treinos_recentes(
    engine: Optional[Engine] = None, dias_retroativos: int = 7
) -> Tuple[bool, str]:
    """
    Sincroniza os treinos recentes do Intervals.icu no banco Neon (tabela exercicios)
    usando exatamente a query ON CONFLICT (id_atividade) DO UPDATE de @app.py.
    """
    treinos, erro = conectar_intervals(dias_retroativos=dias_retroativos)
    if erro:
        return False, erro
    if not treinos:
        return True, "Nenhuma atividade encontrada nos últimos 7 dias no Intervals.icu."

    eng = engine or get_engine()
    try:
        with eng.begin() as conn:
            for t in treinos:
                query = text(
                    """
                    INSERT INTO exercicios (
                        id_atividade, data, hora, tipo, nome_treino, duracao_min,
                        distancia_km, elevacao_m, bpm_medio, bpm_max,
                        cadencia_rpm, calorias, carga_tss, intensidade_if
                    ) VALUES (
                        :id_atividade, :data, :hora, :tipo, :nome_treino, :tempo_mov_min,
                        :distancia_km, :elevacao_m, :bpm_medio, :bpm_max,
                        :cadencia_rpm, :calorias_kcal, :carga_tss, :intensidade_if
                    )
                    ON CONFLICT (id_atividade) DO UPDATE SET
                        nome_treino = EXCLUDED.nome_treino,
                        carga_tss = EXCLUDED.carga_tss,
                        calorias = EXCLUDED.calorias,
                        intensidade_if = EXCLUDED.intensidade_if,
                        cadencia_rpm = EXCLUDED.cadencia_rpm;
                    """
                )
                conn.execute(query, t)
        return True, f"✅ Sincronização com Intervals.icu concluída! ({len(treinos)} treino(s) processado(s))"
    except Exception as e:
        return False, f"Erro ao salvar treinos no banco: {e}"
