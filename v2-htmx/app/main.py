from datetime import date, datetime, timedelta
import os
import pathlib
import secrets
import sys
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, unquote

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, Response, UploadFile, status
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# Garante que a raiz de v2-htmx/ esteja no sys.path no ambiente serverless da Vercel
BASE_DIR = pathlib.Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from app.config import APP_PASSWORD, APP_USER, get_now_br
from app.database import get_engine
from app.services.groq_service import analisar_refeicao_groq
from app.services.intervals_service import sincronizar_treinos_recentes
from app.services.tracker_repo import (
    DEFAULT_METAS,
    atualizar_metas,
    calc_bf_weltman,
    get_consumo_dia,
    get_historico_consumo,
    get_medidas_historico,
    get_metas,
    get_peso_historico,
    get_tempo_jejum,
    get_treinos_dia,
    inserir_alimentos_consumo,
    inserir_exercicio_manual,
    inserir_peso,
    registrar_avaliacao_corporal,
    remover_consumo,
    remover_exercicio,
    remover_medida,
    remover_peso,
    salvar_fechamento_passos,
)

# ============================================================================
# AUTENTICAÇÃO NATIVA HTTP BASIC (100% STATELESS PARA VERCEL SERVERLESS + HTMX)
# ============================================================================
security = HTTPBasic()


