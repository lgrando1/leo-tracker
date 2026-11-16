import base64
import io
import json
import os
import re
import time
import traceback
from datetime import date
from typing import Any, Dict, List, Optional, Tuple
from groq import Groq, NotFoundError
from PIL import Image
from app.config import GROQ_API_KEY, GROQ_MODEL_TEXT, GROQ_MODEL_VISION, get_now_br

FALLBACK_TEXT_MODELS = [
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
    "llama-3.1-8b-instant",
]


def diagnosticar_chave_groq(api_key: Optional[str] = None) -> Tuple[str, str]:
    """
    Retorna (clean_key, descricao_status_chave) sem expor o segredo completo.
    Ex: ('gsk_...', 'Sim (inicia com gsk_abcd..., 56 chars)') ou ('', 'Não (vazia ou ausente no ambiente)')
    """
    raw_key = api_key or os.getenv("GROQ_API_KEY") or GROQ_API_KEY or ""
    clean_key = raw_key.strip().strip('"').strip("'").strip()
    if not clean_key:
        return "", "Não (variável GROQ_API_KEY vazia ou ausente no ambiente)"
    prefixo = clean_key[:8] if len(clean_key) >= 8 else clean_key[:4]
    return clean_key, f"Sim (inicia com {prefixo}..., {len(clean_key)} caracteres)"


def listar_modelos_disponiveis(client: Groq) -> List[str]:
    """Retorna a lista ordenada de IDs de modelos ativos na chave via client.models.list()."""
    try:
        models_resp = client.models.list()
        data = getattr(models_resp, "data", []) or []
        return sorted([str(m.id) for m in data if getattr(m, "id", None)])
    except Exception:
        return []


def formatar_erro_diagnostico_groq(
    erro_titulo: str,
    key_status: str,
    modelo: str,
    exc: Optional[BaseException] = None,
    tb_str: Optional[str] = None,
    raw_response: Optional[str] = None,
    available_models: Optional[List[str]] = None,
) -> str:
    """Monta texto detalhado de diagnóstico para exibição na caixa vermelha do frontend."""
    linhas = [
        "🚨 DIAGNÓSTICO GROQ API",
        f"• Chave detectada (GROQ_API_KEY): {key_status}",
        f"• Modelo configurado na chamada: {modelo}",
    ]
    if exc is not None:
        linhas.append(f"• Exceção ({type(exc).__name__}): {str(exc)}")
    else:
        linhas.append(f"• Detalhe do erro: {erro_titulo}")

    if available_models:
        linhas.append(
            f"\n--- Modelos ativos na chave (client.models.list() · {len(available_models)} modelos) ---\n"
            + ", ".join(available_models)
        )

    if raw_response:
        preview = raw_response[:400]
        linhas.append(f"\n--- Texto bruto retornado pela API (primeiros 400 chars) ---\n{preview}")

    if tb_str:
        tb_resumido = "\n".join(tb_str.strip().splitlines()[-10:])
        linhas.append(f"\n--- Traceback resumido ---\n{tb_resumido}")

    return "\n".join(linhas)


def ping_groq() -> Dict[str, Any]:
    """
    Testa instanciar o cliente Groq, lista todos os modelos ativos via client.models.list()
    e envia um prompt mínimo ('Responda apenas: OK') usando GROQ_MODEL_TEXT (padrão 'openai/gpt-oss-120b').
    """
    clean_key, key_status = diagnosticar_chave_groq()
    modelo_texto_env = (
        os.getenv("GROQ_MODEL_TEXT") or GROQ_MODEL_TEXT or "openai/gpt-oss-120b"
    ).strip().strip('"').strip("'")
    modelo_vision_env = (
        os.getenv("GROQ_MODEL_VISION") or GROQ_MODEL_VISION or "qwen/qwen3.8-27b"
    ).strip().strip('"').strip("'")
    modelo_teste = modelo_texto_env

    t0 = time.perf_counter()
    if not clean_key:
        return {
            "ok": False,
            "status": "ERRO",
            "key_detected": key_status,
            "model_tested": modelo_teste,
            "configured_text_model": modelo_texto_env,
            "configured_vision_model": modelo_vision_env,
            "available_models": [],
            "elapsed_ms": 0,
            "response": None,
            "error": "GROQ_API_KEY não encontrada no ambiente.",
            "traceback": None,
        }

    available_models: List[str] = []
    try:
        client = Groq(api_key=clean_key)
        available_models = listar_modelos_disponiveis(client)

        completion = client.chat.completions.create(
            messages=[{"role": "user", "content": "Responda apenas: OK"}],
            model=modelo_teste,
            temperature=0.0,
            max_tokens=16,
        )
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        resposta = (completion.choices[0].message.content or "").strip()
        return {
            "ok": True,
            "status": "OK",
            "key_detected": key_status,
            "model_tested": modelo_teste,
            "configured_text_model": modelo_texto_env,
            "configured_vision_model": modelo_vision_env,
            "available_models": available_models,
            "elapsed_ms": elapsed_ms,
            "response": resposta,
            "error": None,
            "traceback": None,
        }
    except Exception as e:
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        tb = traceback.format_exc()
        return {
            "ok": False,
            "status": "ERRO",
            "key_detected": key_status,
            "model_tested": modelo_teste,
            "configured_text_model": modelo_texto_env,
            "configured_vision_model": modelo_vision_env,
            "available_models": available_models,
            "elapsed_ms": elapsed_ms,
            "response": None,
            "error": f"{type(e).__name__}: {str(e)}",
            "traceback": "\n".join(tb.strip().splitlines()[-10:]),
        }


