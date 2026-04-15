#!/usr/bin/env python3
"""PostToolUse hook for obsidian-master-kit.

Detects writes inside a vault marked with `.obsidian-master/marker.json` and:

1.  (v1.0 vaults) Abre o DB do vault, chama `core.scanner.scan_single_file`
    pro arquivo modificado e grava um evento `note_created`/`note_updated`/
    `note_deleted` correspondente na tabela `events`. Emissao imediata
    (nao depende do agente invocar a skill).
2.  Injeta `additionalContext` no turno sinalizando o agente a rodar a
    skill `obsidian-librarian` pra fazer sync completo (revalida
    frontmatter, regenera `_INDEX.md`, detecta orfas). Hooks do Claude
    Code nao chamam skills — por isso o signal.

Fallback: vaults v0.1.1 (sem `.obsidian-master/db.sqlite`) seguem no
comportamento antigo (signal-only, <10ms). QUALQUER excecao no bloco DB
e logada em `.obsidian-master/hook-errors.log` e o hook degrada pro
signal-only — nao crasha o Write do usuario. Exit code sempre 0 pra
Write continuar.

Dedup: injeta `additionalContext` no maximo 1x a cada 5s por vault
(`.obsidian-master/last-hook.txt`), evitando loop quando o agente faz
burst de edits.
"""
from __future__ import annotations

import datetime as _dt
import importlib.util as _ilu
import json
import pathlib
import sqlite3
import sys
import time
import traceback
import types as _types

DEDUPE_WINDOW_SECONDS = 5
RELEVANT_TOOLS = {"Write", "Edit", "NotebookEdit"}
MARKER_REL = pathlib.Path(".obsidian-master") / "marker.json"
DB_REL = pathlib.Path(".obsidian-master") / "db.sqlite"
ERROR_LOG_REL = pathlib.Path(".obsidian-master") / "hook-errors.log"
FASTPATH_OPTOUT_REL = pathlib.Path(".obsidian-master") / "hook-fastpath-disabled.txt"

# Raiz do repo = parent do hooks/. Usado pra localizar core/.
_CORE_DIR = pathlib.Path(__file__).resolve().parents[1] / "core"


# ---------- isolated loader pra core.* (mesmo padrao de update_index.py) ----------

def _load_core_module(mod_name: str, filename: str):
    """Carrega `core/<filename>` como `core.<mod_name>` sem executar
    `core/__init__.py` (que puxa networkx/model2vec). Idempotente.
    """
    qualified = f"core.{mod_name}"
    if qualified in sys.modules:
        return sys.modules[qualified]

    if "core" not in sys.modules:
        pkg = _types.ModuleType("core")
        pkg.__path__ = [str(_CORE_DIR)]  # type: ignore[attr-defined]
        sys.modules["core"] = pkg

    path = _CORE_DIR / filename
    spec = _ilu.spec_from_file_location(qualified, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"core/{filename} nao encontrado em {path}")
    module = _ilu.module_from_spec(spec)
    sys.modules[qualified] = module
    spec.loader.exec_module(module)
    setattr(sys.modules["core"], mod_name, module)
    return module


# ---------- helpers ----------

def find_vault_root(file_path: pathlib.Path) -> pathlib.Path | None:
    cur = file_path.parent
    while cur != cur.parent:
        if (cur / MARKER_REL).exists():
            return cur
        cur = cur.parent
    return None


def should_emit(vault_root: pathlib.Path) -> bool:
    tracker = vault_root / ".obsidian-master" / "last-hook.txt"
    now = int(time.time())
    if tracker.exists():
        try:
            last = int(tracker.read_text().strip())
            if now - last < DEDUPE_WINDOW_SECONDS:
                return False
        except ValueError:
            pass
    tracker.parent.mkdir(parents=True, exist_ok=True)
    tracker.write_text(str(now))
    return True


def _log_hook_error(vault_root: pathlib.Path, exc: BaseException) -> None:
    """Append de erro em `.obsidian-master/hook-errors.log`. Nunca re-raise.

    Se ate o log falhar (ex: FS read-only), engolimos — hook JAMAIS pode
    crashear o Write do usuario.
    """
    try:
        log_path = vault_root / ERROR_LOG_REL
        log_path.parent.mkdir(parents=True, exist_ok=True)
        ts = _dt.datetime.now(_dt.timezone.utc).isoformat()
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        with log_path.open("a", encoding="utf-8") as f:
            f.write(f"[{ts}] {type(exc).__name__}: {exc}\n{tb}\n")
    except Exception:
        pass


