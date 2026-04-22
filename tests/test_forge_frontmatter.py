"""Testes de frontmatter.py."""
from __future__ import annotations

import sys
from pathlib import Path

FORGE_DIR = Path(__file__).parent.parent / "skills" / "obsidian-forge" / "scripts"
sys.path.insert(0, str(FORGE_DIR))

from frontmatter import read_frontmatter, write_frontmatter, parse_frontmatter, serialize_frontmatter  # noqa: E402


def test_read_frontmatter_simple(tmp_path: Path) -> None:
    p = tmp_path / "n.md"
    p.write_text("---\ntipo: plano\nstatus: ativo\n---\n\n# Body\n", encoding="utf-8")
    meta, body = read_frontmatter(p)
    assert meta["tipo"] == "plano"
    assert meta["status"] == "ativo"
    assert body.strip() == "# Body"


def test_read_frontmatter_nested(tmp_path: Path) -> None:
    p = tmp_path / "m.md"
    p.write_text("---\nobjetivo:\n  titulo: 'R$ 10k'\n  valor_alvo: 10000\n---\n", encoding="utf-8")
    meta, _ = read_frontmatter(p)
    assert meta["objetivo"]["valor_alvo"] == 10000


def test_read_frontmatter_list_of_dicts(tmp_path: Path) -> None:
    p = tmp_path / "m.md"
    p.write_text(
        "---\nfunil:\n  - etapa: clientes\n    alvo: 4\n  - etapa: reunioes\n    alvo: 40\n---\n",
        encoding="utf-8",
    )
    meta, _ = read_frontmatter(p)
    assert len(meta["funil"]) == 2
    assert meta["funil"][0]["etapa"] == "clientes"
    assert meta["funil"][1]["alvo"] == 40


def test_write_roundtrip(tmp_path: Path) -> None:
    p = tmp_path / "o.md"
    meta = {"tipo": "acao", "slug": "x", "ordem": 3, "tarefas_feitas": 2}
    body = "# T\n\n- [ ] task\n"
    write_frontmatter(p, meta, body)
    meta2, body2 = read_frontmatter(p)
    assert meta2 == meta
    assert body2.strip() == body.strip()


def test_write_preserves_body(tmp_path: Path) -> None:
    p = tmp_path / "o.md"
    body = "linha 1\n\n- [x] feita\n- [ ] pendente\n"
    write_frontmatter(p, {"tipo": "acao"}, body)
    assert body in p.read_text(encoding="utf-8")


def test_read_no_frontmatter(tmp_path: Path) -> None:
    p = tmp_path / "plain.md"
    p.write_text("# so body\n", encoding="utf-8")
    meta, body = read_frontmatter(p)
    assert meta == {}
    assert "# so body" in body
