from datetime import datetime, timedelta
import math
import time
from typing import Any, Dict, List, Optional
import numpy as np
import pandas as pd
import requests
from app.config import get_now_br
from app.database import fetch_all
from app.services.intervals_service import _get_intervals_creds

_CACHE_BIKE: Dict[str, Any] = {"ts": 0.0, "data": None}
_CACHE_TTL_SECONDS = 45.0


def invalidar_cache_bike() -> None:
    _CACHE_BIKE["ts"] = 0.0
    _CACHE_BIKE["data"] = None


def _buscar_atividades_intervals_150d(dias: int = 150) -> List[Dict[str, Any]]:
    api_key, athlete_id = _get_intervals_creds()
    if not api_key or not athlete_id:
        return []

    agora = get_now_br()
    inicio = (agora - timedelta(days=dias)).strftime("%Y-%m-%dT00:00:00")
    fim = agora.strftime("%Y-%m-%dT23:59:59")
    url = f"https://intervals.icu/api/v1/athlete/{athlete_id}/activities?oldest={inicio}&newest={fim}"

    try:
        res = requests.get(url, auth=("API_KEY", api_key), timeout=10)
        if res.status_code == 200:
            data = res.json()
            return data if isinstance(data, list) else []
    except Exception:
        pass
    return []


def _clean_num(val: Any, decimals: int = 2, default: float = 0.0) -> float:
    if val is None:
        return default
    try:
        f = float(val)
        if math.isnan(f) or math.isinf(f):
            return default
        return round(f, decimals)
    except Exception:
        return default


def _clean_optional_num(val: Any, decimals: int = 1) -> Optional[float]:
    if val is None:
        return None
    try:
        f = float(val)
        if math.isnan(f) or math.isinf(f) or f <= 0:
            return None
        return round(f, decimals)
    except Exception:
        return None


