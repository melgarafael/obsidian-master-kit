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

import importlib.util  # noqa: E402

from core.db import connect  # noqa: E402
from core.paths import resolve_vault  # noqa: E402

_GAPS_PATH = pathlib.Path(__file__).parent / "gaps.py"
_KNN_PATH = pathlib.Path(__file__).parent / "knn.py"
_GENERATE_PATH = pathlib.Path(__file__).parent / "generate.py"


def _load_by_path(module_name: str, file_path: pathlib.Path):
    # Reusa se ja importado (evita reload entre sub-comandos) e registra em
    # sys.modules ANTES do exec_module — dataclasses precisa resolver
    # `cls.__module__` em sys.modules pra annotations funcionarem.
    existing = sys.modules.get(module_name)
    if existing is not None:
        return existing
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


def _emit(payload: dict[str, Any]) -> None:
    """Imprime envelope JSON estavel em stdout."""
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _base_payload(cmd: str, vault: pathlib.Path, conn, args: argparse.Namespace) -> dict[str, Any]:
    return {
        "command": cmd,
        "vault": str(vault),
        "vec_index": "ok" if getattr(conn, "vec_loaded", False) else "fallback",
        "dry_run": bool(getattr(args, "dry_run", True)),
    }


def _serialize_candidate(c) -> dict[str, Any]:
    return {
        "kind": c.kind,
        "target_note_ids": list(c.target_note_ids),
        "content": c.content,
        "reasoning": c.reasoning,
        "score": round(float(c.score), 4),
    }


# ---------- sub-comandos ----------


def cmd_bridges(args: argparse.Namespace) -> int:
    vault = resolve_vault(args.vault)
    conn = connect(vault)
    gaps = _load_by_path("_expand_gaps", _GAPS_PATH)
    candidates = gaps.detect_bridges(conn, min_cos=args.min_cos)
    # Filtro de topico: mantem candidato se algum target tem a tag exata.
    if args.topic:
        candidates = _filter_by_topic(conn, candidates, args.topic)
    persisted = 0
    if not args.dry_run and candidates:
        persisted = gaps.persist(conn, candidates)
    payload = _base_payload("bridges", vault, conn, args)
    payload.update(
        {
            "topic": args.topic,
            "min_cos": args.min_cos,
            "candidates": [_serialize_candidate(c) for c in candidates],
            "count": len(candidates),
            "persisted": persisted,
        }
    )
    _emit(payload)
    return 0


def cmd_moc(args: argparse.Namespace) -> int:
    vault = resolve_vault(args.vault)
    conn = connect(vault)
    gaps = _load_by_path("_expand_gaps", _GAPS_PATH)
    candidates = gaps.detect_moc_shallow(conn)
    # Filtra pro MOC especificado via path relativo (match exato).
    moc_path = args.moc_path
    cursor = conn.execute("SELECT id FROM notes WHERE path = ?", (moc_path,))
    row = cursor.fetchone()
    target_id = row[0] if row else None
    if target_id is None:
        payload = _base_payload("moc", vault, conn, args)
        payload.update(
            {
                "moc_path": moc_path,
                "candidates": [],
                "count": 0,
                "persisted": 0,
                "note": f"Nota MOC '{moc_path}' nao encontrada no vault.",
            }
        )
        _emit(payload)
        return 0
    filtered = [c for c in candidates if target_id in c.target_note_ids]
    persisted = 0
    if not args.dry_run and filtered:
        persisted = gaps.persist(conn, filtered)
    payload = _base_payload("moc", vault, conn, args)
    payload.update(
        {
            "moc_path": moc_path,
            "candidates": [_serialize_candidate(c) for c in filtered],
            "count": len(filtered),
            "persisted": persisted,
        }
    )
    _emit(payload)
    return 0


