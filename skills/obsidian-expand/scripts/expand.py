#!/usr/bin/env python3
"""expand.py — CLI da skill `obsidian-expand` (Epic 05).

Cinco sub-comandos:

- `bridges`   — pontes semanticas (pares proximos sem link direto)
- `moc`       — expande um MOC especifico que esta raso
- `gaps`      — gaps semanticos numa area
- `from`      — expansao a partir de uma nota seed (top-K vizinhos)
- `generate`  — materializa uma sugestao aprovada em .md real (invoca LLM)

Os 4 primeiros sao comandos de ANALISE e nunca escrevem arquivo `.md`
quando invocados com `--dry-run` (default). `generate` e o unico que
produz arquivo novo — requer aprovacao explicita via `--suggestion-id`.

Stdlib para o shell. Dependencias do vault (sqlite-vec, Model2Vec) sao
carregadas sob demanda por cada sub-comando que precisa.

Shell (Wave 1): os comandos validam vault + DB + conectividade de
embedder, imprimem envelope JSON vazio com campo `planned_for_wave` e
saem com exit code 0. A logica real entra nas waves seguintes (S02
KNN, S03 gap detection, S04 generation, S05 librarian integration).

Exit codes: 0 ok, 1 erro esperado, 2 argparse.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
from typing import Any

# Permite invocar o script direto (sem pip install -e) resolvendo o repo
# root como ancestor do script e adicionando-o ao sys.path.
_SCRIPT = pathlib.Path(__file__).resolve()
_REPO_ROOT = _SCRIPT.parent.parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from core.db import connect  # noqa: E402
from core.paths import resolve_vault  # noqa: E402

WAVE_PLAN = {
    "bridges": 3,
    "moc": 3,
    "gaps": 3,
    "from": 3,
    "generate": 4,
}


def _emit(payload: dict[str, Any]) -> None:
    """Imprime envelope JSON estavel em stdout."""
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _shell_stub(cmd: str, args: argparse.Namespace, extra: dict[str, Any]) -> int:
    """Esqueleto comum aos sub-comandos de analise enquanto a logica
    esta em waves futuras. Valida vault + DB + abre conexao (garante que o
    ambiente esta sao), imprime envelope JSON com marcador de wave
    pendente, sai 0.
    """
    vault = resolve_vault(args.vault)
    conn = connect(vault)
    vec_status = "ok" if getattr(conn, "vec_loaded", False) else "fallback"
    payload: dict[str, Any] = {
        "command": cmd,
        "vault": str(vault),
        "vec_index": vec_status,
        "dry_run": bool(getattr(args, "dry_run", True)),
        "candidates": [],
        "wave_pending": True,
        "planned_for_wave": WAVE_PLAN[cmd],
        "note": (
            "Shell da Wave 1 (Epic 05 S01). Logica chega na "
            f"Wave {WAVE_PLAN[cmd]}."
        ),
    }
    payload.update(extra)
    _emit(payload)
    return 0


# ---------- sub-comandos ----------


def cmd_bridges(args: argparse.Namespace) -> int:
    extra = {"topic": args.topic, "min_cos": args.min_cos}
    return _shell_stub("bridges", args, extra)


def cmd_moc(args: argparse.Namespace) -> int:
    extra = {"moc_path": args.moc_path}
    return _shell_stub("moc", args, extra)


def cmd_gaps(args: argparse.Namespace) -> int:
    extra = {"area": args.area}
    return _shell_stub("gaps", args, extra)


def cmd_from(args: argparse.Namespace) -> int:
    extra = {"note": args.note, "k": args.k}
    return _shell_stub("from", args, extra)


def cmd_generate(args: argparse.Namespace) -> int:
    # `generate` e distinto: nao e analise, materializa sugestao. Tambem
    # fica stub ate Wave 4.
    vault = resolve_vault(args.vault)
    conn = connect(vault)
    _emit(
        {
            "command": "generate",
            "vault": str(vault),
            "suggestion_id": args.suggestion_id,
            "dry_run": bool(args.dry_run),
            "written_path": None,
            "wave_pending": True,
            "planned_for_wave": WAVE_PLAN["generate"],
            "note": (
                "Shell da Wave 1 (Epic 05 S01). Geracao via LLM chega "
                "na Wave 4 (S04)."
            ),
        }
    )
    _ = conn  # garante que DB abriu ok antes de reportar
    return 0


# ---------- argparse ----------


def _add_common(p: argparse.ArgumentParser, *, include_dry_run: bool = True) -> None:
    p.add_argument(
        "--vault",
        metavar="PATH",
        help="Path do vault root. Se omitido, auto-detecta via ancestor com .obsidian-master/marker.json.",
    )
    if include_dry_run:
        p.add_argument(
            "--dry-run",
            action="store_true",
            default=True,
            help="Default. Imprime propostas sem escrever nada. Use --no-dry-run pra materializar (apos aprovacao).",
        )
        p.add_argument(
            "--no-dry-run",
            dest="dry_run",
            action="store_false",
            help="Materializa (quando aplicavel ao sub-comando).",
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="obsidian-expand",
        description=(
            "Gera notas-ponte usando apenas conteudo do vault como fonte. "
            "Detecta gaps semanticos, expande MOCs rasos, propoe notas de "
            "conceito implicitas."
        ),
    )
    sub = parser.add_subparsers(dest="cmd", required=True, metavar="SUBCOMMAND")

    p_bridges = sub.add_parser(
        "bridges",
        help="Pontes semanticas (pares proximos sem link direto).",
    )
    _add_common(p_bridges)
    p_bridges.add_argument("--topic", help="Filtra pontes que envolvem esse topico/tag.")
    p_bridges.add_argument(
        "--min-cos",
        type=float,
        default=None,
        help="Override do threshold minimo de similaridade (default: core.config.BRIDGE_MIN_COS).",
    )
    p_bridges.set_defaults(func=cmd_bridges)

    p_moc = sub.add_parser("moc", help="Expande um MOC especifico que esta raso.")
    _add_common(p_moc)
    p_moc.add_argument("--moc-path", required=True, help="Path relativo do MOC no vault.")
    p_moc.set_defaults(func=cmd_moc)

    p_gaps = sub.add_parser("gaps", help="Gaps semanticos numa area.")
    _add_common(p_gaps)
    p_gaps.add_argument("--area", help="Area canonica (pessoal/profissional/pesquisa/ai-memory).")
    p_gaps.set_defaults(func=cmd_gaps)

    p_from = sub.add_parser("from", help="Expansao a partir de uma nota seed.")
    _add_common(p_from)
    p_from.add_argument("--note", required=True, help="Path relativo da nota seed.")
    p_from.add_argument("--k", type=int, default=20, help="Top-K vizinhos (default: 20).")
    p_from.set_defaults(func=cmd_from)

    p_gen = sub.add_parser(
        "generate",
        help="Materializa uma sugestao aprovada em .md (invoca LLM).",
    )
    _add_common(p_gen)
    p_gen.add_argument(
        "--suggestion-id",
        type=int,
        required=True,
        help="ID da sugestao em suggestions_cache a materializar.",
    )
    p_gen.set_defaults(func=cmd_generate)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
