"""Testes de render de templates."""
from __future__ import annotations

import sys
from pathlib import Path

FORGE_DIR = Path(__file__).parent.parent / "skills" / "obsidian-forge" / "scripts"
sys.path.insert(0, str(FORGE_DIR))

from plan_business import renderizar_plano, renderizar_metas, renderizar_acoes  # noqa: E402
from frontmatter import read_frontmatter  # noqa: E402


def test_renderizar_plano(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    (vault / "04 - Negocio").mkdir(parents=True)
    renderizar_plano(vault_root=vault, respostas={
        "ciclo": "2026-Q2", "produto": "P", "problema": "Q", "pessoa": "R",
        "produto_prosa": "p", "problema_prosa": "p", "pessoa_prosa": "p",
        "valor_unitario": 2500,
        "resultado_potencial": "a", "tempo_economizado": "b",
        "esforco_reduzido": "c", "producao_aumentada": "d",
    })
    meta, body = read_frontmatter(vault / "04 - Negocio" / "_plano.md")
    assert meta["produto"] == "P"
    assert meta["protected"] is True
    assert "P" in body


def test_renderizar_metas(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    (vault / "04 - Negocio").mkdir(parents=True)
    renderizar_metas(vault_root=vault, respostas={
        "ciclo": "2026-Q2", "objetivo_titulo": "R$ 10k", "valor_alvo": 10000,
        "prazo": "2026-06-30", "valor_unitario": 2500,
        "clientes_alvo": 4, "reunioes_alvo": 40, "reunioes_taxa": 0.10,
        "leads_alvo": 400, "leads_taxa": 0.10,
        "alcance_alvo": 4000, "alcance_fonte": "conteudo",
    })
    meta, _ = read_frontmatter(vault / "04 - Negocio" / "_metas.md")
    assert meta["funil"][0]["etapa"] == "clientes"
    assert meta["funil"][0]["alvo"] == 4
    assert meta["objetivo"]["valor_atual"] == 0


def test_renderizar_acoes_cria_7(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    (vault / "04 - Negocio" / "acoes").mkdir(parents=True)
    renderizar_acoes(vault_root=vault)
    arquivos = sorted((vault / "04 - Negocio" / "acoes").glob("*.md"))
    assert len(arquivos) == 7
    assert any("01-segundo-cerebro" in a.name for a in arquivos)
    assert any("07-admin-financeiro" in a.name for a in arquivos)
