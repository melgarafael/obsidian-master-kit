"""Integration: scan + plan + progresso + refresh num vault temporario."""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

FORGE_DIR = Path(__file__).parent.parent / "skills" / "obsidian-forge" / "scripts"
sys.path.insert(0, str(FORGE_DIR))


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    v = tmp_path / "vault"
    (v / ".obsidian-master").mkdir(parents=True)
    (v / ".obsidian-master" / "marker.json").write_text("{}")
    (v / "04 - Negocio" / "contexto").mkdir(parents=True)
    (v / "04 - Negocio" / "progresso").mkdir(parents=True)
    (v / "04 - Negocio" / "acoes").mkdir(parents=True)
    return v


@pytest.fixture
def fixtures_mtime() -> None:
    fix = Path(__file__).parent / "fixtures" / "forge" / "projetos-fake"
    agora = time.time()
    for r in [fix / "repo-ativo-python", fix / "repo-ativo-node"]:
        for f in r.rglob("*"):
            if f.is_file() and ".git" not in f.parts:
                os.utime(f, (agora, agora))


def test_fluxo_completo(vault: Path, fixtures_mtime: None) -> None:
    from scan_context import init_config, scan
    from plan_business import renderizar_plano, renderizar_metas, renderizar_acoes
    from dash_refresh import recomputar
    from frontmatter import read_frontmatter, write_frontmatter

    fix = Path(__file__).parent / "fixtures" / "forge" / "projetos-fake"
    init_config(vault_root=vault, pastas=[str(fix)])
    result = scan(vault_root=vault, silent=True)
    assert result["projetos_ativos"] >= 2

    renderizar_plano(vault_root=vault, respostas={
        "ciclo": "2026-Q2",
        "produto": "p", "problema": "pb", "pessoa": "ps",
        "produto_prosa": "a", "problema_prosa": "a", "pessoa_prosa": "a",
        "valor_unitario": 2500,
        "resultado_potencial": "r", "tempo_economizado": "t",
        "esforco_reduzido": "e", "producao_aumentada": "pa",
    })
    renderizar_metas(vault_root=vault, respostas={
        "ciclo": "2026-Q2",
        "objetivo_titulo": "R$ 10k", "valor_alvo": 10000, "prazo": "2026-06-30",
        "valor_unitario": 2500,
        "clientes_alvo": 4, "reunioes_alvo": 40, "reunioes_taxa": 0.10,
        "leads_alvo": 400, "leads_taxa": 0.10,
        "alcance_alvo": 4000, "alcance_fonte": "conteudo",
    })
    renderizar_acoes(vault_root=vault)

    write_frontmatter(
        vault / "04 - Negocio" / "progresso" / "2026-04-22.md",
        {"tipo": "progresso", "data": "2026-04-22", "eventos": 2},
        "- 10:00 — cliente_fechado (valor: R$ 2500)\n- 11:00 — reuniao_realizada\n",
    )
    recomputar(vault_root=vault)

    meta, _ = read_frontmatter(vault / "04 - Negocio" / "_metas.md")
    etapas = {e["etapa"]: e for e in meta["funil"]}
    assert etapas["clientes"]["atual"] == 1
    assert etapas["reunioes"]["atual"] == 1
    assert meta["objetivo"]["valor_atual"] == 2500.0
    assert len(list((vault / "04 - Negocio" / "acoes").glob("*.md"))) == 7
