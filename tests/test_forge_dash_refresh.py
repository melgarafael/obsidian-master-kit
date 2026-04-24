"""Paridade Python vs JS na agregação."""
from __future__ import annotations

import sys
from pathlib import Path

FORGE_DIR = Path(__file__).parent.parent / "skills" / "obsidian-forge" / "scripts"
sys.path.insert(0, str(FORGE_DIR))

from dash_refresh import recomputar, _parse_eventos  # noqa: E402
from frontmatter import read_frontmatter, write_frontmatter  # noqa: E402


def test_parse_eventos() -> None:
    body = """
- 14:00 — cliente_fechado (valor: R$ 2500, nota: primeiro)
- 15:00 — reuniao_realizada
- 16:00 — alcance_manual (quantidade: 120)
""".strip()
    e = _parse_eventos(body)
    assert len(e) == 3
    assert e[0]["tipo"] == "cliente_fechado"
    assert e[0]["valor"] == 2500.0
    assert e[2]["quantidade"] == 120


def test_recomputar(tmp_path: Path) -> None:
    area = tmp_path / "04 - Negocio"
    (area / "progresso").mkdir(parents=True)
    metas = {
        "tipo": "metas",
        "objetivo": {"titulo": "x", "valor_alvo": 10000, "valor_atual": 0},
        "funil": [
            {"etapa": "clientes", "alvo": 4, "atual": 0, "valor_unitario": 2500},
            {"etapa": "reunioes", "alvo": 40, "atual": 0, "taxa_conversao": 0.10},
            {"etapa": "leads", "alvo": 400, "atual": 0, "taxa_conversao": 0.10},
            {"etapa": "alcance", "alvo": 4000, "atual": 0, "fonte": "conteudo"},
        ],
    }
    write_frontmatter(area / "_metas.md", metas, "# m")
    write_frontmatter(
        area / "progresso" / "2026-04-22.md",
        {"tipo": "progresso", "data": "2026-04-22", "eventos": 3},
        "- 14:00 — cliente_fechado (valor: R$ 2500)\n"
        "- 15:00 — reuniao_realizada\n"
        "- 16:00 — lead_captado\n",
    )
    recomputar(vault_root=tmp_path)
    meta2, _ = read_frontmatter(area / "_metas.md")
    etapas = {e["etapa"]: e for e in meta2["funil"]}
    assert etapas["clientes"]["atual"] == 1
    assert etapas["reunioes"]["atual"] == 1
    assert etapas["leads"]["atual"] == 1
    assert meta2["objetivo"]["valor_atual"] == 2500.0
