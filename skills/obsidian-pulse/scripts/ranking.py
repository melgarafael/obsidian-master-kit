"""ranking.py — Recommendation ranking + anti-repeticao (Epic 06 S05 / Wave 5).

Pondera sugestoes ativas por kind (formula BRIEF §3.3) + aplica decay de
anti-repeticao:

- Sugestao mostrada nos ultimos 7 dias sem acao: score *= 0.5
- Sugestao dismissed: score *= 0.1 por 30 dias
- Sugestoes do mesmo kind repetidas: decay (2a=0.7, 3a=0.4, 4a+=0.1)

Top 10 por run (hard cap anti-spam da BRIEF).
"""
from __future__ import annotations

import datetime as _dt
import json
import sqlite3
from typing import Any

from core.config import SUGGESTIONS_PER_RUN_MAX

__all__ = ["rank", "select_top"]


# Pesos por kind (aproxima formula BRIEF §3.3).
_KIND_WEIGHT = {
    "review": 0.35,            # FSRS due
    "bridge": 0.25,            # orphan proximity
    "reference_missing": 0.20, # cluster dormancy
    "moc_missing": 0.20,       # cluster dormancy (MOC)
    "moc_expand": 0.20,
    "area_mismatch": 0.15,     # nao e core rec, mas util
}
_DEFAULT_WEIGHT = 0.10


# Decay per-kind repetition (2a, 3a, 4a+)
_SAME_KIND_DECAY = [1.0, 0.7, 0.4, 0.1]


def _active_suggestions(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, kind, target_note_ids, content, reasoning,
               COALESCE(score, 0.5), generated_at
        FROM suggestions_cache
        WHERE dismissed = 0 AND acted_on = 0
          AND expires_at > ?
        ORDER BY id DESC
        """,
        (_dt.datetime.now(_dt.timezone.utc).isoformat(),),
    ).fetchall()
    return [
        {
            "id": r[0], "kind": r[1], "target_note_ids": json.loads(r[2]),
            "content": r[3], "reasoning": r[4],
            "base_score": float(r[5]), "generated_at": r[6],
        }
        for r in rows
    ]


def _shown_recently(conn: sqlite3.Connection, suggestion_id: int, days: int = 7) -> bool:
    """Evento suggestion_shown nos ultimos `days` dias sem aceite/dismiss posterior."""
    cutoff = (_dt.date.today() - _dt.timedelta(days=days)).isoformat()
    row = conn.execute(
        """
        SELECT 1 FROM events
        WHERE event_type = 'suggestion_shown'
          AND note_id IS NULL
          AND json_extract(metadata_json, '$.suggestion_id') = ?
          AND date >= ?
        LIMIT 1
        """,
        (suggestion_id, cutoff),
    ).fetchone() if _column_exists(conn, "events", "metadata_json") else None
    return row is not None


def _column_exists(conn: sqlite3.Connection, table: str, col: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r[1] == col for r in rows)


def _dismissed_count(conn: sqlite3.Connection, kind: str, days: int = 30) -> int:
    cutoff = (_dt.date.today() - _dt.timedelta(days=days)).isoformat()
    row = conn.execute(
        """
        SELECT COUNT(*) FROM suggestions_cache
        WHERE kind = ? AND dismissed = 1
          AND substr(COALESCE(dismissed_at, generated_at), 1, 10) >= ?
        """,
        (kind, cutoff),
    ).fetchone()
    return int(row[0])


def rank(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Calcula score ajustado por kind weight + decays anti-repeticao."""
    suggestions = _active_suggestions(conn)
    dismissed_counts = {k: _dismissed_count(conn, k) for k in _KIND_WEIGHT}
    kind_seen: dict[str, int] = {}
    out: list[dict[str, Any]] = []
    for s in suggestions:
        kind = s["kind"]
        weight = _KIND_WEIGHT.get(kind, _DEFAULT_WEIGHT)
        score = s["base_score"] * weight
        # Decay anti-repeticao: sugestao mostrada recente
        if _shown_recently(conn, s["id"]):
            score *= 0.5
        # Dismissed count (por kind)
        dism = dismissed_counts.get(kind, 0)
        if dism > 0:
            score *= (0.1 ** min(dism, 3))  # decay forte
        # Same-kind order decay
        idx = kind_seen.get(kind, 0)
        decay_factor = _SAME_KIND_DECAY[min(idx, len(_SAME_KIND_DECAY) - 1)]
        score *= decay_factor
        kind_seen[kind] = idx + 1
        out.append({**s, "score": round(score, 4)})
    out.sort(key=lambda x: x["score"], reverse=True)
    return out


def select_top(
    conn: sqlite3.Connection, *, limit: int | None = None
) -> list[dict[str, Any]]:
    """Top-N ranked + record suggestion_shown events pra anti-repeticao."""
    cap = min(SUGGESTIONS_PER_RUN_MAX, limit or 10)
    ranked = rank(conn)
    top = ranked[:cap]
    # Registra evento suggestion_shown (sem bloquear se metadata_json inexistente)
    if top and _column_exists(conn, "events", "metadata_json"):
        now = _dt.datetime.now(_dt.timezone.utc).isoformat()
        today = now[:10]
        for s in top:
            conn.execute(
                """
                INSERT INTO events (ts, event_type, note_id, date, metadata_json)
                VALUES (?, 'suggestion_shown', NULL, ?, ?)
                """,
                (now, today, json.dumps({"suggestion_id": s["id"]})),
            )
        conn.commit()
    return top