def obter_dados_dashboard_bike(
    data_inicio: str = "2025-12-30", force_refresh: bool = False
) -> Dict[str, Any]:
    """
    Reproduz o pipeline longitudinal de dashboardbike.py:
    - Agrega semanalmente (W-SUN, closed='left', label='left') peso, cintura (body_measurements),
      consumo nutricional e atividades de ciclismo (Ride / VirtualRide do Intervals.icu).
    - Retorna dicionário pronto para os endpoints /api/dashboard/kpis e /api/dashboard/graficos-bike.
    """
    now_ts = time.time()
    if (
        not force_refresh
        and _CACHE_BIKE["data"] is not None
        and (now_ts - _CACHE_BIKE["ts"]) < _CACHE_TTL_SECONDS
    ):
        return _CACHE_BIKE["data"]

    rows_peso = fetch_all(
        """
        SELECT data, peso_kg
        FROM public.peso
        WHERE peso_kg IS NOT NULL AND data >= :d
        ORDER BY data ASC
        """,
        {"d": data_inicio},
    )
    rows_medidas = fetch_all(
        """
        SELECT log_date AS data, waist_cm
        FROM public.body_measurements
        WHERE waist_cm IS NOT NULL AND log_date >= :d
        ORDER BY log_date ASC
        """,
        {"d": data_inicio},
    )
    rows_consumo = fetch_all(
        """
        SELECT data, kcal, proteina, carbo, gordura
        FROM public.consumo
        WHERE data >= :d
        ORDER BY data ASC
        """,
        {"d": data_inicio},
    )
    dados_brutos_intervals = _buscar_atividades_intervals_150d(dias=150)

    if not rows_peso:
        vazio = {
            "has_data": False,
            "has_bike_data": False,
            "semana_em_andamento": False,
            "aviso_semana_texto": None,
            "kpis": {
                "peso_atual": 0.0,
                "delta_peso": 0.0,
                "cintura_atual": 0.0,
                "delta_cintura": 0.0,
                "has_cintura": False,
                "ctl_atual": 0,
                "tsb_atual": 0,
                "tsb_status": "Fadiga Otimizada",
                "tsb_badge_class": "bg-emerald-500/15 text-emerald-300 border-emerald-500/30",
            },
            "charts": {
                "labels_full": [],
                "peso_medio": [],
                "cintura_cm": [],
                "prot_dia": [],
                "carbo_dia": [],
                "kcal_dia": [],
                "labels_bike": [],
                "tss": [],
                "ctl": [],
                "atl": [],
                "tsb": [],
                "tsb_colors": [],
                "distancia_km": [],
                "duracao_h": [],
                "cadencia": [],
            },
            "tabela_semanal": [],
        }
        _CACHE_BIKE["ts"] = now_ts
        _CACHE_BIKE["data"] = vazio
        return vazio

    df_peso = pd.DataFrame(rows_peso)
    df_peso["data"] = pd.to_datetime(df_peso["data"]).dt.normalize()
    df_peso["peso_kg"] = pd.to_numeric(df_peso["peso_kg"], errors="coerce")
    df_peso = df_peso.dropna(subset=["data", "peso_kg"]).sort_values("data").drop_duplicates(subset=["data"], keep="last")

    peso_semanal = (
        df_peso.set_index("data")
        .resample("W-SUN", closed="left", label="left")
        .agg(peso_medio=("peso_kg", "mean"), peso_std=("peso_kg", "std"))
        .reset_index()
    )
    peso_semanal.rename(columns={"data": "semana_dt", "peso_medio": "peso_kg"}, inplace=True)
    peso_semanal["perda_semanal_kg"] = peso_semanal["peso_kg"].diff() * -1
    peso_semanal["peso_std"] = peso_semanal["peso_std"].fillna(0.0)

    if rows_medidas:
        df_medidas = pd.DataFrame(rows_medidas)
        df_medidas["data"] = pd.to_datetime(df_medidas["data"]).dt.normalize()
        df_medidas["waist_cm"] = pd.to_numeric(df_medidas["waist_cm"], errors="coerce")
        df_medidas = df_medidas.dropna(subset=["data", "waist_cm"]).sort_values("data").drop_duplicates(subset=["data"], keep="last")
        cintura_semanal = (
            df_medidas.set_index("data")
            .resample("W-SUN", closed="left", label="left")
            .agg({"waist_cm": "mean"})
            .reset_index()
        )
        cintura_semanal["waist_cm"] = cintura_semanal["waist_cm"].interpolate(method="linear")
        cintura_semanal.rename(columns={"data": "semana_dt"}, inplace=True)
    else:
        cintura_semanal = pd.DataFrame({"semana_dt": peso_semanal["semana_dt"], "waist_cm": np.nan})

    if rows_consumo:
        df_consumo = pd.DataFrame(rows_consumo)
        df_consumo["data"] = pd.to_datetime(df_consumo["data"]).dt.normalize()
        for col in ["kcal", "proteina", "carbo", "gordura"]:
            df_consumo[col] = pd.to_numeric(df_consumo[col], errors="coerce").fillna(0.0)
        consumo_semanal = (
            df_consumo.set_index("data")
            .resample("W-SUN", closed="left", label="left")
            .agg({"kcal": "sum", "proteina": "sum", "carbo": "sum", "gordura": "sum"})
            .reset_index()
        )
        consumo_semanal[["kcal", "proteina", "carbo", "gordura"]] = (
            consumo_semanal[["kcal", "proteina", "carbo", "gordura"]] / 7.0
        )
        consumo_semanal.rename(columns={"data": "semana_dt"}, inplace=True)
    else:
        consumo_semanal = pd.DataFrame(columns=["semana_dt", "kcal", "proteina", "carbo", "gordura"])

    df_bike = pd.DataFrame(dados_brutos_intervals)
    primeiro_pedal = None
    if not df_bike.empty and "type" in df_bike.columns:
        df_bike = df_bike[df_bike["type"].isin(["Ride", "VirtualRide"])].copy()
        if not df_bike.empty:
            df_bike["data"] = pd.to_datetime(df_bike["start_date_local"].astype(str).str[:10], errors="coerce").dt.normalize()
            df_bike = df_bike.dropna(subset=["data"]).sort_values("data")
            primeiro_pedal = df_bike["data"].min()

            df_bike["tss"] = pd.to_numeric(df_bike.get("icu_training_load", 0), errors="coerce").fillna(0.0)
            df_bike["atl"] = pd.to_numeric(df_bike.get("icu_atl", np.nan), errors="coerce")
            df_bike["ctl"] = pd.to_numeric(df_bike.get("icu_ctl", np.nan), errors="coerce")
            df_bike["distancia_km"] = pd.to_numeric(df_bike.get("distance", 0), errors="coerce").fillna(0.0) / 1000.0
            df_bike["duracao_h"] = pd.to_numeric(df_bike.get("moving_time", 0), errors="coerce").fillna(0.0) / 3600.0
            df_bike["cadencia"] = pd.to_numeric(df_bike.get("average_cadence", np.nan), errors="coerce")

            bike_semanal = (
                df_bike.set_index("data")
                .resample("W-SUN", closed="left", label="left")
                .agg(
                    {
                        "tss": "sum",
                        "atl": "last",
                        "ctl": "last",
                        "distancia_km": "sum",
                        "duracao_h": "sum",
                        "cadencia": "mean",
                    }
                )
                .reset_index()
            )
            bike_semanal.rename(columns={"data": "semana_dt"}, inplace=True)
            bike_semanal["tsb"] = bike_semanal["ctl"] - bike_semanal["atl"]
        else:
            bike_semanal = pd.DataFrame(columns=["semana_dt", "tss", "atl", "ctl", "tsb", "distancia_km", "duracao_h", "cadencia"])
    else:
        bike_semanal = pd.DataFrame(columns=["semana_dt", "tss", "atl", "ctl", "tsb", "distancia_km", "duracao_h", "cadencia"])

    df_analise = pd.merge(peso_semanal, cintura_semanal, on="semana_dt", how="left")
    df_analise = pd.merge(df_analise, consumo_semanal, on="semana_dt", how="left")
    df_analise = pd.merge(df_analise, bike_semanal, on="semana_dt", how="left")

    colunas_esforco = ["tss", "distancia_km", "duracao_h", "cadencia", "kcal", "proteina", "carbo", "gordura"]
    for col in colunas_esforco:
        if col not in df_analise.columns:
            df_analise[col] = 0.0
    df_analise[colunas_esforco] = df_analise[colunas_esforco].fillna(0.0)

    for col in ["ctl", "atl"]:
        if col not in df_analise.columns:
            df_analise[col] = 0.0
    df_analise[["ctl", "atl"]] = df_analise[["ctl", "atl"]].ffill().fillna(0.0)
    df_analise["tsb"] = df_analise["ctl"] - df_analise["atl"]
    df_analise["prot_kg_dia"] = df_analise["proteina"] / df_analise["peso_kg"]

    df_analise = df_analise.dropna(subset=["peso_kg"]).sort_values("semana_dt").reset_index(drop=True)
    df_analise["semana_num"] = [i + 1 for i in range(len(df_analise))]

    # Verifica se a última semana está em andamento
    hoje = pd.Timestamp(get_now_br().date())
    ultima_semana_dt = df_analise["semana_dt"].iloc[-1]
    fim_ultima_semana = ultima_semana_dt + timedelta(days=6)
    semana_em_andamento = bool(ultima_semana_dt <= hoje <= fim_ultima_semana)
    aviso_semana_texto = None
    if semana_em_andamento:
        num_ult = int(df_analise["semana_num"].iloc[-1])
        aviso_semana_texto = (
            f"Atenção: A Semana {num_ult} ({ultima_semana_dt.strftime('%d/%m')}) está em andamento. "
            "Os registros de carga, volume e nutrição representam uma fração do período e podem gerar distorções visuais."
        )

    # KPIs principais (dashboardbike.py linhas 144-166)
    peso_inicial = float(df_analise["peso_kg"].iloc[0])
    peso_atual = float(df_analise["peso_kg"].iloc[-1])
    delta_peso = round(peso_inicial - peso_atual, 1)

    cinturas_validas = df_analise["waist_cm"].dropna()
    has_cintura = not cinturas_validas.empty
    cintura_inicial = float(cinturas_validas.iloc[0]) if has_cintura else 0.0
    cintura_atual = float(cinturas_validas.iloc[-1]) if has_cintura else 0.0
    delta_cintura = round(cintura_inicial - cintura_atual, 1) if has_cintura else 0.0

    ctl_atual = round(float(df_analise["ctl"].iloc[-1]))
    tsb_atual = round(float(df_analise["tsb"].iloc[-1]))

    if tsb_atual < -20:
        tsb_status = "Alta Fadiga Cumulativa"
        tsb_badge_class = "bg-rose-500/15 text-rose-300 border-rose-500/30"
    elif tsb_atual > 10:
        tsb_status = "Repouso/Destreinamento"
        tsb_badge_class = "bg-sky-500/15 text-sky-300 border-sky-500/30"
    else:
        tsb_status = "Fadiga Otimizada"
        tsb_badge_class = "bg-emerald-500/15 text-emerald-300 border-emerald-500/30"

    labels_full = [
        f"S{int(row['semana_num'])} ({row['semana_dt'].strftime('%d/%m')})"
        for _, row in df_analise.iterrows()
    ]

    df_bike_vis = (
        df_analise[df_analise["semana_dt"] >= primeiro_pedal].copy()
        if primeiro_pedal is not None
        else pd.DataFrame()
    )
    has_bike_data = not df_bike_vis.empty
    labels_bike = [
        f"S{int(row['semana_num'])} ({row['semana_dt'].strftime('%d/%m')})"
        for _, row in df_bike_vis.iterrows()
    ] if has_bike_data else []

    tsb_list = [_clean_num(v, 1) for v in df_bike_vis["tsb"]] if has_bike_data else []
    tsb_colors = ["rgba(16, 185, 129, 0.85)" if t > 0 else "rgba(239, 68, 68, 0.85)" for t in tsb_list]

    tabela_semanal: List[Dict[str, Any]] = []
    # Ordem reversa na tabela (semanas mais recentes primeiro) ou cronológica S1..SN
    for _, row in df_analise.iterrows():
        delta_sem = row.get("perda_semanal_kg")
        waist_val = _clean_optional_num(row.get("waist_cm"), 1)
        tabela_semanal.append(
            {
                "semana": f"S{int(row['semana_num'])}",
                "data_base": row["semana_dt"].strftime("%d/%m/%Y"),
                "peso_medio": f"{_clean_num(row.get('peso_kg'), 2):.2f} kg",
                "peso_std": f"± {_clean_num(row.get('peso_std'), 2):.2f} kg",
                "delta_peso": f"{_clean_num(delta_sem, 2):+.2f} kg" if pd.notna(delta_sem) else "—",
                "cintura": f"{waist_val:.1f} cm" if waist_val is not None else "—",
                "prot_kg_dia": f"{_clean_num(row.get('prot_kg_dia'), 2):.2f}",
                "tss": f"{_clean_num(row.get('tss'), 0):.0f}",
                "tsb": f"{_clean_num(row.get('tsb'), 0):+.0f}",
                "tsb_raw": _clean_num(row.get("tsb"), 1),
                "volume_km": f"{_clean_num(row.get('distancia_km'), 1):.1f} km",
            }
        )

    resultado = {
        "has_data": True,
        "has_bike_data": has_bike_data,
        "semana_em_andamento": semana_em_andamento,
        "aviso_semana_texto": aviso_semana_texto,
        "kpis": {
            "peso_atual": round(peso_atual, 1),
            "delta_peso": delta_peso,
            "cintura_atual": round(cintura_atual, 1),
            "delta_cintura": delta_cintura,
            "has_cintura": has_cintura,
            "ctl_atual": ctl_atual,
            "tsb_atual": tsb_atual,
            "tsb_status": tsb_status,
            "tsb_badge_class": tsb_badge_class,
        },
        "charts": {
            "labels_full": labels_full,
            "peso_medio": [_clean_num(v, 2) for v in df_analise["peso_kg"]],
            "cintura_cm": [_clean_optional_num(v, 1) for v in df_analise["waist_cm"]],
            "prot_dia": [_clean_num(v, 1) for v in df_analise["proteina"]],
            "carbo_dia": [_clean_num(v, 1) for v in df_analise["carbo"]],
            "kcal_dia": [_clean_num(v, 0) for v in df_analise["kcal"]],
            "labels_bike": labels_bike,
            "tss": [_clean_num(v, 0) for v in df_bike_vis["tss"]] if has_bike_data else [],
            "ctl": [_clean_num(v, 1) for v in df_bike_vis["ctl"]] if has_bike_data else [],
            "atl": [_clean_num(v, 1) for v in df_bike_vis["atl"]] if has_bike_data else [],
            "tsb": tsb_list,
            "tsb_colors": tsb_colors,
            "distancia_km": [_clean_num(v, 1) for v in df_bike_vis["distancia_km"]] if has_bike_data else [],
            "duracao_h": [_clean_num(v, 2) for v in df_bike_vis["duracao_h"]] if has_bike_data else [],
            "cadencia": [_clean_num(v, 1) for v in df_bike_vis["cadencia"]] if has_bike_data else [],
        },
        "tabela_semanal": tabela_semanal,
    }

    _CACHE_BIKE["ts"] = now_ts
    _CACHE_BIKE["data"] = resultado
    return resultado
