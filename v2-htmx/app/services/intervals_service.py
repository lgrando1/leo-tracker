import os
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
import requests
from sqlalchemy import text
from sqlalchemy.engine import Engine
from app.config import INTERVALS_API_KEY, INTERVALS_ATHLETE_ID, get_now_br
from app.database import get_engine

GENERIC_WORKOUT_NAMES = {
    "",
    "treino",
    "workout",
    "weight training",
    "weighttraining",
    "strength",
    "musculação",
    "musculacao",
    "morning workout",
    "afternoon workout",
    "evening workout",
    "night workout",
    "lunch workout",
    "morning weight training",
    "afternoon weight training",
    "evening weight training",
}


def _get_intervals_creds() -> Tuple[str, str]:
    api_key = (
        os.getenv("INTERVALS_API_KEY") or INTERVALS_API_KEY or ""
    ).strip().strip('"').strip("'").strip()
    athlete_id = (
        os.getenv("INTERVALS_ATHLETE_ID") or INTERVALS_ATHLETE_ID or ""
    ).strip().strip('"').strip("'").strip()
    return api_key, athlete_id


def _mapear_atividade_intervals(atv: Dict[str, Any]) -> Tuple[str, str, str]:
    """
    Mapeia tipo, nome_treino e observacoes (description) de uma atividade do Intervals.icu.
    Reconhece treinos de força vindos do Hevy via Strava (type == 'WeightTraining')
    e aproveita o campo 'description' caso o nome venha genérico.
    """
    raw_type = str(atv.get("type") or "Workout").strip()
    raw_name = str(atv.get("name") or "").strip()
    raw_desc = str(atv.get("description") or "").strip()

    desc_lines = [ln.strip() for ln in raw_desc.splitlines() if ln.strip()]
    resumo_desc = " | ".join(desc_lines[:3])[:140] if desc_lines else ""

    contexto_lower = f"{raw_type} {raw_name} {raw_desc}".lower()
    is_weight_training = raw_type in ("WeightTraining", "Strength", "Crossfit") or "hevy" in contexto_lower

    if is_weight_training:
        tipo_final = "Musculação (Hevy)" if ("hevy" in contexto_lower or raw_type == "WeightTraining") else "Musculação"
    else:
        tipo_final = f"Intervals - {raw_type}"

    nome_lower = raw_name.lower().strip()
    nome_eh_generico = (
        not raw_name
        or nome_lower in GENERIC_WORKOUT_NAMES
        or nome_lower.endswith("weight training")
        or nome_lower.endswith("workout")
    )

    if nome_eh_generico and resumo_desc:
        if raw_name and nome_lower not in ("treino", "workout"):
            nome_final = f"{raw_name} · {resumo_desc}"[:160]
        else:
            nome_final = resumo_desc[:160]
    else:
        nome_final = raw_name or ("Treino de Força (Hevy)" if is_weight_training else "Treino")

    observacoes_final = raw_desc[:1000] if raw_desc else ""
    return tipo_final, nome_final, observacoes_final


