import json
import os
import re
import traceback
from datetime import timedelta
from typing import Any, Dict, List, Optional, Tuple
import requests
from groq import Groq, NotFoundError
from app.config import GROQ_API_KEY, GROQ_MODEL_TEXT, get_now_br
from app.database import fetch_all
from app.services.groq_service import (
    FALLBACK_TEXT_MODELS,
    diagnosticar_chave_groq,
    formatar_erro_diagnostico_groq,
    listar_modelos_disponiveis,
)
from app.services.intervals_service import _get_intervals_creds, _mapear_atividade_intervals
from app.services.tracker_repo import get_metas, get_peso_historico


def _buscar_wellness_intervals(dias: int = 7) -> List[Dict[str, Any]]:
    api_key, athlete_id = _get_intervals_creds()
    if not api_key or not athlete_id:
        return []
    hoje = get_now_br().date()
    ini = (hoje - timedelta(days=dias)).strftime("%Y-%m-%d")
    fim = hoje.strftime("%Y-%m-%d")
    url = f"https://intervals.icu/api/v1/athlete/{athlete_id}/wellness?oldest={ini}&newest={fim}"
    try:
        res = requests.get(url, auth=("API_KEY", api_key), timeout=8)
        if res.status_code == 200:
            data = res.json()
            return data if isinstance(data, list) else []
    except Exception:
        pass
    return []


def _buscar_activities_intervals(dias: int = 7) -> List[Dict[str, Any]]:
    api_key, athlete_id = _get_intervals_creds()
    if not api_key or not athlete_id:
        return []
    agora = get_now_br()
    ini = (agora - timedelta(days=dias)).strftime("%Y-%m-%dT00:00:00")
    fim = agora.strftime("%Y-%m-%dT23:59:59")
    url = f"https://intervals.icu/api/v1/athlete/{athlete_id}/activities?oldest={ini}&newest={fim}"
    try:
        res = requests.get(url, auth=("API_KEY", api_key), timeout=8)
        if res.status_code == 200:
            data = res.json()
            return data if isinstance(data, list) else []
    except Exception:
        pass
    return []


