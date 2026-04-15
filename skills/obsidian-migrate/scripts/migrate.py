#!/usr/bin/env python3
"""CLI do skill obsidian-migrate. Opcao C (hibrida) pra adocao do kit
em vault existente. Wave 1 implementa so 'status'; demais comandos sao
stubs declarados (Waves 2-6 flesham).
"""
from __future__ import annotations
import argparse
import json
import pathlib
import sys


VALID_STATES = ("empty", "existing", "already_migrated")


def detect_state(vault: pathlib.Path) -> str:
    """Detecta o estado do vault pra fins de migracao.

    - empty: diretorio nao existe OU existe mas nao tem nenhum .md fora de
      pastas ignoradas
    - already_migrated: tem .obsidian-master/marker.json
    - existing: tem .md e nao tem marker
    """
    if not vault.exists() or not vault.is_dir():
        return "empty"
    marker = vault / ".obsidian-master" / "marker.json"
    if marker.exists():
        return "already_migrated"
    # Procura qualquer .md fora de ignored
    ignore = {".obsidian", ".trash", ".obsidian-master", ".git", "node_modules",
              "_templates"}
    for p in vault.rglob("*.md"):
        rel = p.relative_to(vault)
        if any(part in ignore or part.startswith(".") for part in rel.parts[:-1]):
            continue
        return "existing"
    return "empty"


def cmd_status(args) -> int:
    vault = pathlib.Path(args.vault).expanduser().resolve()
    state = detect_state(vault)
    print(f"Estado do vault: {state}")
    print(f"Caminho: {vault}")
    if state == "already_migrated":
        marker = vault / ".obsidian-master" / "marker.json"
        try:
            data = json.loads(marker.read_text(encoding="utf-8"))
            mig = data.get("migration_completed", False)
            print(f"  marker.json: kit_version={data.get('kit_version', '?')}, "
                  f"migration_completed={mig}")
        except Exception as e:
            print(f"  marker.json: presente, mas falhou parse ({e})")
        print("Erro: vault ja tem marker obsidian-master. Pra sincronizar, "
              "use obsidian-librarian. Pra reconstruir do zero, remova "
              ".obsidian-master/ e rode obsidian-init.", file=sys.stderr)
        return 1
    elif state == "empty":
        print("Vault vazio (ou sem .md fora de pastas ignoradas).")
        print("Sugestao: use obsidian-init pra scaffold de um vault do zero.")
        return 0
    else:  # existing
        print("Vault existente sem marker. Pronto pra migracao.")
        print("Proximo passo: migrate.py shadow-scan --vault PATH (Wave 2)")
        return 0


def _stub(wave: int, cmd: str):
    """Gera um handler stub pra subcommand nao implementado ainda."""
    def handler(args) -> int:
        print(f"Subcommand '{cmd}' ainda nao implementado (planejado pra Wave {wave}).",
              file=sys.stderr)
        return 2
    return handler


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="migrate.py",
        description=(
            "CLI do skill obsidian-migrate. Adota o kit em vault existente "
            "sem destruir estrutura (Opcao C hibrida). Fluxo: status -> "
            "shadow-scan -> cluster -> propose -> plan -> approve -> apply."
        ),
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    # Wave 1: status
    p_st = sub.add_parser("status", help="Detecta estado do vault (empty|existing|already_migrated)")
    p_st.add_argument("--vault", required=True, help="Raiz do vault a inspecionar")
    p_st.set_defaults(func=cmd_status)

    # Stubs pras proximas waves
    for (w, name, help_text) in [
        (2, "shadow-scan", "Backup + scan inicial sem mover arquivos"),
        (3, "cluster",     "HDBSCAN sobre embeddings + labels de cluster"),
        (4, "propose",     "Gera migration-proposal.md + CLAUDE.md preview"),
        (5, "plan",        "Popula migration_plan em lotes de 20"),
        (5, "approve",     "Approval interativo por batch"),
        (6, "apply",       "Aplica renames do batch (Wave 6)"),
        (6, "rollback",    "Reverte renames do batch (Wave 6)"),
    ]:
        p_cmd = sub.add_parser(name, help=help_text)
        p_cmd.add_argument("--vault", required=True)
        p_cmd.set_defaults(func=_stub(w, name))

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