def conectar_intervals(dias_retroativos: int = 7) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
    """
    Busca atividades dos últimos N dias na API do Intervals.icu,
    mapeando WeightTraining (Hevy -> Strava -> Intervals) para Musculação e
    aproveitando o campo description quando o nome é genérico.
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
            if not isinstance(atv, dict) or not atv.get("id"):
                continue
            data_hora_local = str(atv.get("start_date_local") or "")
            tipo_final, nome_final, obs_final = _mapear_atividade_intervals(atv)

            treinos.append(
                {
                    "id_atividade": str(atv.get("id")),
                    "data": data_hora_local[:10] if len(data_hora_local) >= 10 else None,
                    "hora": data_hora_local[11:16] if len(data_hora_local) >= 16 else None,
                    "tipo": tipo_final,
                    "nome_treino": nome_final,
                    "tempo_mov_min": round((atv.get("moving_time") or atv.get("elapsed_time") or 0) / 60, 1),
                    "distancia_km": round((atv.get("distance") or 0) / 1000, 2),
                    "elevacao_m": round((atv.get("total_elevation_gain") or 0), 0),
                    "bpm_medio": round((atv.get("average_heartrate") or 0), 1),
                    "bpm_max": round((atv.get("max_heartrate") or 0), 1),
                    "cadencia_rpm": round((atv.get("average_cadence") or 0), 1),
                    "calorias_kcal": round((atv.get("calories") or 0), 2),
                    "carga_tss": round((atv.get("icu_training_load") or 0), 1),
                    "intensidade_if": round((atv.get("icu_intensity") or 0), 3),
                    "observacoes": obs_final,
                }
            )
        return treinos, None
    return [], None


def sincronizar_treinos_recentes(
    engine: Optional[Engine] = None, dias_retroativos: int = 7
) -> Tuple[bool, str]:
    """
    Sincroniza os treinos recentes do Intervals.icu no banco Neon (tabela exercicios)
    usando SELECT -> UPDATE / INSERT com commit explícito (evitando depender de constraint UNIQUE).
    """
    treinos, erro = conectar_intervals(dias_retroativos=dias_retroativos)
    if erro:
        return False, erro
    if not treinos:
        return True, "Nenhuma atividade encontrada nos últimos 7 dias no Intervals.icu."

    eng = engine or get_engine()
    try:
        with eng.connect() as conn:
            for t in treinos:
                existente = conn.execute(
                    text("SELECT id FROM exercicios WHERE id_atividade = :id_atividade LIMIT 1"),
                    {"id_atividade": t["id_atividade"]},
                ).first()

                if existente is not None:
                    conn.execute(
                        text(
                            """
                            UPDATE exercicios SET
                                tipo = :tipo,
                                nome_treino = :nome_treino,
                                duracao_min = :tempo_mov_min,
                                distancia_km = :distancia_km,
                                elevacao_m = :elevacao_m,
                                bpm_medio = :bpm_medio,
                                bpm_max = :bpm_max,
                                cadencia_rpm = :cadencia_rpm,
                                calorias = :calorias_kcal,
                                carga_tss = :carga_tss,
                                intensidade_if = :intensidade_if,
                                observacoes = COALESCE(NULLIF(:observacoes, ''), observacoes)
                            WHERE id_atividade = :id_atividade
                            """
                        ),
                        t,
                    )
                else:
                    conn.execute(
                        text(
                            """
                            INSERT INTO exercicios (
                                id_atividade, data, hora, tipo, nome_treino, duracao_min,
                                distancia_km, elevacao_m, bpm_medio, bpm_max,
                                cadencia_rpm, calorias, carga_tss, intensidade_if, observacoes
                            ) VALUES (
                                :id_atividade, :data, :hora, :tipo, :nome_treino, :tempo_mov_min,
                                :distancia_km, :elevacao_m, :bpm_medio, :bpm_max,
                                :cadencia_rpm, :calorias_kcal, :carga_tss, :intensidade_if, :observacoes
                            )
                            """
                        ),
                        t,
                    )
            conn.commit()
        return True, f"✅ Sincronização de treinos concluída ({len(treinos)} treino(s))"
    except Exception as e:
        return False, f"Erro SQL em exercicios: {type(e).__name__}: {e}"


def sincronizar_peso_intervals(
    engine: Optional[Engine] = None, dias_retroativos: int = 30
) -> Tuple[bool, str, int]:
    """
    Consulta GET https://intervals.icu/api/v1/athlete/{ATHLETE_ID}/wellness?oldest={inicio}&newest={fim}
    (últimos 30 dias) e sincroniza os registros válidos de peso ('weight' is not None e > 0)
    na tabela peso do Neon sem usar ON CONFLICT (data):
      1. SELECT id FROM peso WHERE DATE(data) = :data LIMIT 1
      2. Se existir: UPDATE peso SET peso_kg = :peso WHERE DATE(data) = :data
      3. Se não existir: INSERT INTO peso (data, peso_kg) VALUES (:data, :peso)
      4. Executa conn.commit() explícito.
    Qualquer erro SQL é retornado diretamente na mensagem (sem except silencioso).
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

    res = requests.get(url, auth=auth, timeout=8)
    res.raise_for_status()
    dataset = res.json()

    if not dataset or not isinstance(dataset, list):
        return True, "Nenhum dado de wellness retornado pelo Intervals.icu.", 0

    eng = engine or get_engine()
    inseridos = 0
    atualizados = 0
    verificados = 0

    try:
        with eng.connect() as conn:
            for item in dataset:
                if not isinstance(item, dict):
                    continue
                raw_w = item.get("weight")
                # Ignora dias onde weight é None sem interromper o loop
                if raw_w is None:
                    continue

                peso_val = round(float(raw_w), 2)
                if peso_val <= 0:
                    continue

                data_str = str(item.get("id") or item.get("date") or "").strip()[:10]
                if not data_str:
                    continue

                verificados += 1
                existente = conn.execute(
                    text("SELECT id FROM peso WHERE DATE(data) = :data LIMIT 1"),
                    {"data": data_str},
                ).first()

                if existente is not None:
                    conn.execute(
                        text("UPDATE peso SET peso_kg = :peso WHERE DATE(data) = :data"),
                        {"peso": peso_val, "data": data_str},
                    )
                    atualizados += 1
                else:
                    conn.execute(
                        text("INSERT INTO peso (data, peso_kg) VALUES (:data, :peso)"),
                        {"data": data_str, "peso": peso_val},
                    )
                    inseridos += 1

            conn.commit()

        total_gravados = inseridos + atualizados
        return (
            True,
            f"Peso sincronizado: {verificados} lidos ({inseridos} novos, {atualizados} atualizados)",
            total_gravados,
        )
    except Exception as e:
        return False, f"Erro SQL ao gravar peso no Neon ({type(e).__name__}): {e}", 0