def montar_contexto_tutor(dias: int = 7) -> Dict[str, Any]:
    """
    Reúne em um dicionário compacto os dados reais dos últimos 7 dias:
    1. Antropometria (peso inicial/atual do período, variação e metas configuradas)
    2. Nutrição (Neon public.consumo: médias diárias, g/kg de proteína e dias com déficit acentuado)
    3. Treinos (Intervals /activities + Neon public.exercicios: sessões, tipos, duração, TSS, CTL, ATL, TSB)
    4. Sono e Recuperação (Intervals /wellness: horas de sono sleepSecs/3600, sleepScore e restingHR)
    """
    hoje = get_now_br().date()
    dt_ini = hoje - timedelta(days=dias)
    metas = get_metas()

    # 1. Antropometria
    peso_hist = get_peso_historico(limit=30)
    peso_atual = float(peso_hist.get("peso_atual") or 105.0)
    tendencia_ewma = float(peso_hist.get("tendencia_atual") or peso_atual)

    pesos_7d = fetch_all(
        """
        SELECT data, peso_kg
        FROM public.peso
        WHERE data >= :d1 AND data <= :d2 AND peso_kg IS NOT NULL
        ORDER BY data ASC, id ASC
        """,
        {"d1": dt_ini, "d2": hoje},
    )
    if pesos_7d:
        peso_ini_7d = float(pesos_7d[0]["peso_kg"])
        peso_fim_7d = float(pesos_7d[-1]["peso_kg"])
        peso_atual = peso_fim_7d
    else:
        peso_ini_7d = peso_atual
        peso_fim_7d = peso_atual

    variacao_7d_kg = round(peso_fim_7d - peso_ini_7d, 2)

    # 2. Nutrição (Neon public.consumo)
    consumo_diario = fetch_all(
        """
        SELECT data,
               ROUND(CAST(SUM(COALESCE(kcal, 0)) AS NUMERIC), 0) AS kcal,
               ROUND(CAST(SUM(COALESCE(proteina, 0)) AS NUMERIC), 1) AS proteina_g,
               ROUND(CAST(SUM(COALESCE(carbo, 0)) AS NUMERIC), 1) AS carbo_g,
               ROUND(CAST(SUM(COALESCE(gordura, 0)) AS NUMERIC), 1) AS gordura_g,
               COUNT(*) AS refeicoes
        FROM public.consumo
        WHERE data >= :d1 AND data <= :d2
        GROUP BY data
        ORDER BY data ASC
        """,
        {"d1": dt_ini, "d2": hoje},
    )

    dias_com_registro = len(consumo_diario)
    if dias_com_registro > 0:
        media_kcal = round(sum(float(r["kcal"] or 0) for r in consumo_diario) / dias_com_registro, 0)
        media_prot = round(sum(float(r["proteina_g"] or 0) for r in consumo_diario) / dias_com_registro, 1)
        media_carb = round(sum(float(r["carbo_g"] or 0) for r in consumo_diario) / dias_com_registro, 1)
        media_gord = round(sum(float(r["gordura_g"] or 0) for r in consumo_diario) / dias_com_registro, 1)
    else:
        media_kcal, media_prot, media_carb, media_gord = 0.0, 0.0, 0.0, 0.0

    prot_g_kg = round(media_prot / max(peso_atual, 1.0), 2)

    meta_prot = float(metas.get("prot") or 108)
    meta_kcal = float(metas.get("kcal") or 1638)

    dias_deficit_proteico: List[str] = []
    dias_deficit_calorico_acentuado: List[str] = []
    resumo_dias_nutri: List[Dict[str, Any]] = []

    for r in consumo_diario:
        d_str = r["data"].strftime("%Y-%m-%d") if hasattr(r["data"], "strftime") else str(r["data"])
        k_val = float(r["kcal"] or 0)
        p_val = float(r["proteina_g"] or 0)
        c_val = float(r["carbo_g"] or 0)
        g_val = float(r["gordura_g"] or 0)

        if p_val < (meta_prot * 0.8):
            dias_deficit_proteico.append(f"{d_str} ({p_val:.0f}g vs meta {meta_prot:.0f}g)")
        if k_val < (meta_kcal * 0.75):
            dias_deficit_calorico_acentuado.append(f"{d_str} ({k_val:.0f} kcal vs meta {meta_kcal:.0f} kcal)")

        resumo_dias_nutri.append(
            {
                "data": d_str,
                "kcal": int(k_val),
                "p_g": p_val,
                "c_g": c_val,
                "g_g": g_val,
            }
        )

    # 3. Sono e Recuperação (Intervals /wellness)
    wellness_raw = _buscar_wellness_intervals(dias=dias)
    noites_sono: List[Dict[str, Any]] = []
    horas_list: List[float] = []
    scores_list: List[float] = []
    rhr_list: List[float] = []
    ultimo_ctl_wellness: Optional[float] = None
    ultimo_atl_wellness: Optional[float] = None

    for w in wellness_raw:
        if not isinstance(w, dict):
            continue
        d_id = str(w.get("id") or "")[:10]
        sleep_secs = w.get("sleepSecs")
        sleep_h = round(float(sleep_secs) / 3600.0, 2) if sleep_secs is not None and float(sleep_secs or 0) > 0 else None
        sleep_score = w.get("sleepScore")
        rhr = w.get("restingHR")
        hrv = w.get("hrv")

        if w.get("ctl") is not None:
            try:
                ultimo_ctl_wellness = round(float(w["ctl"]), 1)
            except Exception:
                pass
        if w.get("atl") is not None:
            try:
                ultimo_atl_wellness = round(float(w["atl"]), 1)
            except Exception:
                pass

        if sleep_h is not None:
            horas_list.append(sleep_h)
        if sleep_score is not None:
            try:
                scores_list.append(float(sleep_score))
            except Exception:
                pass
        if rhr is not None:
            try:
                rhr_list.append(float(rhr))
            except Exception:
                pass

        if any(v is not None for v in (sleep_h, sleep_score, rhr, hrv)):
            noites_sono.append(
                {
                    "data": d_id,
                    "sono_horas": sleep_h,
                    "sleep_score": sleep_score,
                    "resting_hr_bpm": rhr,
                    "hrv": hrv,
                }
            )

    media_sono_h = round(sum(horas_list) / len(horas_list), 2) if horas_list else None
    media_sleep_score = round(sum(scores_list) / len(scores_list), 1) if scores_list else None
    media_rhr = round(sum(rhr_list) / len(rhr_list), 1) if rhr_list else None

    # 4. Treinos (Intervals /activities + Neon public.exercicios)
    activities_raw = _buscar_activities_intervals(dias=dias)
    exercicios_neon = fetch_all(
        """
        SELECT data, tipo, nome_treino, duracao_min, passos, passos_total_dia,
               distancia_km, calorias, bpm_medio, carga_tss, intensidade_if, observacoes
        FROM public.exercicios
        WHERE data >= :d1 AND data <= :d2
        ORDER BY data ASC, id ASC
        """,
        {"d1": dt_ini, "d2": hoje},
    )

    sessoes_lista: List[Dict[str, Any]] = []
    tss_total = 0.0
    duracao_total_min = 0.0
    qtd_ciclismo = 0
    qtd_forca = 0
    qtd_outros = 0
    ctl_atual = ultimo_ctl_wellness or 0.0
    atl_atual = ultimo_atl_wellness or 0.0

    if activities_raw:
        for atv in activities_raw:
            if not isinstance(atv, dict) or not atv.get("id"):
                continue
            tipo_map, nome_map, obs_map = _mapear_atividade_intervals(atv)
            dur_min = round(float(atv.get("moving_time") or atv.get("elapsed_time") or 0) / 60.0, 1)
            tss_val = round(float(atv.get("icu_training_load") or 0), 1)
            dist_km = round(float(atv.get("distance") or 0) / 1000.0, 2)
            raw_type = str(atv.get("type") or "")

            if atv.get("icu_ctl") is not None:
                try:
                    ctl_atual = round(float(atv["icu_ctl"]), 1)
                except Exception:
                    pass
            if atv.get("icu_atl") is not None:
                try:
                    atl_atual = round(float(atv["icu_atl"]), 1)
                except Exception:
                    pass

            if raw_type in ("Ride", "VirtualRide"):
                qtd_ciclismo += 1
            elif "Musculação" in tipo_map or raw_type in ("WeightTraining", "Strength"):
                qtd_forca += 1
            else:
                qtd_outros += 1

            tss_total += tss_val
            duracao_total_min += dur_min
            sessoes_lista.append(
                {
                    "data": str(atv.get("start_date_local") or "")[:10],
                    "tipo": tipo_map,
                    "nome": nome_map,
                    "duracao_min": dur_min,
                    "distancia_km": dist_km,
                    "tss": tss_val,
                    "bpm_medio": atv.get("average_heartrate"),
                    "detalhes": obs_map[:180] if obs_map else None,
                }
            )
    else:
        for ex in exercicios_neon:
            tipo_ex = str(ex.get("tipo") or "")
            if tipo_ex == "Fechamento Diário":
                continue
            dur_min = float(ex.get("duracao_min") or 0)
            tss_val = float(ex.get("carga_tss") or 0)
            if "Ride" in tipo_ex or "Bicicleta" in tipo_ex or "Ciclismo" in tipo_ex:
                qtd_ciclismo += 1
            elif "Musculação" in tipo_ex or "Hevy" in tipo_ex:
                qtd_forca += 1
            else:
                qtd_outros += 1
            tss_total += tss_val
            duracao_total_min += dur_min
            sessoes_lista.append(
                {
                    "data": ex["data"].strftime("%Y-%m-%d") if hasattr(ex.get("data"), "strftime") else str(ex.get("data")),
                    "tipo": tipo_ex,
                    "nome": ex.get("nome_treino") or tipo_ex,
                    "duracao_min": dur_min,
                    "distancia_km": float(ex.get("distancia_km") or 0),
                    "tss": tss_val,
                    "bpm_medio": ex.get("bpm_medio"),
                }
            )

    tsb_atual = round(ctl_atual - atl_atual, 1)

    return {
        "periodo": f"{dt_ini.strftime('%Y-%m-%d')} a {hoje.strftime('%Y-%m-%d')} ({dias} dias)",
        "antropometria": {
            "peso_inicial_7d_kg": round(peso_ini_7d, 1),
            "peso_atual_kg": round(peso_atual, 1),
            "tendencia_ewma_kg": round(tendencia_ewma, 1),
            "variacao_7d_kg": variacao_7d_kg,
            "meta_peso_alvo_kg": metas.get("peso_alvo"),
            "meta_kcal_diaria": metas.get("kcal"),
            "meta_macros_g": {
                "proteina": metas.get("prot"),
                "carbo": metas.get("carb"),
                "gordura": metas.get("gord"),
            },
        },
        "nutricao_7d": {
            "dias_registrados": dias_com_registro,
            "media_kcal_dia": int(media_kcal),
            "media_proteina_g_dia": media_prot,
            "proteina_g_por_kg_peso_atual": prot_g_kg,
            "media_carbo_g_dia": media_carb,
            "media_gordura_g_dia": media_gord,
            "dias_com_deficit_proteico": dias_deficit_proteico,
            "dias_com_deficit_calorico_acentuado": dias_deficit_calorico_acentuado,
            "historico_diario": resumo_dias_nutri,
        },
        "treinos_7d": {
            "total_sessoes": len(sessoes_lista),
            "sessoes_ciclismo": qtd_ciclismo,
            "sessoes_forca_hevy": qtd_forca,
            "sessoes_outros": qtd_outros,
            "duracao_total_min": round(duracao_total_min, 0),
            "tss_total_semana": round(tss_total, 1),
            "ctl_fitness": ctl_atual,
            "atl_fadiga_aguda": atl_atual,
            "tsb_prontidao": tsb_atual,
            "sessoes": sessoes_lista,
        },
        "sono_e_recuperacao_7d": {
            "noites_com_dados": len(noites_sono),
            "media_sono_horas": media_sono_h,
            "media_sleep_score": media_sleep_score,
            "media_resting_hr_bpm": media_rhr,
            "historico_noites": noites_sono,
        },
    }


