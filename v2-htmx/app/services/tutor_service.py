import json
import os
import re
import traceback
from datetime import timedelta
from typing import Any, Dict, List, Optional, Tuple
import requests
from groq import Groq, NotFoundError
from app.config import GROQ_API_KEY, GROQ_MODEL_TEXT, get_now_br
from app.database import fetch_all, fetch_one
from app.services.groq_service import (
    FALLBACK_TEXT_MODELS,
    diagnosticar_chave_groq,
    formatar_erro_diagnostico_groq,
    listar_modelos_disponiveis,
)
from app.services.intervals_service import _get_intervals_creds, _mapear_atividade_intervals
from app.services.tracker_repo import get_metas, get_peso_historico


def _buscar_metas_reais_neon() -> Dict[str, Any]:
    """
    Busca as metas reais ativas diretamente da tabela public.perfil no banco Neon.
    """
    try:
        row = fetch_one("SELECT * FROM public.perfil ORDER BY id ASC LIMIT 1")
        if row:
            return {
                "meta_kcal_diaria": int(float(row.get("meta_kcal") or 1638)),
                "meta_proteina_g_diaria": int(float(row.get("meta_proteina") or 108)),
                "meta_carbo_g_diaria": int(float(row.get("meta_carbo") or 164)),
                "meta_gordura_g_diaria": int(float(row.get("meta_gordura") or 67)),
                "meta_peso_alvo_kg": float(row.get("meta_peso_alvo") or 120.0),
                "ritmo_semanal_kg": float(row.get("ritmo_semanal") or 0.8),
                "fator_atividade": float(row.get("fator_atividade") or 1.2),
            }
    except Exception:
        pass
    m = get_metas()
    return {
        "meta_kcal_diaria": int(m.get("kcal", 1638)),
        "meta_proteina_g_diaria": int(m.get("prot", 108)),
        "meta_carbo_g_diaria": int(m.get("carb", 164)),
        "meta_gordura_g_diaria": int(m.get("gord", 67)),
        "meta_peso_alvo_kg": float(m.get("peso_alvo", 120.0)),
        "ritmo_semanal_kg": float(m.get("ritmo", 0.8)),
        "fator_atividade": float(m.get("fator", 1.2)),
    }


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
    1. Metas Reais Cadastradas no Neon (public.perfil: kcal, proteína, carbo, gordura e peso alvo)
    2. Antropometria (peso inicial/atual do período e variação)
    3. Nutrição (Neon public.consumo: médias diárias comparadas com as metas reais do Neon)
    4. Treinos (Intervals /activities + Neon public.exercicios: sessões, tipos, duração, TSS, CTL, ATL, TSB)
    5. Sono e Recuperação (Intervals /wellness: horas de sono sleepSecs/3600, sleepScore e restingHR)
    """
    hoje = get_now_br().date()
    dt_ini = hoje - timedelta(days=dias)
    metas_reais = _buscar_metas_reais_neon()

    meta_kcal = float(metas_reais["meta_kcal_diaria"])
    meta_prot = float(metas_reais["meta_proteina_g_diaria"])
    meta_carb = float(metas_reais["meta_carbo_g_diaria"])
    meta_gord = float(metas_reais["meta_gordura_g_diaria"])

    # 1. Antropometria
    peso_hist = get_peso_historico(limit=30)
    peso_atual = float(peso_hist.get("peso_atual") or 105.0)
    tendencia_ewma = float(peso_hist.get("tendencia_atual") or peso_atual)

    pesos_7d = fetch_all(
        """
        SELECT data, peso_kg
        FROM public.peso
        WHERE DATE(data) >= :d1 AND DATE(data) <= :d2 AND peso_kg IS NOT NULL
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
    meta_prot_g_kg_configurada = round(meta_prot / max(peso_atual, 1.0), 2)

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

    dias_abaixo_meta_prot: List[str] = []
    dias_abaixo_meta_kcal: List[str] = []
    resumo_dias_nutri: List[Dict[str, Any]] = []

    for r in consumo_diario:
        d_str = r["data"].strftime("%Y-%m-%d") if hasattr(r["data"], "strftime") else str(r["data"])
        k_val = float(r["kcal"] or 0)
        p_val = float(r["proteina_g"] or 0)
        c_val = float(r["carbo_g"] or 0)
        g_val = float(r["gordura_g"] or 0)

        if p_val < (meta_prot * 0.85):
            dias_abaixo_meta_prot.append(f"{d_str} ({p_val:.0f}g vs meta real {meta_prot:.0f}g)")
        if k_val < (meta_kcal * 0.75):
            dias_abaixo_meta_kcal.append(f"{d_str} ({k_val:.0f} kcal vs meta real {meta_kcal:.0f} kcal)")

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
                    "detalhes": obs_map[:160] if obs_map else None,
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
        "metas_reais_cadastradas_neon": {
            "meta_kcal_diaria": int(meta_kcal),
            "meta_proteina_g_diaria": int(meta_prot),
            "meta_proteina_g_por_kg_equivalente": meta_prot_g_kg_configurada,
            "meta_carbo_g_diaria": int(meta_carb),
            "meta_gordura_g_diaria": int(meta_gord),
            "meta_peso_alvo_kg": metas_reais["meta_peso_alvo_kg"],
        },
        "antropometria": {
            "peso_inicial_7d_kg": round(peso_ini_7d, 1),
            "peso_atual_kg": round(peso_atual, 1),
            "tendencia_ewma_kg": round(tendencia_ewma, 1),
            "variacao_7d_kg": variacao_7d_kg,
            "meta_peso_alvo_kg": metas_reais["meta_peso_alvo_kg"],
        },
        "nutricao_7d": {
            "dias_registrados": dias_com_registro,
            "media_kcal_dia": int(media_kcal),
            "saldo_kcal_vs_meta_real_neon": int(round(media_kcal - meta_kcal)),
            "pct_meta_kcal_atingida": int(round((media_kcal / max(meta_kcal, 1.0)) * 100)),
            "media_proteina_g_dia": media_prot,
            "saldo_proteina_g_vs_meta_real_neon": round(media_prot - meta_prot, 1),
            "pct_meta_proteina_atingida": int(round((media_prot / max(meta_prot, 1.0)) * 100)),
            "proteina_g_por_kg_peso_atual": prot_g_kg,
            "media_carbo_g_dia": media_carb,
            "saldo_carbo_g_vs_meta_real_neon": round(media_carb - meta_carb, 1),
            "media_gordura_g_dia": media_gord,
            "saldo_gordura_g_vs_meta_real_neon": round(media_gord - meta_gord, 1),
            "dias_abaixo_da_meta_real_de_proteina": dias_abaixo_meta_prot,
            "dias_abaixo_da_meta_real_de_kcal": dias_abaixo_meta_kcal,
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


def _normalizar_status(st: Any) -> str:
    s = str(st or "info").lower().strip()
    if s in ("alerta", "warn", "warning", "erro", "danger", "critico", "crítico"):
        return "alerta"
    if s in ("ok", "sucesso", "bom", "otimo", "ótimo", "verde"):
        return "ok"
    return "info"


def _extrair_estrutura_tutor(raw_text: str) -> Dict[str, Any]:
    """
    Faz o parse e normaliza o JSON estrito retornado pelo Groq com as listas:
    - diagnostico: [{"status": "alerta|ok|info", "titulo": "...", "texto": "..."}]
    - prioridades_hoje: [{"acao": "...", "detalhe": "..."}]
    - pontos_atencao: ["...", "..."]
    """
    cleaned = re.sub(r"```(?:json)?", "", raw_text or "", flags=re.IGNORECASE).replace("```", "").strip()
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    candidato = match.group(0) if match else cleaned

    parsed = json.loads(candidato)
    if not isinstance(parsed, dict):
        raise ValueError("O retorno do modelo não é um objeto JSON.")

    diag_raw = parsed.get("diagnostico") or []
    diagnostico: List[Dict[str, str]] = []
    if isinstance(diag_raw, list):
        for item in diag_raw:
            if isinstance(item, dict):
                diagnostico.append(
                    {
                        "status": _normalizar_status(item.get("status")),
                        "titulo": str(item.get("titulo") or "Tópico").strip(),
                        "texto": str(item.get("texto") or "").strip(),
                    }
                )

    prio_raw = parsed.get("prioridades_hoje") or []
    prioridades_hoje: List[Dict[str, str]] = []
    if isinstance(prio_raw, list):
        for item in prio_raw:
            if isinstance(item, dict):
                prioridades_hoje.append(
                    {
                        "acao": str(item.get("acao") or "Ação").strip(),
                        "detalhe": str(item.get("detalhe") or "").strip(),
                    }
                )
            elif isinstance(item, str) and item.strip():
                prioridades_hoje.append({"acao": "Prioridade", "detalhe": item.strip()})

    pts_raw = parsed.get("pontos_atencao") or []
    pontos_atencao: List[str] = []
    if isinstance(pts_raw, list):
        for item in pts_raw:
            if isinstance(item, str) and item.strip():
                pontos_atencao.append(item.strip())
            elif isinstance(item, dict):
                txt = str(item.get("texto") or item.get("detalhe") or "").strip()
                if txt:
                    pontos_atencao.append(txt)

    return {
        "diagnostico": diagnostico,
        "prioridades_hoje": prioridades_hoje,
        "pontos_atencao": pontos_atencao,
    }


def gerar_parecer_tutor_groq(dias: int = 7) -> Tuple[bool, Dict[str, Any] | str]:
    """
    Coleta o contexto real dos últimos 7 dias (incluindo as metas reais cadastradas no Neon)
    e consulta o modelo GROQ_MODEL_TEXT forçando response_format={"type": "json_object"}
    com frases curtas e escaneáveis.
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
    metas_neon = contexto["metas_reais_cadastradas_neon"]
    contexto_json_str = json.dumps(contexto, ensure_ascii=False, indent=2)

    system_prompt = f"""Você é um tutor de fisiologia do exercício, nutrição esportiva e recuperação.
Analise os dados reais dos últimos 7 dias (sono, FC de repouso, carga de treino CTL/ATL/TSB, peso e ingestão de macros) e responda em português do Brasil de forma direta, técnica e acionável, sem rodeios.

REGRAS OBRIGATÓRIAS DE METAS REAIS DO NEON:
- As metas reais cadastradas pelo usuário no banco Neon são EXATAMENTE:
  * Calorias: {metas_neon['meta_kcal_diaria']} kcal/dia
  * Proteína: {metas_neon['meta_proteina_g_diaria']} g/dia (equivalente a {metas_neon['meta_proteina_g_por_kg_equivalente']} g/kg)
  * Carboidrato: {metas_neon['meta_carbo_g_diaria']} g/dia
  * Gordura: {metas_neon['meta_gordura_g_diaria']} g/dia
  * Peso Alvo: {metas_neon['meta_peso_alvo_kg']} kg
- NUNCA assuma ou invente metas genéricas de literatura (como 2000 kcal, 2150 kcal ou 1.8 g/kg).
- Sempre compare o consumo médio dos últimos 7 dias EXCLUSIVAMENTE contra as metas reais acima ({metas_neon['meta_kcal_diaria']} kcal e {metas_neon['meta_proteina_g_diaria']}g de proteína).

FORMATO DE SAÍDA OBRIGATÓRIO:
Retorne APENAS um objeto JSON válido (sem markdown e sem texto corrido longo), seguindo ESTRITAMENTE este esquema e limites de palavras:
{{
  "diagnostico": [
    {{"status": "alerta|ok|info", "titulo": "Carga & Fadiga", "texto": "Frase curta (máx. 14 palavras)"}},
    {{"status": "alerta|ok|info", "titulo": "Sono & Recuperação", "texto": "Frase curta (máx. 14 palavras)"}},
    {{"status": "alerta|ok|info", "titulo": "Balanço Nutricional", "texto": "Frase curta comparando consumo médio com a meta real ({metas_neon['meta_kcal_diaria']} kcal / {metas_neon['meta_proteina_g_diaria']}g P)"}}
  ],
  "prioridades_hoje": [
    {{"acao": "Título curto da ação 1", "detalhe": "Instrução prática direta (máx. 15 palavras)"}},
    {{"acao": "Título curto da ação 2", "detalhe": "Instrução prática direta (máx. 15 palavras)"}},
    {{"acao": "Título curto da ação 3", "detalhe": "Instrução prática direta (máx. 15 palavras)"}}
  ],
  "pontos_atencao": [
    "Bullet curto 1 sobre risco da semana (máx. 15 palavras)",
    "Bullet curto 2 sobre ajuste prático (máx. 15 palavras)"
  ]
}}"""

    user_prompt = (
        f"Dados reais dos últimos {dias} dias (com metas reais do Neon em 'metas_reais_cadastradas_neon'):\n\n"
        f"{contexto_json_str}\n\n"
        "Retorne apenas o JSON estruturado com frases curtas e escaneáveis."
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
            "temperature": 0.15,
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

        raw_response = completion.choices[0].message.content or ""
        estrutura = _extrair_estrutura_tutor(raw_response)
        return True, {
            "modelo_usado": modelo_ativo,
            "contexto": contexto,
            "parecer": estrutura,
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
