import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
import requests
from sqlalchemy import text
from sqlalchemy.engine import Engine
from app.config import INTERVALS_API_KEY, INTERVALS_ATHLETE_ID, get_now_br
from app.database import get_engine


def _get_intervals_creds() -> Tuple[str, str]:
    api_key = (
        os.getenv("INTERVALS_API_KEY") or INTERVALS_API_KEY or ""
    ).strip().strip('"').strip("'").strip()
    athlete_id = (
        os.getenv("INTERVALS_ATHLETE_ID") or INTERVALS_ATHLETE_ID or ""
    ).strip().strip('"').strip("'").strip()
    return api_key, athlete_id


def conectar_intervals(dias_retroativos: int = 7) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
    """
    Busca atividades dos últimos N dias na API do Intervals.icu,
    reproduzindo a função conectar_intervals(dias_retroativos=7) de @app.py.
    """
    api_key, athlete_id = _get_intervals_creds()
    if not api_key or not athlete_id:
        return (
            None,
            "Credenciais do Intervals.icu (INTERVALS_API_KEY e INTERVALS_ATHLETE_ID) não encontradas no ambiente!",
        )

    hoje_dt = get_now_br()
    data_inicio = (hoje_dt - timedelta(days=dias_retroativos)).strftime("%Y-%m-%dT00:00:00")
    data_fim = hoje_dt.strftime("%Y-%m-%dT23:59:59")

    url = f"https://intervals.icu/api/v1/athlete/{athlete_id}/activities?oldest={data_inicio}&newest={data_fim}"
    auth = ("API_KEY", api_key)

    try:
        res = requests.get(url, auth=auth, timeout=8)
        res.raise_for_status()
        dataset = res.json()
    except Exception as e:
        return None, f"Erro na conexão com o Intervals.icu (activities): {e}"

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


def sincronizar_peso_intervals(
    engine: Optional[Engine] = None, dias_retroativos: int = 14
) -> Tuple[bool, str, int]:
    """
    Consulta GET https://intervals.icu/api/v1/athlete/{ATHLETE_ID}/wellness?oldest={data_inicio}&newest={data_fim}
    (últimos 14 dias) com timeout=8 e sincroniza os registros válidos de peso ('weight')
    na tabela public.peso do Neon (inserindo se não existir na data ou atualizando se mudou).
    Retorna (ok, mensagem, quantidade_inserida_ou_atualizada).
    """
    api_key, athlete_id = _get_intervals_creds()
    if not api_key or not athlete_id:
        return (
            False,
            "Credenciais do Intervals.icu ausentes para sincronizar wellness/peso.",
            0,
        )

    hoje_dt = get_now_br().date()
    data_inicio = (hoje_dt - timedelta(days=dias_retroativos)).strftime("%Y-%m-%d")
    data_fim = hoje_dt.strftime("%Y-%m-%d")

    url = f"https://intervals.icu/api/v1/athlete/{athlete_id}/wellness?oldest={data_inicio}&newest={data_fim}"
    auth = ("API_KEY", api_key)

    try:
        res = requests.get(url, auth=auth, timeout=8)
        res.raise_for_status()
        dataset = res.json()
    except Exception as e:
        return False, f"Erro ao consultar wellness no Intervals.icu: {e}", 0

    if not dataset or not isinstance(dataset, list):
        return True, "Nenhum dado de wellness retornado.", 0

    eng = engine or get_engine()
    alterados = 0
    verificados = 0

    try:
        with eng.begin() as conn:
            for item in dataset:
                if not isinstance(item, dict):
                    continue
                raw_w = item.get("weight")
                data_id = item.get("id")  # Formato YYYY-MM-DD no endpoint wellness
                if raw_w is None or not data_id:
                    continue
                try:
                    peso_val = round(float(raw_w), 2)
                except (ValueError, TypeError):
                    continue
                if peso_val <= 0:
                    continue

                verificados += 1
                row = conn.execute(
                    text(
                        "SELECT id, peso_kg FROM public.peso WHERE data = :d ORDER BY id DESC LIMIT 1"
                    ),
                    {"d": data_id},
                ).mappings().first()

                if row is None:
                    conn.execute(
                        text("INSERT INTO public.peso (data, peso_kg) VALUES (:d, :p)"),
                        {"d": data_id, "p": peso_val},
                    )
                    alterados += 1
                else:
                    peso_existente = float(row["peso_kg"] or 0.0)
                    if abs(peso_existente - peso_val) > 0.01:
                        conn.execute(
                            text("UPDATE public.peso SET peso_kg = :p WHERE id = :id"),
                            {"p": peso_val, "id": row["id"]},
                        )
                        alterados += 1

        return (
            True,
            f"Wellness sincronizado ({verificados} dia(s) com peso, {alterados} novo(s)/atualizado(s)).",
            alterados,
        )
    except Exception as e:
        return False, f"Erro ao sincronizar peso do Intervals no banco: {e}", 0