def _extrair_blocos_tutor(raw_text: str) -> Dict[str, str]:
    """
    Extrai os 3 blocos estruturados do retorno do modelo Groq (seja via JSON ou texto com seções).
    """
    cleaned = re.sub(r"```(?:json)?", "", raw_text or "", flags=re.IGNORECASE).replace("```", "").strip()
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(0))
            if isinstance(data, dict):
                d1 = str(data.get("diagnostico_cruzado") or "").strip()
                d2 = str(data.get("prioridade_hoje") or "").strip()
                d3 = str(data.get("ponto_atencao_semana") or "").strip()
                if d1 or d2 or d3:
                    return {
                        "diagnostico_cruzado": d1 or "Sem observações adicionais.",
                        "prioridade_hoje": d2 or "Manter plano diário.",
                        "ponto_atencao_semana": d3 or "Monitorar consistência.",
                    }
        except Exception:
            pass

    # Fallback se o modelo respondeu em texto livre
    return {
        "diagnostico_cruzado": cleaned or "Sem resposta gerada pelo modelo.",
        "prioridade_hoje": "Consulte o diagnóstico acima para ajustar treino, sono e macronutrientes de hoje.",
        "ponto_atencao_semana": "Manter consistência nos registros de alimentação, treino e sono.",
    }


