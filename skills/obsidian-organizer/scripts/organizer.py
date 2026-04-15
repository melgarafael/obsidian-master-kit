#!/usr/bin/env python3
"""organizer.py — CLI da skill `obsidian-organizer` (Epic 04).

Seis sub-comandos:

- `cluster`        — HDBSCAN sobre vec_notes + TF-IDF labeling
- `duplicates`     — pares com cos >= DUPLICATE_MIN_COS
- `moc-audit`      — clusters >= 10 sem MOC proprio
- `area-mismatch`  — notas com `frontmatter.area` != pasta
- `propose`        — agrega tudo em migration_plan (dry-run default)
- `report`         — relatorio visual consolidado

Stdlib + (sob demanda) scikit-learn / sqlite-vec / numpy.

Shell (Wave 1): cada comando valida vault + DB + abre conexao, imprime
envelope JSON estavel com `wave_pending=True` e `planned_for_wave` apontando
a onda que entrega a logica real. As demais waves substituem os stubs.

Exit codes: 0 ok, 1 erro esperado, 2 argparse.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import pathlib
import sys
from typing import Any

_SCRIPT = pathlib.Path(__file__).resolve()
_REPO_ROOT = _SCRIPT.parent.parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from core.db import connect  # noqa: E402
from core.paths import resolve_vault  # noqa: E402

WAVE_PLAN = {
    "duplicates": 3,
    "moc-audit": 4,
    "area-mismatch": 5,
    "propose": 6,
    "report": 6,
}

_CLUSTER_PATH = pathlib.Path(__file__).parent / "cluster.py"


def _emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _base(cmd: str, vault: pathlib.Path, conn, args) -> dict[str, Any]:
    """Envelope base. Stubs adicionam wave_pending/planned_for_wave manualmente."""
    return {
        "command": cmd,
        "vault": str(vault),
        "vec_index": "ok" if getattr(conn, "vec_loaded", False) else "fallback",
        "dry_run": bool(getattr(args, "dry_run", True)),
    }


def _stub_payload(cmd: str, vault: pathlib.Path, conn, args) -> dict[str, Any]:
    p = _base(cmd, vault, conn, args)
    p["wave_pending"] = True
    p["planned_for_wave"] = WAVE_PLAN[cmd]
    return p


def _load_by_path(module_name: str, file_path: pathlib.Path):
    existing = sys.modules.get(module_name)
    if existing is not None:
        return existing
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------- sub-comandos ----------


def cmd_cluster(args) -> int:
    vault = resolve_vault(args.vault)
    conn = connect(vault)
    cluster = _load_by_path("_organizer_cluster", _CLUSTER_PATH)
    if args.latest:
        # Apenas lista clusters do ultimo run persistido, sem re-rodar
        row = conn.execute(
            "SELECT run_id FROM clusters ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        if row is None:
            _emit(
                _base("cluster", vault, conn, args)
                | {"latest": True, "clusters": [], "run_id": None,
                   "note": "Nenhum run persistido ainda. Rode 'cluster' sem --latest."}
            )
            return 0
        run_id = row[0]
        rows = conn.execute(
            """
            SELECT id, label, note_count, proposed_area_id
            FROM clusters WHERE run_id = ? ORDER BY note_count DESC
            """,
            (run_id,),
        ).fetchall()
        payload = _base("cluster", vault, conn, args) | {
            "latest": True,
            "ai_label": args.ai_label,
            "run_id": run_id,
            "clusters": [
                {
                    "id": r[0],
                    "label": r[1],
                    "note_count": r[2],
                    "dominant_area_id": r[3],
                }
                for r in rows
            ],
        }
        _emit(payload)
        return 0
    result = cluster.run(conn)
    payload = _base("cluster", vault, conn, args)
    payload.update({"latest": False, "ai_label": args.ai_label})
    payload.update(result)
    _emit(payload)
    return 0 if "error" not in result else 1


def cmd_duplicates(args) -> int:
    vault = resolve_vault(args.vault)
    conn = connect(vault)
    payload = _stub_payload("duplicates", vault, conn, args)
    payload.update(
        {
            "min_cos": args.min_cos,
            "interactive": args.interactive,
            "candidates": [],
        }
    )
    _emit(payload)
    return 0


def cmd_moc_audit(args) -> int:
    vault = resolve_vault(args.vault)
    conn = connect(vault)
    payload = _stub_payload("moc-audit", vault, conn, args)
    payload.update(
        {
            "create_suggestions": args.create_suggestions,
            "missing_moc": [],
        }
    )
    _emit(payload)
    return 0


def cmd_area_mismatch(args) -> int:
    vault = resolve_vault(args.vault)
    conn = connect(vault)
    payload = _stub_payload("area-mismatch", vault, conn, args)
    payload.update(
        {
            "fix": args.fix,
            "mismatches": [],
        }
    )
    _emit(payload)
    return 0


def cmd_propose(args) -> int:
    vault = resolve_vault(args.vault)
    conn = connect(vault)
    payload = _stub_payload("propose", vault, conn, args)
    payload.update({"batches": []})
    _emit(payload)
    return 0


def cmd_report(args) -> int:
    vault = resolve_vault(args.vault)
    conn = connect(vault)
    payload = _stub_payload("report", vault, conn, args)
    payload.update({"summary": {}})
    _emit(payload)
    return 0


# ---------- argparse ----------


def _add_common(p):
    p.add_argument("--vault", metavar="PATH", help="Vault root (auto-descobre via marker).")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="obsidian-organizer",
        description="Organizador semantico do vault: clusters, duplicatas, MOCs faltando, area-mismatch.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True, metavar="SUBCOMMAND")

    p_cl = sub.add_parser("cluster", help="HDBSCAN runner + TF-IDF labeling")
    _add_common(p_cl)
    p_cl.add_argument("--latest", action="store_true", help="Mostra so o ultimo run.")
    p_cl.add_argument("--ai-label", action="store_true", help="Rotula via Claude (custo).")
    p_cl.set_defaults(func=cmd_cluster, dry_run=True)

    p_du = sub.add_parser("duplicates", help="Pares de notas com cos alto")
    _add_common(p_du)
    p_du.add_argument("--min-cos", type=float, default=None, help="Override DUPLICATE_MIN_COS.")
    p_du.add_argument("--interactive", action="store_true", help="Pede verdict (merge/keep/not).")
    p_du.set_defaults(func=cmd_duplicates, dry_run=True)

    p_moc = sub.add_parser("moc-audit", help="Clusters >= 10 sem MOC proprio")
    _add_common(p_moc)
    p_moc.add_argument("--create-suggestions", action="store_true",
                       help="Grava sugestoes 'moc_missing' + gera stub .md.")
    p_moc.set_defaults(func=cmd_moc_audit, dry_run=True)

    p_am = sub.add_parser("area-mismatch", help="frontmatter.area != pasta")
    _add_common(p_am)
    p_am.add_argument("--fix", action="store_true", help="Oferece aplicacao interativa.")
    p_am.set_defaults(func=cmd_area_mismatch, dry_run=True)

    p_pr = sub.add_parser("propose", help="Agrega tudo em migration_plan (lotes)")
    _add_common(p_pr)
    p_pr.add_argument("--dry-run", action="store_true", default=True,
                      help="Default. Nao escreve migration_plan.")
    p_pr.add_argument("--no-dry-run", dest="dry_run", action="store_false",
                      help="Escreve de fato em migration_plan.")
    p_pr.set_defaults(func=cmd_propose)

    p_re = sub.add_parser("report", help="Relatorio visual consolidado")
    _add_common(p_re)
    p_re.set_defaults(func=cmd_report, dry_run=True)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
