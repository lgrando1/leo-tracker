import base64
import io
import json
import os
from datetime import date
from typing import Any, Dict, Optional, Tuple
from groq import Groq
from PIL import Image
from app.config import GROQ_API_KEY, GROQ_MODEL_TEXT, GROQ_MODEL_VISION, get_now_br


def otimizar_imagem_base64(imagem_bytes: bytes, max_dim: int = 1024, quality: int = 85) -> str:
    """Redimensiona e comprime a imagem em JPEG (< 500 KB) antes de enviar à API da Groq."""
    img = Image.open(io.BytesIO(imagem_bytes))
    if img.mode in ("RGBA", "P", "LA"):
        img = img.convert("RGB")
    img.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality, optimize=True)
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def tentar_parse_json_direto(texto_usuario: str) -> Optional[Dict[str, Any]]:
    """
    Verifica se o usuário colou diretamente um JSON estruturado (lista ou objeto),
    mantendo compatibilidade com o fluxo original do @app.py.
    """
    if not texto_usuario:
        return None
    cleaned = texto_usuario.replace("```json", "").replace("```", "").strip()
    s, e = cleaned.find("["), cleaned.rfind("]")
    if s == -1 and cleaned.startswith("{"):
        s, e = cleaned.find("{"), cleaned.rfind("}")
    if s == -1 or e == -1:
        return None
    try:
        parsed = json.loads(cleaned[s : e + 1])
        if isinstance(parsed, list):
            return {"analise": "JSON importado diretamente.", "alimentos": parsed}
        if isinstance(parsed, dict):
            if "alimentos" in parsed and isinstance(parsed["alimentos"], list):
                return parsed
            return {"analise": "Item JSON importado diretamente.", "alimentos": [parsed]}
    except Exception:
        return None
    return None


def processar_texto_ia(
    texto_usuario: str,
    api_key: Optional[str] = None,
    imagem_bytes: Optional[bytes] = None,
    data_ref: Optional[date] = None,
) -> Tuple[bool, Dict[str, Any] | str]:
    """
    Função equivalente a processar_texto_ia de @app.py, com limpeza de GROQ_API_KEY
    e captura explícita de qualquer exceção para exibição na interface HTMX.
    """
    if texto_usuario and not imagem_bytes:
        direto = tentar_parse_json_direto(texto_usuario)
        if direto is not None:
            return True, direto

    raw_key = api_key or os.getenv("GROQ_API_KEY") or GROQ_API_KEY or ""
    clean_key = raw_key.strip().strip('"').strip("'").strip()
    if not clean_key:
        return False, "Erro: GROQ_API_KEY não configurada nas variáveis de ambiente (.env / Vercel)!"

    model_text = (os.getenv("GROQ_MODEL_TEXT") or GROQ_MODEL_TEXT or "openai/gpt-oss-120b").strip().strip('"').strip("'")
    model_vision = (os.getenv("GROQ_MODEL_VISION") or GROQ_MODEL_VISION or "qwen/qwen3.8-27b").strip().strip('"').strip("'")

    data_hoje_str = (data_ref or get_now_br().date()).strftime("%Y-%m-%d")

    prompt_system = f"""
Aja como Nutricionista Matemático. Hoje: {data_hoje_str}.
DIRETRIZES:
1. Identifique cada alimento (por texto ou visualmente na imagem, usando o prato/talheres como escala para estimar gramas).
2. Se houver comanda, rótulo ou tabela nutricional na imagem, leia os valores exatos.
3. MULTIPLIQUE a densidade calórica padrão pelo peso estimado/informado.
4. GORDURA OCULTA: Se for fritura/grelhado, adicione gordura extra.
5. MICRONUTRIENTES: Estime Ferro, B12, Zinco e Magnésio por engenharia reversa.
SAÍDA: Retorne APENAS JSON válido.
Formato: {{"analise": "Texto curto", "alimentos": [{{"data": "YYYY-MM-DD", "alimento": "Nome",
"quantidade_g": 0, "kcal": 0, "p": 0, "c": 0, "g": 0, "gluten": "txt",
"ferro_mg": 0, "b12_mcg": 0, "zinco_mg": 0, "magnesio_mg": 0}}]}}
""".strip()

    try:
        client = Groq(api_key=clean_key)

        if imagem_bytes is not None:
            b64_img = otimizar_imagem_base64(imagem_bytes)
            texto_prompt = (
                texto_usuario.strip()
                if texto_usuario and texto_usuario.strip()
                else "Analise visualmente esta refeição/rótulo e estime todos os alimentos, pesos em gramas, macros e micronutrientes."
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
        except TypeError:
            # Fallback caso a versão do SDK não aceite reasoning_effort como argumento direto
            kwargs.pop("reasoning_effort", None)
            completion = client.chat.completions.create(**kwargs)

        raw = (
            (completion.choices[0].message.content or "")
            .replace("```json", "")
            .replace("```", "")
            .strip()
        )
        s, e = raw.find("{"), raw.rfind("}")
        if s != -1 and e != -1:
            raw = raw[s : e + 1]
        content = json.loads(raw)
        if isinstance(content, list):
            content = {"analise": "Processado", "alimentos": content}
        return True, content
    except Exception as ex:
        return False, f"Erro: {str(ex)}"


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