def otimizar_imagem_base64(imagem_bytes: bytes, max_dim: int = 1024, quality: int = 85) -> str:
    """Redimensiona e comprime a imagem em JPEG (< 500 KB) antes de enviar à API da Groq."""
    img = Image.open(io.BytesIO(imagem_bytes))
    if img.mode in ("RGBA", "P", "LA"):
        img = img.convert("RGB")
    img.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality, optimize=True)
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def normalizar_item_alimento(item: Dict[str, Any], data_padrao_str: str) -> Dict[str, Any]:
    """Garante que todas as chaves estruturadas de macros e micronutrientes existam com tipos válidos."""
    def _to_float(val: Any, default: float = 0.0) -> float:
        if val is None or val == "":
            return default
        try:
            if isinstance(val, str):
                val = val.replace(",", ".").strip()
            return float(val)
        except Exception:
            return default

    return {
        "data": str(item.get("data") or data_padrao_str).strip(),
        "alimento": str(item.get("alimento") or item.get("nome") or "Alimento").strip(),
        "quantidade_g": _to_float(item.get("quantidade_g", item.get("quantidade", 0))),
        "kcal": _to_float(item.get("kcal", item.get("calorias", 0))),
        "p": _to_float(item.get("p", item.get("proteina", 0))),
        "c": _to_float(item.get("c", item.get("carbo", item.get("carboidrato", 0)))),
        "g": _to_float(item.get("g", item.get("gordura", item.get("lipideos", 0)))),
        "gluten": str(item.get("gluten") or "Não informado").strip(),
        "ferro_mg": _to_float(item.get("ferro_mg", item.get("ferro", 0))),
        "b12_mcg": _to_float(item.get("b12_mcg", item.get("b12", 0))),
        "zinco_mg": _to_float(item.get("zinco_mg", item.get("zinco", 0))),
        "magnesio_mg": _to_float(item.get("magnesio_mg", item.get("magnesio", 0))),
    }


def normalizar_payload_nutricional(
    content: Any, data_padrao_str: str, analise_padrao: str = "Refeição processada com sucesso."
) -> Dict[str, Any]:
    """Valida e padroniza o dicionário final com as chaves 'analise' e 'alimentos'."""
    if isinstance(content, list):
        lista_bruta = content
        analise = analise_padrao
    elif isinstance(content, dict):
        analise = str(content.get("analise") or analise_padrao).strip()
        if "alimentos" in content and isinstance(content["alimentos"], list):
            lista_bruta = content["alimentos"]
        elif any(k in content for k in ("alimento", "nome", "kcal", "p", "proteina")):
            lista_bruta = [content]
        else:
            lista_bruta = []
    else:
        lista_bruta = []
        analise = analise_padrao

    alimentos_norm: List[Dict[str, Any]] = [
        normalizar_item_alimento(it, data_padrao_str)
        for it in lista_bruta
        if isinstance(it, dict)
    ]
    return {"analise": analise, "alimentos": alimentos_norm}


