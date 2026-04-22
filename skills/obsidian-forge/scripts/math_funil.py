"""Matematica do funil — deriva, valida, agrega. Zero LLM."""
from __future__ import annotations

import math
from typing import Any


class FunilInvalido(ValueError):
    pass


def derivar_funil(*, valor_alvo: float, valor_unitario: float,
                  reunioes_taxa: float, leads_taxa: float,
                  alcance_multiplicador: float) -> dict[str, int]:
    if valor_unitario <= 0 or reunioes_taxa <= 0 or leads_taxa <= 0:
        raise FunilInvalido("Parametros devem ser positivos.")
    clientes = math.ceil(valor_alvo / valor_unitario)
    reunioes = math.ceil(clientes / reunioes_taxa)
    leads = math.ceil(reunioes / leads_taxa)
    alcance = math.ceil(leads * alcance_multiplicador)
    return {"clientes": clientes, "reunioes": reunioes, "leads": leads, "alcance": alcance}


def validar_funil(funil: list[dict[str, Any]], *, valor_alvo: float) -> None:
    etapas = {e["etapa"]: e for e in funil}
    for nome in ("clientes", "reunioes", "leads", "alcance"):
        if nome not in etapas:
            raise FunilInvalido(f"Etapa '{nome}' ausente.")

    c = etapas["clientes"]["alvo"]
    vu = etapas["clientes"]["valor_unitario"]
    if c * vu != valor_alvo:
        raise FunilInvalido(f"clientes ({c}) * valor_unitario ({vu}) != valor_alvo ({valor_alvo}).")

    r = etapas["reunioes"]["alvo"]
    rt = etapas["reunioes"]["taxa_conversao"]
    if r != math.ceil(c / rt):
        raise FunilInvalido(f"reunioes.alvo={r}, esperado {math.ceil(c / rt)}.")

    lv = etapas["leads"]["alvo"]
    lt = etapas["leads"]["taxa_conversao"]
    if lv != math.ceil(r / lt):
        raise FunilInvalido(f"leads.alvo={lv}, esperado {math.ceil(r / lt)}.")


_TIPO_PARA_ETAPA = {
    "cliente_fechado": "clientes",
    "reuniao_realizada": "reunioes",
    "lead_captado": "leads",
    "conteudo_publicado": "alcance",
    "alcance_manual": "alcance",
}


def agregar_progresso(eventos: list[dict[str, Any]]) -> dict[str, Any]:
    a = {"clientes": 0, "reunioes": 0, "leads": 0, "alcance": 0, "valor_total": 0.0}
    for ev in eventos:
        t = ev.get("tipo")
        e = _TIPO_PARA_ETAPA.get(t)
        if e is None:
            continue
        if t == "alcance_manual":
            a["alcance"] += int(ev.get("quantidade", 0))
        else:
            a[e] += 1
        if t == "cliente_fechado":
            a["valor_total"] += float(ev.get("valor", 0))
    return a
