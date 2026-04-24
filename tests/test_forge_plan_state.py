"""State management da entrevista plan_business."""
from __future__ import annotations

import sys
from pathlib import Path

FORGE_DIR = Path(__file__).parent.parent / "skills" / "obsidian-forge" / "scripts"
sys.path.insert(0, str(FORGE_DIR))

from plan_business import ler_estado, salvar_estado, limpar_estado, proximo_passo  # noqa: E402


def test_estado_vazio(tmp_path: Path) -> None:
    assert proximo_passo(tmp_path) == 1


def test_salvar_e_ler(tmp_path: Path) -> None:
    salvar_estado(tmp_path, {"passo_atual": 2, "resp_1": {"produto": "x"}})
    e = ler_estado(tmp_path)
    assert e["passo_atual"] == 2
    assert e["resp_1"]["produto"] == "x"


def test_proximo_passo_apos_2(tmp_path: Path) -> None:
    salvar_estado(tmp_path, {"passo_atual": 2})
    assert proximo_passo(tmp_path) == 3


def test_limpar(tmp_path: Path) -> None:
    salvar_estado(tmp_path, {"passo_atual": 3})
    limpar_estado(tmp_path)
    assert proximo_passo(tmp_path) == 1
