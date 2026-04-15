#!/usr/bin/env python3
"""pulse.py — CLI da skill `obsidian-pulse` (Epic 06).

Quatro sub-comandos:

- `refresh` — roda Stage B (batch analytics: FSRS, anomalies, ranking)
- `serve`   — sobe FastAPI + HTMX dashboard em 127.0.0.1:4711
- `daemon`  — `refresh` + `serve` em foreground
- `status`  — resumo do estado (ultimo run, contagens)

Stdlib + (sob demanda) FastAPI/uvicorn/jinja2/fsrs via extra
`obsidian-master-kit[pulse]`.

Shell (Wave 1): stubs com envelope JSON estavel. Waves 2-10
substituem incrementalmente.
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


WAVE_PLAN: dict[str, int] = {}  # todos os subcomandos wired

_WORKER_PATH = pathlib.Path(__file__).parent / "worker.py"
_SERVER_PATH = pathlib.Path(__file__).parent / "server.py"


def _emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _base(cmd: str, vault: pathlib.Path, conn, args) -> dict[str, Any]:
    return {
        "command": cmd,
        "vault": str(vault),
        "vec_index": "ok" if getattr(conn, "vec_loaded", False) else "fallback",
    }


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


def cmd_refresh(args) -> int:
    vault = resolve_vault(args.vault)
    conn = connect(vault)
    worker = _load_by_path("_pulse_worker", _WORKER_PATH)
    result = worker.run_batch_analytics(conn)
    payload = _base("refresh", vault, conn, args)
    payload.update(result)
    _emit(payload)
    return 0


def cmd_serve(args) -> int:
    vault = resolve_vault(args.vault)
    # Import lazy — FastAPI e extra opcional
    try:
        import uvicorn
    except ImportError:
        print(
            "Erro: dependencias do pulse nao instaladas.\n"
            "Instale com: pip install 'obsidian-master-kit[pulse]'",
            file=sys.stderr,
        )
        return 1
    server = _load_by_path("_pulse_server", _SERVER_PATH)
    app = server.build_app(vault)
    token = app.state.pulse_token
    print(f"obsidian-pulse servindo em http://127.0.0.1:{args.port}")
    print(f"Token pra /api/*: {token}")
    print(f"(gravado em {vault}/.obsidian-master/pulse-token.txt)")
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
    return 0


def cmd_daemon(args) -> int:
    """Daemon = refresh inicial + serve em foreground."""
    vault = resolve_vault(args.vault)
    conn = connect(vault)
    worker = _load_by_path("_pulse_worker", _WORKER_PATH)
    result = worker.run_batch_analytics(conn)
    print(
        f"Refresh inicial concluido em {result['total_duration_ms']:.0f}ms",
        file=sys.stderr,
    )
    conn.close()
    return cmd_serve(args)


def cmd_status(args) -> int:
    """Status ja e funcional na Wave 1 — so DB queries."""
    vault = resolve_vault(args.vault)
    conn = connect(vault)
    notes_active = conn.execute(
        "SELECT COUNT(*) FROM notes WHERE deleted_at IS NULL "
        "AND (status IS NULL OR status != 'arquivado')"
    ).fetchone()[0]
    last_scan = conn.execute(
        "SELECT MAX(ts) FROM events WHERE event_type='scan_run'"
    ).fetchone()[0]
    sugg_pending = conn.execute(
        "SELECT COUNT(*) FROM suggestions_cache "
        "WHERE dismissed=0 AND acted_on=0"
    ).fetchone()[0]
    alerts_pending = conn.execute(
        "SELECT COUNT(*) FROM alerts_cache WHERE dismissed=0"
    ).fetchone()[0]
    payload = _base("status", vault, conn, args)
    payload.update({
        "notes_active": int(notes_active),
        "last_scan": last_scan,
        "suggestions_pending": int(sugg_pending),
        "alerts_pending": int(alerts_pending),
    })
    _emit(payload)
    return 0


def _add_common(p):
    p.add_argument("--vault", metavar="PATH", help="Vault root (auto via marker).")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="obsidian-pulse",
        description="Dashboard localhost + worker batch — Netflix/YouTube pessoal pro vault.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True, metavar="SUBCOMMAND")

    p_r = sub.add_parser("refresh", help="Roda Stage B (batch analytics).")
    _add_common(p_r)
    p_r.set_defaults(func=cmd_refresh)

    p_s = sub.add_parser("serve", help="Sobe FastAPI dashboard em 127.0.0.1:PORT.")
    _add_common(p_s)
    p_s.add_argument("--port", type=int, default=4711, help="Default: 4711")
    p_s.set_defaults(func=cmd_serve)

    p_d = sub.add_parser("daemon", help="Refresh + serve em foreground.")
    _add_common(p_d)
    p_d.add_argument("--port", type=int, default=4711)
    p_d.set_defaults(func=cmd_daemon)

    p_st = sub.add_parser("status", help="Status resumido (ultimo run, contagens).")
    _add_common(p_st)
    p_st.set_defaults(func=cmd_status)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