def _emit_note_event(conn: sqlite3.Connection, change) -> None:
    """Insere evento `note_created`/`note_updated`/`note_deleted` em `events`.

    Usa o mesmo formato de ts que `update_index.py::_insert_event` (ISO-8601
    UTC sem microsegundos) pra consistencia de dedup/queries. Nao emite
    `scan_run` (esse fica a cargo do librarian quando o agente rodar o
    sync full).
    """
    kind_to_event = {
        "created": "note_created",
        "updated": "note_updated",
        "deleted": "note_deleted",
    }
    event_type = kind_to_event.get(change.kind)
    if event_type is None or change.note_id is None:
        return

    # area_id resolvido via SELECT — scanner ja persistiu a nota
    row = conn.execute(
        "SELECT area_id FROM notes WHERE id=?", (change.note_id,)
    ).fetchone()
    area_id = row[0] if row is not None else None

    now_dt = _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0)
    ts = now_dt.isoformat()
    date = ts[:10]
    metadata = json.dumps({"triggered_by": "hook"}, ensure_ascii=False)
    conn.execute(
        "INSERT INTO events (note_id, area_id, event_type, ts, date, "
        "word_delta, metadata_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            change.note_id,
            area_id,
            event_type,
            ts,
            date,
            change.word_delta,
            metadata,
        ),
    )
    conn.commit()


def _try_fastpath(vault_root: pathlib.Path, file_path: pathlib.Path) -> None:
    """Opens DB, roda scan_single_file, emite event. Silencioso em sucesso.

    Raises em erro — caller decide se loga + fallback. Guard externo:
    `.obsidian-master/hook-fastpath-disabled.txt` desliga o fastpath.
    """
    if (vault_root / FASTPATH_OPTOUT_REL).exists():
        return

    db_path = vault_root / DB_REL
    if not db_path.exists():
        # vault v0.1.1 — fallback silencioso pro signal-only
        return

    core_db = _load_core_module("db", "db.py")
    core_scanner = _load_core_module("scanner", "scanner.py")
    conn = core_db.connect(vault_root)
    try:
        change = core_scanner.scan_single_file(conn, vault_root, file_path)
        if change and change.kind in ("created", "updated", "deleted"):
            _emit_note_event(conn, change)
    finally:
        conn.close()


# ---------- entrypoint ----------

def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    tool_name = payload.get("tool_name", "")
    if tool_name not in RELEVANT_TOOLS:
        return 0

    tool_input = payload.get("tool_input", {}) or {}
    raw_path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
    if not raw_path:
        return 0

    file_path = pathlib.Path(raw_path)
    vault_root = find_vault_root(file_path)
    if vault_root is None:
        return 0

    # --- fastpath: emissao imediata de event via scan_single_file ---
    # Erros aqui NUNCA propagam pra fora do hook — log + fallback signal-only.
    try:
        _try_fastpath(vault_root, file_path)
    except (ImportError, sqlite3.OperationalError, sqlite3.DatabaseError, OSError) as exc:
        _log_hook_error(vault_root, exc)
    except Exception as exc:  # last-resort guard
        _log_hook_error(vault_root, exc)

    # --- signal-only fallback (sempre roda, preserva v0.1.1 behavior) ---
    if not should_emit(vault_root):
        return 0

    message = (
        f"Voce acabou de escrever em um vault obsidian-master-kit "
        f"(raiz: `{vault_root}`). Arquivo modificado: `{file_path}`. "
        f"Invoque agora a skill `obsidian-librarian` para sincronizar o vault "
        f"(valida frontmatter, atualiza _INDEX.md, detecta orfas). "
        f"Execute: python3 ${{CLAUDE_PLUGIN_ROOT}}/skills/obsidian-librarian/"
        f"scripts/update_index.py --vault \"{vault_root}\""
    )

    output = {
        "continue": True,
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": message,
        },
    }
    sys.stdout.write(json.dumps(output))
    return 0


if __name__ == "__main__":
    sys.exit(main())
