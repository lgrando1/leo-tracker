from collections import Counter, defaultdict
from datetime import date, datetime
import re
from typing import Any, Dict, List, Optional
from app.config import get_now_br
from app.database import execute_write, fetch_all, fetch_one

DEFAULT_METAS: Dict[str, Any] = {
    "kcal": 1638,
    "prot": 108,
    "carb": 164,
    "gord": 67,
    "peso_alvo": 120.0,
    "ritmo": 0.8,
    "altura": 178,
    "idade": 41,
    "genero": "Masculino",
    "fator": 1.2,
    "last_waist": 133.0,
    "last_neck": 53.0,
    "last_hip": 122.0,
}


def calc_bf_weltman(waist: float, weight_kg: float, height_cm: int, gender: str) -> float:
    """
    Fórmula de Weltman idêntica a @app.py (linhas 109-115).
    """
    if waist <= 0 or weight_kg <= 0:
        return 0.0
    try:
        if gender == "Masculino":
            return (0.31457 * waist) - (0.10969 * weight_kg) + 10.8336
        return (0.11077 * waist) - (0.17666 * height_cm) + (0.14354 * weight_kg) + 51.03301
    except Exception:
        return 0.0


def padronizar_alimento(nome: Optional[str]) -> str:
    """
    Padronização de alimentos idêntica a @app.py (linhas 221-243) para o Top 15 do Histórico.
    """
    if not nome:
        return "Outros"
    n = str(nome).lower().strip()
    if not n:
        return "Outros"
    n = re.sub(r"\(.*?\)", "", n).strip()
    n = n.split("-")[0].strip()

    if "ovo" in n:
        return "Ovo"
    if "frango" in n:
        return "Frango (Filé/Peito)"
    if "tapioca" in n:
        return "Tapioca"
    if "chia" in n:
        return "Semente de Chia"
    if "linhaça" in n or "linhaca" in n:
        return "Semente de Linhaça"
    if "queijo" in n:
        return "Queijo"
    if "banana" in n:
        return "Banana"
    if "arroz" in n:
        return "Arroz"
    if "feijão" in n or "feijao" in n:
        return "Feijão"
    if "carne" in n or "patinho" in n or "alcatra" in n:
        return "Carne Bovina"
    if "whey" in n:
        return "Whey Protein"
    if "leite" in n and "doce" not in n:
        return "Leite"
    if "iogurte" in n:
        return "Iogurte"
    if "maçã" in n or "maca" in n:
        return "Maçã"
    if "laranja" in n:
        return "Laranja"

    return n.title()


def get_metas() -> Dict[str, Any]:
    """Lê metas nutricionais e antropométricas de public.perfil (id = 1) igual a get_metas_do_banco() em @app.py."""
    try:
        r = fetch_one("SELECT * FROM public.perfil WHERE id = 1")
        if r:
            return {
                "kcal": int(r.get("meta_kcal") if r.get("meta_kcal") is not None else 1638),
                "prot": int(r.get("meta_proteina") if r.get("meta_proteina") is not None else 108),
                "carb": int(r.get("meta_carbo") if r.get("meta_carbo") is not None else 164),
                "gord": int(r.get("meta_gordura") if r.get("meta_gordura") is not None else 67),
                "peso_alvo": float(r.get("meta_peso_alvo") if r.get("meta_peso_alvo") is not None else 120.0),
                "ritmo": float(r.get("ritmo_semanal") if r.get("ritmo_semanal") is not None else 0.8),
                "altura": int(r.get("altura_cm") if r.get("altura_cm") is not None else 178),
                "idade": int(r.get("idade") if r.get("idade") is not None else 41),
                "genero": r.get("genero") or "Masculino",
                "fator": float(r.get("fator_atividade") or 1.2),
                "last_waist": float(r.get("ultima_cintura") or 133.0),
                "last_neck": float(r.get("ultimo_pescoco") or 53.0),
                "last_hip": float(r.get("ultimo_quadril") or 122.0),
            }
    except Exception:
        pass
    return DEFAULT_METAS.copy()


