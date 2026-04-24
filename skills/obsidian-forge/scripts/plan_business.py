"""Modulo 2 — arquiteto de negocio."""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))


def _state_path(vault_root: Path) -> Path:
    return vault_root / "04 - Negocio" / ".forge-state.json"


def ler_estado(vault_root: Path) -> dict[str, Any]:
    p = _state_path(vault_root)
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def salvar_estado(vault_root: Path, estado: dict[str, Any]) -> None:
    p = _state_path(vault_root)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(estado, indent=2, ensure_ascii=False), encoding="utf-8")


def limpar_estado(vault_root: Path) -> None:
    p = _state_path(vault_root)
    if p.exists():
        p.unlink()


def proximo_passo(vault_root: Path) -> int:
    return min(int(ler_estado(vault_root).get("passo_atual", 0)) + 1, 5)


from frontmatter import read_frontmatter, write_frontmatter, serialize_frontmatter  # noqa: E402

TEMPLATES_DIR = Path(__file__).parent / "templates"


def _render_template(template_path: Path, ctx: dict[str, Any]) -> str:
    text = template_path.read_text(encoding="utf-8")
    for k, v in ctx.items():
        text = text.replace("{{" + k + "}}", str(v))
    return text


def renderizar_plano(*, vault_root: Path, respostas: dict[str, Any]) -> Path:
    ctx = {**respostas, "atualizado": datetime.now().isoformat(timespec="seconds")}
    text = _render_template(TEMPLATES_DIR / "plano.md", ctx)
    alvo = vault_root / "04 - Negocio" / "_plano.md"
    alvo.parent.mkdir(parents=True, exist_ok=True)
    alvo.write_text(text, encoding="utf-8")
    return alvo


def renderizar_metas(*, vault_root: Path, respostas: dict[str, Any]) -> Path:
    ctx = {
        **respostas,
        "atualizado": datetime.now().isoformat(timespec="seconds"),
        "reunioes_taxa_pct": int(respostas["reunioes_taxa"] * 100),
        "leads_taxa_pct": int(respostas["leads_taxa"] * 100),
    }
    text = _render_template(TEMPLATES_DIR / "metas.md", ctx)
    alvo = vault_root / "04 - Negocio" / "_metas.md"
    alvo.parent.mkdir(parents=True, exist_ok=True)
    alvo.write_text(text, encoding="utf-8")
    return alvo


def renderizar_acoes(*, vault_root: Path) -> list[Path]:
    agora = datetime.now().isoformat(timespec="seconds")
    src_dir = TEMPLATES_DIR / "acoes"
    alvo_dir = vault_root / "04 - Negocio" / "acoes"
    alvo_dir.mkdir(parents=True, exist_ok=True)
    criados: list[Path] = []
    for src in sorted(src_dir.glob("*.md")):
        text = _render_template(src, {"atualizado": agora})
        alvo = alvo_dir / src.name
        alvo.write_text(text, encoding="utf-8")
        criados.append(alvo)
    return criados