def verificar_acesso(credentials: HTTPBasicCredentials = Depends(security)) -> str:
    """
    Valida usuário e senha via HTTP Basic Auth usando secrets.compare_digest.
    - Usuário padrão: 'leo' (ou variável APP_USER do ambiente)
    - Senha padrão: lida de APP_PASSWORD (ou PASSWORD) do ambiente, fallback 'admin'
    """
    expected_user = (os.getenv("APP_USER") or APP_USER or "leo").strip()
    expected_pass = (
        os.getenv("APP_PASSWORD")
        or os.getenv("PASSWORD")
        or APP_PASSWORD
        or "admin"
    ).strip()

    user_ok = secrets.compare_digest(
        credentials.username.encode("utf-8"), expected_user.encode("utf-8")
    )
    pass_ok = secrets.compare_digest(
        credentials.password.encode("utf-8"), expected_pass.encode("utf-8")
    )

    if not (user_ok and pass_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Acesso restrito",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


app = FastAPI(
    title="Leo Tracker Pro · v2 HTMX",
    description="Aplicação FastAPI + Jinja2 + HTMX + Tailwind CSS protegida com HTTP Basic Auth.",
    version="2.2.0",
    dependencies=[Depends(verificar_acesso)],
)

# Resolução absoluta de templates e static para compatibilidade com Vercel Serverless e execução local
ROOT_TEMPLATES_DIR = pathlib.Path(__file__).resolve().parent.parent / "templates"
APP_TEMPLATES_DIR = pathlib.Path(__file__).resolve().parent / "templates"
TEMPLATES_DIR = ROOT_TEMPLATES_DIR if ROOT_TEMPLATES_DIR.exists() else APP_TEMPLATES_DIR
templates = Jinja2Templates(
    directory=[str(d) for d in (ROOT_TEMPLATES_DIR, APP_TEMPLATES_DIR) if d.exists()]
    or str(TEMPLATES_DIR)
)

STATIC_DIR = pathlib.Path(__file__).resolve().parent.parent / "static"
if not STATIC_DIR.exists():
    STATIC_DIR = pathlib.Path(__file__).resolve().parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def _render_template(request: Request, template_name: str, context: Dict[str, Any]) -> Response:
    """Renderiza template Jinja2 de forma compatível com qualquer versão do Starlette/FastAPI."""
    context["request"] = request
    try:
        return templates.TemplateResponse(request=request, name=template_name, context=context)
    except TypeError:
        return templates.TemplateResponse(template_name, context)


def _resolve_vercel_path(request: Request) -> str:
    """
    Normaliza o caminho caso o rewrite da Vercel (/(.*) -> /app/main.py)
    encaminhe scope['path'] como '/app/main.py'.
    """
    raw_path = request.scope.get("path") or request.url.path or "/"

    if raw_path in ("/app/main.py", "/app/main.py/"):
        for header_name in ("x-forwarded-uri", "x-original-url", "x-rewrite-url"):
            h_val = request.headers.get(header_name)
            if h_val:
                clean_h = h_val.split("?", 1)[0]
                if clean_h and clean_h != "/app/main.py":
                    raw_path = clean_h
                    break
        else:
            route_matches = request.headers.get("x-now-route-matches")
            if route_matches is not None:
                parsed = parse_qs(route_matches, keep_blank_values=True)
                matched = parsed.get("1", [""])[0]
                raw_path = "/" + unquote(matched).lstrip("/")
            else:
                raw_path = "/"
    elif raw_path.startswith("/app/main.py/"):
        raw_path = raw_path[len("/app/main.py") :]

    if not raw_path.startswith("/"):
        raw_path = "/" + raw_path
    if len(raw_path) > 1 and raw_path.endswith("/"):
        raw_path = raw_path.rstrip("/")

    request.scope["path"] = raw_path
    request.scope["raw_path"] = raw_path.encode("utf-8")
    return raw_path


@app.middleware("http")
async def vercel_path_normalizer_middleware(request: Request, call_next):
    _resolve_vercel_path(request)
    return await call_next(request)


def _parse_date(date_str: Optional[str], fallback: Optional[date] = None) -> date:
    if date_str:
        try:
            return datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            pass
    return fallback or get_now_br().date()


def _build_base_context(
    data_alvo: date,
    ai_feedback: Optional[str] = None,
    ai_error: Optional[str] = None,
    peso_feedback: Optional[str] = None,
    medidas_feedback: Optional[str] = None,
    treino_feedback: Optional[str] = None,
    treino_error: Optional[str] = None,
    config_feedback: Optional[str] = None,
    dt_treino: Optional[date] = None,
    dt_hist_ini: Optional[date] = None,
    dt_hist_fim: Optional[date] = None,
) -> Dict[str, Any]:
    """
    Monta o contexto completo para renderização inicial ou atualização de parciais HTMX.
    Envolve todas as consultas ao Neon em blocos try/except seguros para evitar Erro 500.
    """
    hoje = get_now_br().date()
    dt_tr = dt_treino or data_alvo
    dt_hi = dt_hist_ini or (hoje - timedelta(days=7))
    dt_hf = dt_hist_fim or hoje

    db_error: Optional[str] = None
    metas = DEFAULT_METAS.copy()
    jejum = "0h 0m"
    peso_data: Dict[str, Any] = {
        "peso_atual": 140.0,
        "peso_inicial": 140.0,
        "tendencia_atual": 140.0,
        "perda_total": 0.0,
        "delta_ultimo": 0.0,
        "registros": [],
        "chart_labels": [],
        "chart_pesos": [],
        "chart_ewma": [],
    }
    consumo_data: Dict[str, Any] = {
        "itens": [],
        "totais": {
            "kcal": 0.0,
            "proteina": 0.0,
            "carbo": 0.0,
            "gordura": 0.0,
            "quantidade": 0.0,
            "ferro_mg": 0.0,
            "b12_mcg": 0.0,
            "zinco_mg": 0.0,
            "magnesio_mg": 0.0,
        },
    }
    medidas_list = []
    treino_data: Dict[str, Any] = {
        "registros": [],
        "min_treino": 0,
        "passos_atv": 0,
        "total_rel": 0,
        "passos_rot": 0,
        "progresso_min": 0.0,
    }
    historico_data: Dict[str, Any] = {
        "total_kcal": 0,
        "media_prot_dia": 0,
        "total_registros": 0,
        "top_alimentos": [],
        "max_freq": 1,
        "registros": [],
    }

    try:
        metas = get_metas()
        jejum = get_tempo_jejum()
        peso_data = get_peso_historico(limit=30)
        consumo_data = get_consumo_dia(data_alvo)
        medidas_list = get_medidas_historico(limit=30)
        treino_data = get_treinos_dia(dt_tr)
        historico_data = get_historico_consumo(dt_hi, dt_hf)
    except Exception as exc:
        db_error = f"Não foi possível conectar ou consultar o banco Neon: {exc}"

    peso_atual = float(peso_data.get("peso_atual") or 140.0)
    peso_alvo = float(metas.get("peso_alvo") or 120.0)
    progresso_peso = (
        min(max(0.0, (150.0 - peso_atual) / max(0.1, (150.0 - peso_alvo))), 1.0) * 100.0
    )

    bf_preview = calc_bf_weltman(
        float(metas.get("last_waist") or 133.0),
        peso_atual,
        int(metas.get("altura") or 178),
        str(metas.get("genero") or "Masculino"),
    )

    return {
        "hoje": hoje,
        "data_alvo": data_alvo,
        "dt_treino": dt_tr,
        "dt_hist_ini": dt_hi,
        "dt_hist_fim": dt_hf,
        "metas": metas,
        "jejum": jejum,
        "peso": peso_data,
        "progresso_peso": round(progresso_peso, 1),
        "consumo": consumo_data,
        "medidas": medidas_list,
        "bf_preview": round(bf_preview, 1),
        "treino": treino_data,
        "historico": historico_data,
        "db_error": db_error,
        "ai_feedback": ai_feedback,
        "ai_error": ai_error,
        "peso_feedback": peso_feedback,
        "medidas_feedback": medidas_feedback,
        "treino_feedback": treino_feedback,
        "treino_error": treino_error,
        "config_feedback": config_feedback,
    }


# ============================================================================
# PÁGINA PRINCIPAL (SUPORTA GET E HEAD PARA EVITAR 405 EM CHECKS DE STATUS)
# ============================================================================
@app.api_route("/health", methods=["GET", "HEAD"], response_class=JSONResponse)
async def healthcheck():
    return {"status": "ok"}


@app.api_route("/", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def index(request: Request, data: Optional[str] = Query(default=None)):
    if request.method == "HEAD":
        return Response(status_code=200)
    data_alvo = _parse_date(data)
    ctx = _build_base_context(data_alvo)
    return _render_template(request, "index.html", ctx)


# ============================================================================
# PARCIAIS: RESUMO DO TOPO
# ============================================================================
@app.get("/partials/summary", response_class=HTMLResponse)
async def partial_summary(request: Request, data: Optional[str] = Query(default=None)):
    data_alvo = _parse_date(data)
    ctx = _build_base_context(data_alvo)
    ctx["oob"] = False
    return _render_template(request, "partials/summary_cards.html", ctx)


# ============================================================================
# PARCIAIS: PESO
# ============================================================================
@app.get("/partials/peso", response_class=HTMLResponse)
async def partial_peso_get(request: Request, data: Optional[str] = Query(default=None)):
    data_alvo = _parse_date(data)
    ctx = _build_base_context(data_alvo)
    ctx["include_summary_oob"] = False
    return _render_template(request, "partials/weight_section.html", ctx)


@app.post("/partials/peso", response_class=HTMLResponse)
async def partial_peso_post(
    request: Request,
    data_peso: str = Form(...),
    peso_kg: float = Form(...),
    data_alvo_str: Optional[str] = Form(default=None),
):
    dt_peso = _parse_date(data_peso)
    dt_alvo = _parse_date(data_alvo_str or data_peso)
    feedback = None
    try:
        inserir_peso(dt_peso, float(peso_kg))
        feedback = f"Peso de {peso_kg:.1f} kg salvo em {dt_peso.strftime('%d/%m/%Y')}!"
    except Exception as exc:
        feedback = f"Erro ao salvar peso: {exc}"

    ctx = _build_base_context(dt_alvo, peso_feedback=feedback)
    ctx["include_summary_oob"] = True
    return _render_template(request, "partials/weight_section.html", ctx)


@app.delete("/partials/peso/{peso_id}", response_class=HTMLResponse)
async def partial_peso_delete(
    request: Request,
    peso_id: int,
    data: Optional[str] = Query(default=None),
):
    dt_alvo = _parse_date(data)
    feedback = "Registro de peso removido."
    try:
        remover_peso(peso_id)
    except Exception as exc:
        feedback = f"Erro ao remover registro: {exc}"
    ctx = _build_base_context(dt_alvo, peso_feedback=feedback)
    ctx["include_summary_oob"] = True
    return _render_template(request, "partials/weight_section.html", ctx)


# ============================================================================
# PARCIAIS: MEDIDAS CORPORAIS
# ============================================================================
@app.post("/partials/medidas", response_class=HTMLResponse)
async def partial_medidas_post(
    request: Request,
    d_med: str = Form(...),
    p_inp: float = Form(...),
    waist: float = Form(...),
    data_alvo_str: Optional[str] = Form(default=None),
):
    dt_med = _parse_date(d_med)
    dt_alvo = _parse_date(data_alvo_str or d_med)
    feedback = None
    try:
        bf_w = registrar_avaliacao_corporal(dt_med, float(p_inp), float(waist))
        feedback = (
            f"Avaliação salva! Peso: {p_inp:.1f} kg | Cintura: {waist:.1f} cm | "
            f"BF Weltman: {bf_w:.1f}% (atualizado em body_measurements, peso e perfil)."
        )
    except Exception as exc:
        feedback = f"Erro ao salvar avaliação corporal: {exc}"

    ctx = _build_base_context(dt_alvo, medidas_feedback=feedback)
    ctx["include_summary_oob"] = True
    return _render_template(request, "partials/medidas_section.html", ctx)


@app.delete("/partials/medidas/{medida_id}", response_class=HTMLResponse)
async def partial_medidas_delete(
    request: Request,
    medida_id: int,
    data: Optional[str] = Query(default=None),
):
    dt_alvo = _parse_date(data)
    feedback = "Medida corporal removida."
    try:
        remover_medida(medida_id)
    except Exception as exc:
        feedback = f"Erro ao remover medida: {exc}"
    ctx = _build_base_context(dt_alvo, medidas_feedback=feedback)
    ctx["include_summary_oob"] = False
    return _render_template(request, "partials/medidas_section.html", ctx)


# ============================================================================
# PARCIAIS: CONSUMO ALIMENTAR (Groq SDK + JSON direto) & HISTÓRICO
# ============================================================================
@app.get("/partials/consumo", response_class=HTMLResponse)
async def partial_consumo_get(request: Request, data: Optional[str] = Query(default=None)):
    data_alvo = _parse_date(data)
    ctx = _build_base_context(data_alvo)
    ctx["include_summary_oob"] = True
    return _render_template(request, "partials/meals_list.html", ctx)


@app.post("/partials/consumo", response_class=HTMLResponse)
async def partial_consumo_post(
    request: Request,
    texto_input: str = Form(default=""),
    data_consumo: Optional[str] = Form(default=None),
    foto_prato: Optional[UploadFile] = File(default=None),
):
    data_alvo = _parse_date(data_consumo)
    ai_feedback: Optional[str] = None
    ai_error: Optional[str] = None

    try:
        imagem_bytes: Optional[bytes] = None
        if foto_prato and foto_prato.filename:
            raw_bytes = await foto_prato.read()
            if raw_bytes:
                imagem_bytes = raw_bytes

        if not (texto_input and texto_input.strip()) and not imagem_bytes:
            ai_error = "Digite o que comeu, envie uma foto do prato/rótulo ou cole diretamente o JSON."
        else:
            ok, resultado = analisar_refeicao_groq(
                texto_usuario=texto_input,
                data_ref=data_alvo,
                imagem_bytes=imagem_bytes,
            )
            if not ok:
                ai_error = str(resultado)
            else:
                payload = resultado if isinstance(resultado, dict) else {}
                alimentos = payload.get("alimentos") or []
                if not alimentos:
                    ai_error = f"A análise não retornou alimentos válidos. Resposta: {payload}"
                else:
                    qtd = inserir_alimentos_consumo(alimentos, data_padrao=data_alvo)
                    analise_txt = payload.get("analise") or "Refeição processada!"
                    ai_feedback = f"{analise_txt} ({qtd} alimento(s) salvo(s))"
    except Exception as ex:
        ai_error = f"Erro: {str(ex)}"

    ctx = _build_base_context(data_alvo, ai_feedback=ai_feedback, ai_error=ai_error)
    ctx["include_summary_oob"] = True
    return _render_template(request, "partials/meals_list.html", ctx)


@app.delete("/partials/consumo/{consumo_id}", response_class=HTMLResponse)
async def partial_consumo_delete(
    request: Request,
    consumo_id: int,
    data: Optional[str] = Query(default=None),
):
    data_alvo = _parse_date(data)
    ai_error = None
    try:
        remover_consumo(consumo_id)
    except Exception as exc:
        ai_error = f"Erro ao excluir alimento: {exc}"
    ctx = _build_base_context(data_alvo, ai_error=ai_error)
    ctx["include_summary_oob"] = True
    return _render_template(request, "partials/meals_list.html", ctx)


@app.get("/partials/historico", response_class=HTMLResponse)
async def partial_historico_get(
    request: Request,
    dt_hi: Optional[str] = Query(default=None),
    dt_hf: Optional[str] = Query(default=None),
):
    hoje = get_now_br().date()
    ini = _parse_date(dt_hi, fallback=hoje - timedelta(days=7))
    fim = _parse_date(dt_hf, fallback=hoje)
    ctx = _build_base_context(hoje, dt_hist_ini=ini, dt_hist_fim=fim)
    return _render_template(request, "partials/historico_section.html", ctx)


# ============================================================================
# PARCIAIS: TREINO & INTERVALS.ICU
# ============================================================================
@app.get("/partials/treino", response_class=HTMLResponse)
async def partial_treino_get(request: Request, dt_alvo: Optional[str] = Query(default=None)):
    dt_tr = _parse_date(dt_alvo)
    ctx = _build_base_context(dt_tr, dt_treino=dt_tr)
    return _render_template(request, "partials/treino_section.html", ctx)


@app.post("/partials/treino/fechamento", response_class=HTMLResponse)
async def partial_treino_fechamento(
    request: Request,
    dt_alvo: str = Form(...),
    input_total: int = Form(...),
):
    dt_tr = _parse_date(dt_alvo)
    fb, err = None, None
    try:
        salvar_fechamento_passos(dt_tr, int(input_total))
        fb = f"Fechado! Total do relógio: {input_total} passos."
    except Exception as exc:
        err = f"Erro ao salvar fechamento: {exc}"

    ctx = _build_base_context(dt_tr, dt_treino=dt_tr, treino_feedback=fb, treino_error=err)
    return _render_template(request, "partials/treino_section.html", ctx)


@app.post("/partials/treino/atividade", response_class=HTMLResponse)
async def partial_treino_atividade(
    request: Request,
    dt_alvo: str = Form(...),
    tipo: str = Form(...),
    duracao: int = Form(default=30),
    passos: int = Form(default=0),
    dist: float = Form(default=0.0),
    cal: float = Form(default=0.0),
    bpm: int = Form(default=0),
    obs: str = Form(default=""),
):
    dt_tr = _parse_date(dt_alvo)
    fb, err = None, None
    try:
        inserir_exercicio_manual(
            dt_alvo=dt_tr,
            tipo=tipo,
            duracao_min=int(duracao),
            passos=int(passos),
            distancia_km=float(dist),
            calorias=float(cal),
            bpm_medio=int(bpm),
            observacoes=obs,
        )
        fb = "Atividade registrada!"
    except Exception as exc:
        err = f"Erro ao registrar atividade: {exc}"

    ctx = _build_base_context(dt_tr, dt_treino=dt_tr, treino_feedback=fb, treino_error=err)
    return _render_template(request, "partials/treino_section.html", ctx)


@app.post("/partials/treino/sync", response_class=HTMLResponse)
async def partial_treino_sync(
    request: Request,
    dt_alvo: Optional[str] = Form(default=None),
):
    dt_tr = _parse_date(dt_alvo)
    try:
        ok, msg = sincronizar_treinos_recentes(engine=get_engine(), dias_retroativos=7)
    except Exception as exc:
        ok, msg = False, f"Erro ao conectar com banco/Intervals.icu: {exc}"
    ctx = _build_base_context(
        dt_tr,
        dt_treino=dt_tr,
        treino_feedback=msg if ok else None,
        treino_error=None if ok else msg,
    )
    return _render_template(request, "partials/treino_section.html", ctx)


@app.delete("/partials/treino/{exercicio_id}", response_class=HTMLResponse)
async def partial_treino_delete(
    request: Request,
    exercicio_id: int,
    dt_alvo: Optional[str] = Query(default=None),
):
    dt_tr = _parse_date(dt_alvo)
    fb, err = "Registro de treino removido.", None
    try:
        remover_exercicio(exercicio_id)
    except Exception as exc:
        fb, err = None, f"Erro ao remover registro: {exc}"
    ctx = _build_base_context(dt_tr, dt_treino=dt_tr, treino_feedback=fb, treino_error=err)
    return _render_template(request, "partials/treino_section.html", ctx)


# ============================================================================
# PARCIAIS: CONFIGURAÇÕES E METAS (public.perfil id = 1)
# ============================================================================
@app.post("/partials/config", response_class=HTMLResponse)
async def partial_config_post(
    request: Request,
    fator_atividade: float = Form(...),
    meta_kcal: float = Form(...),
    meta_proteina: float = Form(...),
    meta_carbo: float = Form(...),
    meta_gordura: float = Form(...),
    meta_peso_alvo: float = Form(...),
    ritmo_semanal: float = Form(...),
    data_alvo_str: Optional[str] = Form(default=None),
):
    dt_alvo = _parse_date(data_alvo_str)
    fb = None
    try:
        atualizar_metas(
            meta_kcal=float(meta_kcal),
            meta_proteina=float(meta_proteina),
            meta_carbo=float(meta_carbo),
            meta_gordura=float(meta_gordura),
            meta_peso_alvo=float(meta_peso_alvo),
            ritmo_semanal=float(ritmo_semanal),
            fator_atividade=float(fator_atividade),
        )
        fb = "Metas e Fator de Atividade salvos em public.perfil (id = 1)!"
    except Exception as exc:
        fb = f"Erro ao atualizar metas: {exc}"

    ctx = _build_base_context(dt_alvo, config_feedback=fb)
    ctx["include_summary_oob"] = True
    return _render_template(request, "partials/config_section.html", ctx)