def atualizar_metas(
    meta_kcal: float,
    meta_proteina: float,
    meta_carbo: float,
    meta_gordura: float,
    meta_peso_alvo: float,
    ritmo_semanal: float,
    fator_atividade: float,
) -> None:
    """Atualiza metas na tabela public.perfil (id = 1) conforme @app.py (linhas 1528-1531)."""
    execute_write(
        """
        UPDATE public.perfil SET
            meta_kcal = :mk,
            meta_proteina = :mp,
            meta_carbo = :mc,
            meta_gordura = :mg,
            meta_peso_alvo = :mpa,
            ritmo_semanal = :rit,
            fator_atividade = :fat
        WHERE id = 1
        """,
        {
            "mk": meta_kcal,
            "mp": meta_proteina,
            "mc": meta_carbo,
            "mg": meta_gordura,
            "mpa": meta_peso_alvo,
            "rit": ritmo_semanal,
            "fat": fator_atividade,
        },
    )


def get_tempo_jejum() -> str:
    """Calcula o tempo de jejum desde o último registro em public.consumo (@app.py linhas 570-580)."""
    try:
        row = fetch_one(
            "SELECT data_hora FROM public.consumo ORDER BY data_hora DESC LIMIT 1"
        )
        if row and row.get("data_hora"):
            last_dt: datetime = row["data_hora"]
            now_naive = get_now_br().replace(tzinfo=None)
            last_naive = last_dt.replace(tzinfo=None) if last_dt.tzinfo else last_dt
            diff = (now_naive - last_naive).total_seconds()
            if diff > 0:
                return f"{int(diff // 3600)}h {int((diff % 3600) // 60)}m"
    except Exception:
        pass
    return "0h 0m"


# ============================================================================
# PESO & MEDIDAS CORPORAIS
# ============================================================================
def get_peso_historico(limit: int = 30) -> Dict[str, Any]:
    """
    Busca o histórico de peso em public.peso e calcula a tendência EWMA (span=10,
    Hacker's Diet de @app.py linha 501).
    """
    rows = fetch_all("SELECT id, data, peso_kg FROM public.peso ORDER BY data ASC, id ASC")

    por_data: Dict[date, Dict[str, Any]] = {}
    for r in rows:
        if r.get("data") is not None and r.get("peso_kg") is not None:
            por_data[r["data"]] = {
                "id": r["id"],
                "data": r["data"],
                "peso_kg": float(r["peso_kg"]),
            }

    serie_diaria = list(por_data.values())

    alpha = 2.0 / (10.0 + 1.0)
    ewma_val = None
    for item in serie_diaria:
        p = item["peso_kg"]
        if ewma_val is None:
            ewma_val = p
        else:
            ewma_val = (alpha * p) + ((1.0 - alpha) * ewma_val)
        item["peso_tendencia"] = round(ewma_val, 2)

    peso_atual = float(rows[-1]["peso_kg"]) if rows and rows[-1].get("peso_kg") is not None else 140.0
    peso_inicial = serie_diaria[0]["peso_kg"] if serie_diaria else peso_atual
    tendencia_atual = serie_diaria[-1]["peso_tendencia"] if serie_diaria else peso_atual

    delta_ultimo = 0.0
    if len(serie_diaria) >= 2:
        delta_ultimo = round(serie_diaria[-1]["peso_kg"] - serie_diaria[-2]["peso_kg"], 2)

    recorte = serie_diaria[-limit:]
    chart_labels = [
        d["data"].strftime("%d/%m") if hasattr(d["data"], "strftime") else str(d["data"])
        for d in recorte
    ]
    chart_pesos = [round(d["peso_kg"], 2) for d in recorte]
    chart_ewma = [d["peso_tendencia"] for d in recorte]

    ultimos_registros = list(reversed(rows[-limit:]))

    return {
        "peso_atual": round(peso_atual, 1),
        "peso_inicial": round(peso_inicial, 1),
        "tendencia_atual": round(tendencia_atual, 1),
        "perda_total": round(peso_inicial - peso_atual, 1),
        "delta_ultimo": delta_ultimo,
        "registros": ultimos_registros,
        "chart_labels": chart_labels,
        "chart_pesos": chart_pesos,
        "chart_ewma": chart_ewma,
    }


