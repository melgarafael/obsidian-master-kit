"""Testes de math_funil."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

FORGE_DIR = Path(__file__).parent.parent / "skills" / "obsidian-forge" / "scripts"
sys.path.insert(0, str(FORGE_DIR))

from math_funil import derivar_funil, validar_funil, FunilInvalido, agregar_progresso  # noqa: E402


def test_derivar_canonico() -> None:
    f = derivar_funil(valor_alvo=10000, valor_unitario=2500,
                      reunioes_taxa=0.10, leads_taxa=0.10, alcance_multiplicador=10)
    assert f == {"clientes": 4, "reunioes": 40, "leads": 400, "alcance": 4000}


def test_derivar_arredonda_para_cima() -> None:
    f = derivar_funil(valor_alvo=10000, valor_unitario=3000,
                      reunioes_taxa=0.15, leads_taxa=0.10, alcance_multiplicador=10)
    assert f["clientes"] == 4


def test_validar_ok() -> None:
    f = [
        {"etapa": "clientes", "alvo": 4, "valor_unitario": 2500},
        {"etapa": "reunioes", "alvo": 40, "taxa_conversao": 0.10},
        {"etapa": "leads", "alvo": 400, "taxa_conversao": 0.10},
        {"etapa": "alcance", "alvo": 4000, "fonte": "conteudo"},
    ]
    validar_funil(f, valor_alvo=10000)


def test_validar_falha_quando_valor_nao_bate() -> None:
    f = [
        {"etapa": "clientes", "alvo": 3, "valor_unitario": 2500},
        {"etapa": "reunioes", "alvo": 40, "taxa_conversao": 0.10},
        {"etapa": "leads", "alvo": 400, "taxa_conversao": 0.10},
        {"etapa": "alcance", "alvo": 4000, "fonte": "conteudo"},
    ]
    with pytest.raises(FunilInvalido, match="clientes"):
        validar_funil(f, valor_alvo=10000)


def test_agregar_eventos() -> None:
    eventos = [
        {"tipo": "cliente_fechado", "valor": 2500},
        {"tipo": "cliente_fechado", "valor": 2500},
        {"tipo": "reuniao_realizada"},
        {"tipo": "lead_captado"},
        {"tipo": "lead_captado"},
        {"tipo": "lead_captado"},
        {"tipo": "conteudo_publicado"},
    ]
    a = agregar_progresso(eventos)
    assert a == {"clientes": 2, "reunioes": 1, "leads": 3, "alcance": 1, "valor_total": 5000.0}


def test_agregar_alcance_manual() -> None:
    e = [{"tipo": "alcance_manual", "quantidade": 120},
         {"tipo": "conteudo_publicado"}]
    assert agregar_progresso(e)["alcance"] == 121