def extrair_e_parsear_json(
    texto_bruto: str, data_padrao_str: str, analise_padrao: str = "Refeição processada com sucesso."
) -> Tuple[bool, Dict[str, Any] | str]:
    """
    Sanitiza cercas Markdown (```json e ```), extrai o bloco JSON via regex
    re.search(r"\\{.*\\}", texto, re.DOTALL) e executa json.loads() com captura
    de json.JSONDecodeError exibindo os primeiros 200 caracteres da resposta bruta.
    """
    raw = (texto_bruto or "").strip()
    if not raw:
        return False, "Erro de parsing JSON: resposta vazia do modelo."

    sem_cercas = re.sub(r"```(?:json)?", "", raw, flags=re.IGNORECASE).replace("```", "").strip()

    match_obj = re.search(r"\{.*\}", sem_cercas, re.DOTALL)
    if match_obj:
        candidato = match_obj.group(0).strip()
    else:
        match_arr = re.search(r"\[.*\]", sem_cercas, re.DOTALL)
        candidato = match_arr.group(0).strip() if match_arr else sem_cercas

    try:
        parsed = json.loads(candidato)
    except json.JSONDecodeError as je:
        preview = raw[:200].replace("\n", " ")
        return (
            False,
            f"json.JSONDecodeError: {je.msg} (pos {je.pos}). "
            f"Primeiros 200 caracteres: {preview!r}",
        )

    payload = normalizar_payload_nutricional(parsed, data_padrao_str, analise_padrao=analise_padrao)
    if not payload.get("alimentos"):
        preview = raw[:200].replace("\n", " ")
        return (
            False,
            f"JSON válido, mas a lista 'alimentos' está vazia ou ausente. "
            f"Primeiros 200 caracteres: {preview!r}",
        )
    return True, payload


def tentar_parse_json_direto(
    texto_usuario: str, data_ref: Optional[date] = None
) -> Tuple[bool, Optional[Dict[str, Any]], Optional[str]]:
    """
    Verifica se o texto enviado pelo usuário é um JSON colado diretamente
    (começa com '{' e termina com '}', ou começa com '[' e termina com ']').
    """
    if not texto_usuario:
        return False, None, None

    cleaned = re.sub(r"```(?:json)?", "", texto_usuario, flags=re.IGNORECASE).replace("```", "").strip()
    is_json_obj = cleaned.startswith("{") and cleaned.endswith("}")
    is_json_arr = cleaned.startswith("[") and cleaned.endswith("]")

    if not (is_json_obj or is_json_arr):
        return False, None, None

    data_hoje_str = (data_ref or get_now_br().date()).strftime("%Y-%m-%d")
    ok, res = extrair_e_parsear_json(
        cleaned,
        data_padrao_str=data_hoje_str,
        analise_padrao="📦 JSON importado diretamente (bypass da API Groq).",
    )
    if ok and isinstance(res, dict):
        return True, res, None
    return True, None, str(res)