def gerar_parecer_tutor_groq(dias: int = 7) -> Tuple[bool, Dict[str, Any] | str]:
    """
    Coleta o contexto real dos últimos 7 dias e consulta o modelo GROQ_MODEL_TEXT
    com o system prompt de Tutor Fisiológico, retornando os 3 blocos acionáveis.
    """
    clean_key, key_status = diagnosticar_chave_groq()
    model_text = (
        os.getenv("GROQ_MODEL_TEXT") or GROQ_MODEL_TEXT or "openai/gpt-oss-120b"
    ).strip().strip('"').strip("'")
    modelo_ativo = model_text

    if not clean_key:
        return False, formatar_erro_diagnostico_groq(
            erro_titulo="GROQ_API_KEY não configurada no ambiente!",
            key_status=key_status,
            modelo=modelo_ativo,
        )

    contexto = montar_contexto_tutor(dias=dias)
    contexto_json_str = json.dumps(contexto, ensure_ascii=False, indent=2)

    system_prompt = (
        "Você é um tutor de fisiologia do exercício, nutrição esportiva e recuperação. "
        "Analise os dados reais dos últimos 7 dias (sono, FC de repouso, carga de treino CTL/ATL/TSB, "
        "peso e ingestão de macros) e responda em português do Brasil de forma direta, técnica e acionável, sem rodeios.\n\n"
        "Retorne APENAS um objeto JSON válido contendo EXATAMENTE estas 3 chaves:\n"
        "{\n"
        '  "diagnostico_cruzado": "Análise técnica cruzando Carga (TSS/CTL/ATL/TSB + Ciclismo/Hevy) x Sono/FC Repouso x Dieta (kcal e proteína g/kg + variação de peso).",\n'
        '  "prioridade_hoje": "Ação número 1 mais importante para hoje (ex: priorizar sono/recuperação, ajustar carboidrato pré-pedal, bater meta proteica pós-força ou manter ritmo), com números claros.",\n'
        '  "ponto_atencao_semana": "Principal gargalo ou risco fisiológico observado nos últimos 7 dias (ex: déficit proteico em dias de treino, queda no sono, TSB muito negativo ou falta de registros) e como corrigir."\n'
        "}"
    )

    user_prompt = (
        f"Aqui estão os dados fisiológicos, nutricionais e de treinamento reais dos últimos {dias} dias:\n\n"
        f"{contexto_json_str}\n\n"
        "Gere o parecer técnico estruturado nos 3 blocos solicitados."
    )

    raw_response = ""
    client: Optional[Groq] = None
    try:
        client = Groq(api_key=clean_key)
        kwargs: Dict[str, Any] = {
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "model": model_text,
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        }

        try:
            completion = client.chat.completions.create(**kwargs)
        except NotFoundError:
            completion = None
            last_err: Optional[Exception] = None
            for fb_model in FALLBACK_TEXT_MODELS:
                if fb_model == kwargs.get("model"):
                    continue
                try:
                    kwargs["model"] = fb_model
                    modelo_ativo = fb_model
                    completion = client.chat.completions.create(**kwargs)
                    break
                except Exception as e_fb:
                    last_err = e_fb
            if completion is None:
                raise last_err or NotFoundError("Modelo não encontrado", response=None, body=None)
        except Exception as call_err:
            if "response_format" in str(call_err).lower():
                kwargs.pop("response_format", None)
                completion = client.chat.completions.create(**kwargs)
            else:
                raise

        raw_response = completion.choices[0].message.content or ""
        blocos = _extrair_blocos_tutor(raw_response)
        return True, {
            "modelo_usado": modelo_ativo,
            "contexto": contexto,
            "blocos": blocos,
        }
    except Exception as ex:
        tb_str = traceback.format_exc()
        modelos_ativos: List[str] = []
        if client is not None and (isinstance(ex, NotFoundError) or "404" in str(ex) or "model_not_found" in str(ex).lower()):
            modelos_ativos = listar_modelos_disponiveis(client)
        return False, formatar_erro_diagnostico_groq(
            erro_titulo=f"{type(ex).__name__}: {str(ex)}",
            key_status=key_status,
            modelo=modelo_ativo,
            exc=ex,
            tb_str=tb_str,
            raw_response=raw_response,
            available_models=modelos_ativos,
        )
