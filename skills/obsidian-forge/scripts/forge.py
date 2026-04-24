#!/usr/bin/env python3
"""CLI entry do obsidian-forge."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _detectar_vault(start: Path | None = None) -> Path:
    p = (start or Path.cwd()).resolve()
    for cand in [p, *p.parents]:
        if (cand / ".obsidian-master" / "marker.json").exists():
            return cand
    raise FileNotFoundError("Vault nao encontrado. Use --vault PATH.")


def cmd_scan(args: argparse.Namespace) -> int:
    sys.path.insert(0, str(Path(__file__).parent))
    from scan_context import scan, init_config
    vault = Path(args.vault).resolve() if args.vault else _detectar_vault()

    if args.init:
        print("Quais pastas o forge deve vigiar? (ENTER duplo termina)")
        pastas: list[str] = []
        while True:
            try:
                linha = input("> ").strip()
            except EOFError:
                break
            if not linha:
                break
            p = Path(linha).expanduser()
            if not p.exists():
                print(f"  pasta inexistente: {p}")
                continue
            pastas.append(str(p))
        if not pastas:
            print("Nenhuma pasta. Abortado.")
            return 1
        cfg = init_config(vault_root=vault, pastas=pastas)
        print(f"Config salvo: {cfg}")
        return 0

    if args.add:
        from frontmatter import read_frontmatter, write_frontmatter
        cfg_path = vault / "04 - Negocio" / "_config-scan.md"
        if not cfg_path.exists():
            print("Rode --init antes.")
            return 1
        meta, body = read_frontmatter(cfg_path)
        pastas = list(meta.get("pastas_observadas", []))
        if args.add not in pastas:
            pastas.append(args.add)
            meta["pastas_observadas"] = pastas
            write_frontmatter(cfg_path, meta, body)
            print(f"Adicionado: {args.add}")
        return 0

    try:
        scan(vault_root=vault, silent=args.silent, quick=args.quick)
        return 0
    except FileNotFoundError as e:
        print(f"Erro: {e}")
        return 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="forge")
    p.add_argument("--vault")
    sub = p.add_subparsers(dest="cmd", required=True)
    ps = sub.add_parser("scan")
    ps.add_argument("--init", action="store_true")
    ps.add_argument("--silent", action="store_true")
    ps.add_argument("--quick", action="store_true")
    ps.add_argument("--add")
    ps.set_defaults(func=cmd_scan)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