def processar_texto_ia(
    texto_usuario: str,
    api_key: Optional[str] = None,
    imagem_bytes: Optional[bytes] = None,
    data_ref: Optional[date] = None,
) -> Tuple[bool, Dict[str, Any] | str]:
    """
    Processa descrição alimentar (texto livre, JSON direto ou imagem) usando o SDK da Groq.
    Se o modelo configurado retornar NotFoundError (404), tenta fallbacks compatíveis
    ('openai/gpt-oss-120b', 'openai/gpt-oss-20b', 'llama-3.1-8b-instant') ou lista os
    modelos disponíveis em client.models.list() na mensagem de erro.
    """
    data_hoje_str = (data_ref or get_now_br().date()).strftime("%Y-%m-%d")

    if texto_usuario and not imagem_bytes:
        is_direct_json, direct_payload, direct_err = tentar_parse_json_direto(texto_usuario, data_ref=data_ref)
        if is_direct_json:
            if direct_payload is not None:
                return True, direct_payload
            _, key_status = diagnosticar_chave_groq(api_key)
            return False, formatar_erro_diagnostico_groq(
                erro_titulo=direct_err or "JSON direto inválido",
                key_status=key_status,
                modelo="Bypass JSON Direto (sem chamada à IA)",
                raw_response=texto_usuario,
            )

    clean_key, key_status = diagnosticar_chave_groq(api_key)
    model_text = (os.getenv("GROQ_MODEL_TEXT") or GROQ_MODEL_TEXT or "openai/gpt-oss-120b").strip().strip('"').strip("'")
    model_vision = (os.getenv("GROQ_MODEL_VISION") or GROQ_MODEL_VISION or "qwen/qwen3.8-27b").strip().strip('"').strip("'")
    modelo_ativo = model_vision if imagem_bytes is not None else model_text

    if not clean_key:
        return False, formatar_erro_diagnostico_groq(
            erro_titulo="GROQ_API_KEY não configurada!",
            key_status=key_status,
            modelo=modelo_ativo,
        )

    prompt_system = f"""
Aja como Nutricionista Matemático. Hoje: {data_hoje_str}.
DIRETRIZES:
1. Identifique cada alimento (por texto ou visualmente na imagem, usando o prato/talheres como escala para estimar gramas).
2. Se houver comanda, rótulo ou tabela nutricional na imagem, leia os valores exatos.
3. MULTIPLIQUE a densidade calórica padrão pelo peso estimado/informado.
4. GORDURA OCULTA: Se for fritura/grelhado, adicione gordura extra.
5. MICRONUTRIENTES: Estime Ferro, B12, Zinco e Magnésio por engenharia reversa.
SAÍDA: Retorne APENAS um objeto JSON válido (sem texto fora do JSON e sem blocos markdown), contendo EXATAMENTE estas chaves:
{{
  "analise": "Texto curto",
  "alimentos": [
    {{
      "data": "{data_hoje_str}",
      "alimento": "Nome",
      "quantidade_g": 0,
      "kcal": 0,
      "p": 0,
      "c": 0,
      "g": 0,
      "gluten": "txt",
      "ferro_mg": 0,
      "b12_mcg": 0,
      "zinco_mg": 0,
      "magnesio_mg": 0
    }}
  ]
}}
""".strip()

    raw_response = ""
    client: Optional[Groq] = None
    try:
        client = Groq(api_key=clean_key)

        if imagem_bytes is not None:
            b64_img = otimizar_imagem_base64(imagem_bytes)
            texto_prompt = (
                texto_usuario.strip()
                if texto_usuario and texto_usuario.strip()
                else "Analise visualmente esta refeição/rótulo e estime todos os alimentos, pesos em gramas, macros e micronutrientes no formato JSON solicitado."
            )
            user_content = [
                {"type": "text", "text": texto_prompt},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{b64_img}"},
                },
            ]
            kwargs: Dict[str, Any] = {
                "messages": [
                    {"role": "system", "content": prompt_system},
                    {"role": "user", "content": user_content},
                ],
                "model": model_vision,
                "temperature": 0.1,
                "reasoning_effort": "none",
                "response_format": {"type": "json_object"},
            }
        else:
            kwargs = {
                "messages": [
                    {"role": "system", "content": prompt_system},
                    {"role": "user", "content": texto_usuario},
                ],
                "model": model_text,
                "temperature": 0.1,
                "response_format": {"type": "json_object"},
            }

        try:
            completion = client.chat.completions.create(**kwargs)
        except NotFoundError:
            # Se for chamada de texto e o modelo configurado deu 404, tenta os fallbacks permitidos
            if imagem_bytes is None:
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
            else:
                raise
        except Exception as call_err:
            err_msg = str(call_err).lower()
            if "reasoning_effort" in err_msg or "response_format" in err_msg or isinstance(call_err, TypeError):
                kwargs.pop("reasoning_effort", None)
                if "response_format" in err_msg:
                    kwargs.pop("response_format", None)
                completion = client.chat.completions.create(**kwargs)
            else:
                raise

        raw_response = completion.choices[0].message.content or ""
        ok_parse, resultado_parse = extrair_e_parsear_json(raw_response, data_padrao_str=data_hoje_str)
        if not ok_parse:
            return False, formatar_erro_diagnostico_groq(
                erro_titulo=str(resultado_parse),
                key_status=key_status,
                modelo=modelo_ativo,
                raw_response=raw_response,
            )
        return True, resultado_parse
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


def analisar_refeicao_groq(
    texto_usuario: str,
    data_ref: Optional[date] = None,
    imagem_bytes: Optional[bytes] = None,
) -> Tuple[bool, Dict[str, Any] | str]:
    """Alias compatível com main.py que delega para processar_texto_ia."""
    api_key = (os.getenv("GROQ_API_KEY") or GROQ_API_KEY or "").strip().strip('"').strip("'")
    return processar_texto_ia(
        texto_usuario=texto_usuario,
        api_key=api_key,
        imagem_bytes=imagem_bytes,
        data_ref=data_ref,
    )