def inserir_peso(data_peso: date, peso_kg: float) -> None:
    """
    Insere ou atualiza o registro de peso da data em public.peso (id, data DATE, peso_kg REAL).
    """
    existente = fetch_one(
        "SELECT id FROM public.peso WHERE data = :d ORDER BY id DESC LIMIT 1",
        {"d": data_peso},
    )
    if existente and existente.get("id"):
        execute_write(
            "UPDATE public.peso SET peso_kg = :p WHERE data = :d",
            {"p": peso_kg, "d": data_peso},
        )
    else:
        execute_write(
            "INSERT INTO public.peso (data, peso_kg) VALUES (:d, :p)",
            {"d": data_peso, "p": peso_kg},
        )


def remover_peso(peso_id: int) -> None:
    """Remove um registro de public.peso pelo id."""
    execute_write("DELETE FROM public.peso WHERE id = :id", {"id": peso_id})


def registrar_avaliacao_corporal(log_date: date, weight_kg: float, waist_cm: float) -> float:
    """
    Segue exatamente a lógica de Avaliação Corporal do @app.py (linhas 1450-1464):
    1. Calcula BF Weltman via calc_bf_weltman(waist, weight_kg, METAS['altura'], METAS['genero'])
    2. Insere em public.body_measurements
    3. Insere simultaneamente em public.peso
    4. Atualiza ultima_cintura em public.perfil WHERE id = 1
    """
    metas = get_metas()
    bf_w = calc_bf_weltman(waist_cm, weight_kg, metas["altura"], metas["genero"])

    execute_write(
        """
        INSERT INTO public.body_measurements
            (log_date, weight_kg, waist_cm, neck_cm, hip_cm, body_fat_est,
             fold_chest, fold_abdominal, fold_thigh, fold_triceps,
             body_fat_pollock, body_fat_weltman, notes)
        VALUES
            (:dt, :w, :wa, :ne, :hi, :bf, 0, 0, 0, 0, 0, :bfw, 'Weltman Simples')
        """,
        {
            "dt": log_date,
            "w": weight_kg,
            "wa": waist_cm,
            "ne": metas["last_neck"],
            "hi": metas["last_hip"],
            "bf": bf_w,
            "bfw": bf_w,
        },
    )
    execute_write(
        "INSERT INTO public.peso (data, peso_kg) VALUES (:dt, :w)",
        {"dt": log_date, "w": weight_kg},
    )
    execute_write(
        "UPDATE public.perfil SET ultima_cintura = :wa WHERE id = 1",
        {"wa": waist_cm},
    )
    return bf_w


def get_medidas_historico(limit: int = 30) -> List[Dict[str, Any]]:
    """Retorna o histórico de medidas corporais de public.body_measurements."""
    return fetch_all(
        """
        SELECT id, log_date, weight_kg, waist_cm, neck_cm, hip_cm,
               body_fat_est, body_fat_weltman, notes
        FROM public.body_measurements
        ORDER BY log_date DESC, id DESC
        LIMIT :lim
        """,
        {"lim": limit},
    )


def remover_medida(medida_id: int) -> None:
    """Remove um registro de public.body_measurements pelo id."""
    execute_write("DELETE FROM public.body_measurements WHERE id = :id", {"id": medida_id})