def enviar_peso_intervals(data_peso: date, peso_kg: float) -> Tuple[bool, str]:
    """
    Envia PUT https://intervals.icu/api/v1/athlete/{ATHLETE_ID}/wellness/{YYYY-MM-DD}
    com {"weight": valor} para manter o Intervals.icu sincronizado a partir do app.
    """
    api_key, athlete_id = _get_intervals_creds()
    if not api_key or not athlete_id:
        return False, "INTERVALS_API_KEY / INTERVALS_ATHLETE_ID não configurados."

    data_str = data_peso.strftime("%Y-%m-%d")
    url = f"https://intervals.icu/api/v1/athlete/{athlete_id}/wellness/{data_str}"
    auth = ("API_KEY", api_key)
    payload = {"weight": round(float(peso_kg), 2)}

    try:
        res = requests.put(url, auth=auth, json=payload, timeout=8)
        res.raise_for_status()
        return True, f"Intervals.icu atualizado (wellness/{data_str} -> {peso_kg:.1f} kg)"
    except Exception as e:
        return False, f"Falha no PUT wellness Intervals.icu: {e}"


def debug_wellness_intervals(dias_retroativos: int = 30) -> Dict[str, Any]:
    """
    Retorna diagnóstico com os últimos 5 registros brutos retornados pela API /wellness
    do Intervals.icu e também executa sincronizar_peso_intervals() para exibir o resultado
    exato da gravação no banco Neon.
    """
    api_key, athlete_id = _get_intervals_creds()
    hoje_dt = get_now_br().date()
    data_inicio = (hoje_dt - timedelta(days=dias_retroativos)).strftime("%Y-%m-%d")
    data_fim = hoje_dt.strftime("%Y-%m-%d")

    if not api_key or not athlete_id:
        return {
            "ok": False,
            "athlete_id": athlete_id or "(vazio)",
            "range": f"{data_inicio} a {data_fim}",
            "total_days_returned": 0,
            "days_with_weight": 0,
            "sync_ok": False,
            "sync_message": "Credenciais ausentes",
            "last_5_raw": [],
            "last_5_with_weight": [],
            "error": "INTERVALS_API_KEY ou INTERVALS_ATHLETE_ID ausentes nas variáveis de ambiente.",
        }

    url = f"https://intervals.icu/api/v1/athlete/{athlete_id}/wellness?oldest={data_inicio}&newest={data_fim}"
    try:
        res = requests.get(url, auth=("API_KEY", api_key), timeout=8)
        res.raise_for_status()
        dataset = res.json()
        if not isinstance(dataset, list):
            dataset = []

        com_peso = [
            {"id": d.get("id"), "weight": d.get("weight"), "restingHR": d.get("restingHR"), "hrv": d.get("hrv")}
            for d in dataset
            if isinstance(d, dict) and d.get("weight") is not None
        ]
        ultimos_5_brutos = dataset[-5:] if len(dataset) >= 5 else dataset

        sync_ok, sync_msg, sync_count = sincronizar_peso_intervals(dias_retroativos=dias_retroativos)

        return {
            "ok": True,
            "athlete_id": athlete_id,
            "range": f"{data_inicio} a {data_fim}",
            "total_days_returned": len(dataset),
            "days_with_weight": len(com_peso),
            "sync_ok": sync_ok,
            "sync_message": sync_msg,
            "sync_count": sync_count,
            "last_5_raw": ultimos_5_brutos,
            "last_5_with_weight": com_peso[-5:],
            "error": None if sync_ok else sync_msg,
        }
    except Exception as e:
        return {
            "ok": False,
            "athlete_id": athlete_id,
            "range": f"{data_inicio} a {data_fim}",
            "total_days_returned": 0,
            "days_with_weight": 0,
            "sync_ok": False,
            "sync_message": f"{type(e).__name__}: {str(e)}",
            "last_5_raw": [],
            "last_5_with_weight": [],
            "error": f"{type(e).__name__}: {str(e)}",
        }