def cmd_gaps(args: argparse.Namespace) -> int:
    vault = resolve_vault(args.vault)
    conn = connect(vault)
    gaps = _load_by_path("_expand_gaps", _GAPS_PATH)
    candidates = gaps.run_all(conn)
    if args.area:
        candidates = _filter_by_area(conn, candidates, args.area)
    persisted = 0
    if not args.dry_run and candidates:
        persisted = gaps.persist(conn, candidates)
    payload = _base_payload("gaps", vault, conn, args)
    payload.update(
        {
            "area": args.area,
            "candidates": [_serialize_candidate(c) for c in candidates],
            "count": len(candidates),
            "persisted": persisted,
            "by_kind": _count_by_kind(candidates),
        }
    )
    _emit(payload)
    return 0


def cmd_from(args: argparse.Namespace) -> int:
    vault = resolve_vault(args.vault)
    conn = connect(vault)
    knn = _load_by_path("_expand_knn_cli", _KNN_PATH)
    cursor = conn.execute("SELECT id FROM notes WHERE path = ?", (args.note,))
    row = cursor.fetchone()
    if row is None:
        payload = _base_payload("from", vault, conn, args)
        payload.update(
            {
                "note": args.note,
                "k": args.k,
                "neighbors": [],
                "note_err": f"Nota '{args.note}' nao encontrada no vault.",
            }
        )
        _emit(payload)
        return 0
    seed_id = row[0]
    neighbors = knn.knn(conn, seed_id, k=args.k)
    # Anota nome/path + converte distance -> cos pra leitura humana
    enriched: list[dict[str, Any]] = []
    for nid, dist in neighbors:
        nrow = conn.execute(
            "SELECT path, title FROM notes WHERE id = ?", (nid,)
        ).fetchone()
        if nrow is None:
            continue
        cos = max(-1.0, min(1.0, 1.0 - dist / 2.0))
        enriched.append(
            {
                "id": nid,
                "path": nrow[0],
                "title": nrow[1],
                "distance": round(float(dist), 4),
                "cos": round(float(cos), 4),
            }
        )
    payload = _base_payload("from", vault, conn, args)
    payload.update(
        {
            "note": args.note,
            "seed_id": seed_id,
            "k": args.k,
            "neighbors": enriched,
            "count": len(enriched),
        }
    )
    _emit(payload)
    return 0


# ---------- filtro helpers ----------


def _filter_by_topic(conn, candidates, topic: str):
    """Mantem candidato se algum target tem tag cujo path contem `topic`."""
    topic_low = topic.lower()
    kept = []
    for c in candidates:
        placeholders = ",".join("?" * len(c.target_note_ids))
        rows = conn.execute(
            f"""
            SELECT DISTINCT t.tag
            FROM note_tags nt
            JOIN tags t ON t.id = nt.tag_id
            WHERE nt.note_id IN ({placeholders})
            """,
            c.target_note_ids,
        ).fetchall()
        tags_low = {r[0].lower() for r in rows}
        if any(topic_low in t for t in tags_low):
            kept.append(c)
    return kept


def _filter_by_area(conn, candidates, area_name: str):
    """Mantem candidato cujos targets ESTAO TODOS na area."""
    row = conn.execute(
        "SELECT id FROM areas WHERE LOWER(name) = ?", (area_name.lower(),)
    ).fetchone()
    if row is None:
        return []
    area_id = row[0]
    kept = []
    for c in candidates:
        if not c.target_note_ids:
            continue
        placeholders = ",".join("?" * len(c.target_note_ids))
        rows = conn.execute(
            f"SELECT area_id FROM notes WHERE id IN ({placeholders})",
            c.target_note_ids,
        ).fetchall()
        if all(r[0] == area_id for r in rows):
            kept.append(c)
    return kept


def _count_by_kind(candidates) -> dict[str, int]:
    counts: dict[str, int] = {}
    for c in candidates:
        counts[c.kind] = counts.get(c.kind, 0) + 1
    return counts


def cmd_generate(args: argparse.Namespace) -> int:
    vault = resolve_vault(args.vault)
    conn = connect(vault)
    gen = _load_by_path("_expand_generate", _GENERATE_PATH)
    result = gen.generate_note(
        conn, args.suggestion_id, vault, dry_run=bool(args.dry_run)
    )
    payload = _base_payload("generate", vault, conn, args)
    payload["suggestion_id"] = args.suggestion_id
    payload.update(result)
    _emit(payload)
    return 0 if "error" not in result else 1


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