# ============================================================================
# ALIMENTAÇÃO, MACRONUTRIENTES & HISTÓRICO
# ============================================================================
def get_consumo_dia(data_alvo: date) -> Dict[str, Any]:
    """Retorna os itens consumidos no dia e somatórios de macros/micros (@app.py linhas 600-604, 753-763)."""
    itens = fetch_all(
        """
        SELECT id, data, data_hora, alimento, quantidade, kcal,
               proteina, carbo, gordura, gluten,
               COALESCE(ferro_mg, 0) AS ferro_mg,
               COALESCE(b12_mcg, 0) AS b12_mcg,
               COALESCE(zinco_mg, 0) AS zinco_mg,
               COALESCE(magnesio_mg, 0) AS magnesio_mg
        FROM public.consumo
        WHERE data = :d
        ORDER BY id DESC
        """,
        {"d": data_alvo},
    )

    totais = {
        "kcal": round(sum(float(i.get("kcal") or 0) for i in itens), 1),
        "proteina": round(sum(float(i.get("proteina") or 0) for i in itens), 1),
        "carbo": round(sum(float(i.get("carbo") or 0) for i in itens), 1),
        "gordura": round(sum(float(i.get("gordura") or 0) for i in itens), 1),
        "quantidade": round(sum(float(i.get("quantidade") or 0) for i in itens), 0),
        "ferro_mg": round(sum(float(i.get("ferro_mg") or 0) for i in itens), 2),
        "b12_mcg": round(sum(float(i.get("b12_mcg") or 0) for i in itens), 2),
        "zinco_mg": round(sum(float(i.get("zinco_mg") or 0) for i in itens), 2),
        "magnesio_mg": round(sum(float(i.get("magnesio_mg") or 0) for i in itens), 1),
    }

    return {"itens": itens, "totais": totais}


def inserir_alimentos_consumo(alimentos: List[Dict[str, Any]], data_padrao: date) -> int:
    """
    Insere alimentos em public.consumo usando o cálculo de kcal de @app.py (linhas 723 e 743):
    kf = max((float(item.get('p',0))*4 + float(item.get('c',0))*4 + float(item.get('g',0))*9), float(item.get('kcal',0)))
    """
    inseridos = 0
    for item in alimentos:
        dt_val = item.get("data") or data_padrao
        p = float(item.get("p") or 0.0)
        c = float(item.get("c") or 0.0)
        g = float(item.get("g") or 0.0)
        kcal_raw = float(item.get("kcal") or 0.0)
        kf = max((p * 4.0 + c * 4.0 + g * 9.0), kcal_raw)

        execute_write(
            """
            INSERT INTO public.consumo
                (data, alimento, quantidade, kcal, proteina, carbo, gordura,
                 gluten, ferro_mg, b12_mcg, zinco_mg, magnesio_mg)
            VALUES
                (:dt, :ali, :qtd, :kc, :pr, :ca, :go, :gl, :fe, :b12, :zn, :mg)
            """,
            {
                "dt": dt_val,
                "ali": item.get("alimento"),
                "qtd": item.get("quantidade_g"),
                "kc": kf,
                "pr": p,
                "ca": c,
                "go": g,
                "gl": item.get("gluten"),
                "fe": item.get("ferro_mg", 0),
                "b12": item.get("b12_mcg", 0),
                "zn": item.get("zinco_mg", 0),
                "mg": item.get("magnesio_mg", 0),
            },
        )
        inseridos += 1
    return inseridos


def remover_consumo(consumo_id: int) -> None:
    """Remove um item de public.consumo pelo id (@app.py linha 760)."""
    execute_write("DELETE FROM public.consumo WHERE id = :id", {"id": consumo_id})


def get_historico_consumo(dt_ini: date, dt_fim: date) -> Dict[str, Any]:
    """
    Consulta e consolida o Histórico de Consumo (@app.py linhas 1393-1433):
    - Total Kcal no período
    - Média de Proteína/dia (agrupado por data)
    - Total de refeições registradas
    - Ranking Top 15 alimentos via padronizar_alimento()
    - Registros brutos para auditoria
    """
    rows = fetch_all(
        """
        SELECT id, data, alimento, quantidade, kcal, proteina, carbo, gordura
        FROM public.consumo
        WHERE data >= :d1 AND data <= :d2
        ORDER BY data DESC, id DESC
        """,
        {"d1": dt_ini, "d2": dt_fim},
    )

    if not rows:
        return {
            "total_kcal": 0,
            "media_prot_dia": 0,
            "total_registros": 0,
            "top_alimentos": [],
            "max_freq": 1,
            "registros": [],
        }

    total_kcal = int(sum(float(r.get("kcal") or 0) for r in rows))
    prot_por_dia: Dict[Any, float] = defaultdict(float)
    contador_alimentos: Counter[str] = Counter()

    for r in rows:
        prot_por_dia[r.get("data")] += float(r.get("proteina") or 0.0)
        padrao = padronizar_alimento(r.get("alimento"))
        contador_alimentos[padrao] += 1

    media_prot_dia = (
        int(round(sum(prot_por_dia.values()) / len(prot_por_dia)))
        if prot_por_dia
        else 0
    )

    top_15 = [
        {"alimento_base": nome, "frequencia": freq}
        for nome, freq in contador_alimentos.most_common(15)
    ]
    max_freq = top_15[0]["frequencia"] if top_15 else 1

    return {
        "total_kcal": total_kcal,
        "media_prot_dia": media_prot_dia,
        "total_registros": len(rows),
        "top_alimentos": top_15,
        "max_freq": max_freq,
        "registros": rows,
    }


