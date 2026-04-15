"""core.paths — helpers compartilhados de resolucao de vault.

Centraliza a logica de descoberta do vault root (via marker em ancestor) e
paths relativos canonicos usados por `core.cli` e pelas skills (expand,
organizer, pulse, migrate). Stdlib-only.

Uso:

    from core.paths import resolve_vault

    vault = resolve_vault(args.vault)   # args.vault pode ser None
    # vault e um pathlib.Path absoluto apontando pro vault root, ou
    # SystemExit(1) com mensagem pt-br se nao achar marker em nenhum ancestor
"""
from __future__ import annotations

import pathlib
import sys

MARKER_REL = ".obsidian-master/marker.json"


def resolve_vault(raw: str | None) -> pathlib.Path:
    """Resolve o vault root para um Path absoluto.

    - `raw` string dado: expande `~` + resolve, devolve direto (mesmo sem
      marker — permite bootstrap tipo `init-db --vault NEW_DIR`).
    - `raw` None: walk ancestrais do cwd procurando `.obsidian-master/marker.json`.
      Retorna o ancestor com marker.
    - Sem marker em nenhum ancestor: `sys.exit(1)` com mensagem util em pt-br.
    """
    if raw:
        return pathlib.Path(raw).expanduser().resolve()
    cur = pathlib.Path.cwd().resolve()
    while True:
        if (cur / MARKER_REL).exists():
            return cur
        if cur == cur.parent:
            break
        cur = cur.parent
    sys.exit(
        "Erro: nao encontrei vault obsidian-master em ancestrais de "
        f"{pathlib.Path.cwd()}. Rode dentro de um vault ou passe "
        "--vault PATH."
    )
