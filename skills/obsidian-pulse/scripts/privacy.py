"""privacy.py — Redaction layer (Epic 06 S08 / Wave 8).

Le `.obsidian-master/blacklist.json` do vault (lista de glob patterns tipo
`00 - Pessoal/Journaling/**`), marca notas correspondentes como
`sensitive=1` e redige titulos/content em suggestions/alerts quando
servidos ao dashboard.

Toggle `show_sensitive` no dashboard libera exibir titulo real (default
off, sem permitir export CSV mesmo com on).
"""
from __future__ import annotations

import fnmatch
import json
import pathlib
import sqlite3
from typing import Any

from core.config import BLACKLIST_PATH_REL

__all__ = ["load_blacklist", "mark_sensitive_notes", "redact_entry"]


REDACTED_LABEL = "[item sensivel redigido]"


def load_blacklist(vault: pathlib.Path) -> list[str]:
    """Le blacklist.json. Retorna lista de globs (empty se nao existe)."""
    path = vault / BLACKLIST_PATH_REL
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if isinstance(data, dict):
        patterns = data.get("patterns") or []
    elif isinstance(data, list):
        patterns = data
    else:
        return []
    return [str(p) for p in patterns if isinstance(p, str)]


def _path_matches_any(path: str, patterns: list[str]) -> bool:
    for pat in patterns:
        if fnmatch.fnmatchcase(path, pat):
            return True
        # Glob recursivo: 00 - Pessoal/Journaling/** cobre subfolders
        if pat.endswith("/**") and path.startswith(pat[:-3]):
            return True
    return False


def mark_sensitive_notes(
    conn: sqlite3.Connection, vault: pathlib.Path
) -> int:
    """Aplica blacklist as notes.sensitive. Retorna count de notas marcadas."""
    patterns = load_blacklist(vault)
    if not patterns:
        return 0
    rows = conn.execute(
        "SELECT id, path FROM notes WHERE deleted_at IS NULL"
    ).fetchall()
    marked = 0
    for nid, path in rows:
        is_sensitive = _path_matches_any(path, patterns)
        conn.execute(
            "UPDATE notes SET sensitive = ? WHERE id = ?",
            (1 if is_sensitive else 0, nid),
        )
        if is_sensitive:
            marked += 1
    conn.commit()
    return marked


def _is_sensitive_note(conn: sqlite3.Connection, note_id: int) -> bool:
    row = conn.execute(
        "SELECT sensitive FROM notes WHERE id = ?", (note_id,)
    ).fetchone()
    return row is not None and row[0] == 1


def _area_label_for_note(conn: sqlite3.Connection, note_id: int) -> str:
    row = conn.execute(
        """
        SELECT COALESCE(a.label, a.slug, 'area')
        FROM notes n LEFT JOIN areas a ON a.id = n.area_id
        WHERE n.id = ?
        """,
        (note_id,),
    ).fetchone()
    if row is None or row[0] is None:
        return "area"
    return str(row[0])


def redact_entry(
    conn: sqlite3.Connection,
    entry: dict[str, Any],
    *,
    show_sensitive: bool = False,
) -> dict[str, Any]:
    """Redige content/reasoning se algum target e sensitive.

    Se show_sensitive=True, nao redige (mas nunca permite export, enforce
    in endpoint handler).
    """
    if show_sensitive:
        return entry
    target_ids = entry.get("target_note_ids") or []
    if not target_ids:
        return entry
    sensitive_ids = [
        nid for nid in target_ids if _is_sensitive_note(conn, nid)
    ]
    if not sensitive_ids:
        return entry
    area = _area_label_for_note(conn, sensitive_ids[0])
    redacted = dict(entry)
    redacted["content"] = f"{REDACTED_LABEL} em area {area}"
    redacted["reasoning"] = (
        f"Nota sensivel em area {area}. Toggle show_sensitive pra ver detalhes."
    )
    redacted["sensitive"] = True
    return redacted
