"""Recomputa _metas.md em Python (mirror da logica do dashboard.html)."""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from frontmatter import read_frontmatter, write_frontmatter   # noqa: E402
from math_funil import agregar_progresso   # noqa: E402

LINHA_RE = re.compile(r"^- \d{2}:\d{2} — (\w+)(?:\s*\((.*)\))?")


def _parse_eventos(body: str) -> list[dict]:
    eventos = []
    for linha in (body or "").split("\n"):
        m = LINHA_RE.match(linha)
        if not m:
            continue
        tipo = m.group(1)
        det = m.group(2) or ""
        ev = {"tipo": tipo}
        vm = re.search(r"valor:\s*R?\$?\s*(\d+(?:\.\d+)?)", det)
        if vm:
            ev["valor"] = float(vm.group(1))
        qm = re.search(r"quantidade:\s*(\d+)", det)
        if qm:
            ev["quantidade"] = int(qm.group(1))
        eventos.append(ev)
    return eventos


def recomputar(*, vault_root: Path) -> None:
    area = vault_root / "04 - Negocio"
    metas_path = area / "_metas.md"
    if not metas_path.exists():
        return
    meta, body = read_frontmatter(metas_path)
    prog_dir = area / "progresso"
    eventos = []
    if prog_dir.exists():
        for p in prog_dir.glob("*.md"):
            _, b = read_frontmatter(p)
            eventos.extend(_parse_eventos(b))
    atual = agregar_progresso(eventos)
    if "funil" in meta:
        for e in meta["funil"]:
            e["atual"] = atual.get(e.get("etapa"), 0)
    if "objetivo" in meta:
        meta["objetivo"]["valor_atual"] = atual.get("valor_total", 0)
    write_frontmatter(metas_path, meta, body)