# ============================================================================
# EXERCÍCIOS & PASSOS (TAB TREINO DE @app.py)
# ============================================================================
def get_treinos_dia(dt_alvo: date) -> Dict[str, Any]:
    """
    Carrega os exercícios da data alvo seguindo a lógica exata da aba Treino (@app.py linhas 768-833).
    """
    rows = fetch_all(
        "SELECT * FROM public.exercicios WHERE data = :d ORDER BY id DESC",
        {"d": dt_alvo},
    )
    fechamentos = [r for r in rows if r.get("tipo") == "Fechamento Diário"]
    atividades = [r for r in rows if r.get("tipo") != "Fechamento Diário"]

    min_treino = int(sum(float(r.get("duracao_min") or 0) for r in atividades))
    passos_atv = int(sum(float(r.get("passos") or 0) for r in atividades))
    total_rel = int(float(fechamentos[0].get("passos_total_dia") or 0)) if fechamentos else 0
    passos_rot = max(0, total_rel - passos_atv)
    progresso_min = min(min_treino / 120.0, 1.0) * 100.0

    return {
        "registros": rows,
        "min_treino": min_treino,
        "passos_atv": passos_atv,
        "total_rel": total_rel,
        "passos_rot": passos_rot,
        "progresso_min": round(progresso_min, 1),
    }


def salvar_fechamento_passos(dt_alvo: date, input_total: int) -> None:
    """
    Salva o Fechamento Diário do relógio em public.exercicios (@app.py linhas 793-799).
    """
    dados_dia = get_treinos_dia(dt_alvo)
    passos_atv = dados_dia["passos_atv"]

    execute_write(
        "DELETE FROM public.exercicios WHERE data = :d AND tipo = 'Fechamento Diário'",
        {"d": dt_alvo},
    )
    execute_write(
        """
        INSERT INTO public.exercicios
            (data, tipo, duracao_min, passos, passos_total_dia, passos_trabalho, calorias, observacoes)
        VALUES
            (:d, 'Fechamento Diário', 0, 0, :pt, :ptr, 0, 'Total Relógio')
        """,
        {
            "d": dt_alvo,
            "pt": input_total,
            "ptr": max(0, input_total - passos_atv),
        },
    )


def inserir_exercicio_manual(
    dt_alvo: date,
    tipo: str,
    duracao_min: int,
    passos: int,
    distancia_km: float,
    calorias: float,
    bpm_medio: int,
    observacoes: str,
) -> None:
    """Registra atividade manual em public.exercicios (@app.py linhas 814-817)."""
    execute_write(
        """
        INSERT INTO public.exercicios
            (data, tipo, duracao_min, passos, distancia_km, calorias, bpm_medio, observacoes)
        VALUES
            (:d, :t, :dm, :p, :dk, :c, :bpm, :o)
        """,
        {
            "d": dt_alvo,
            "t": tipo,
            "dm": duracao_min,
            "p": passos,
            "dk": distancia_km,
            "c": calorias,
            "bpm": bpm_medio,
            "o": observacoes,
        },
    )


def remover_exercicio(exercicio_id: int) -> None:
    """Remove registro de exercício de public.exercicios (@app.py linha 831)."""
    execute_write("DELETE FROM public.exercicios WHERE id = :id", {"id": exercicio_id})
