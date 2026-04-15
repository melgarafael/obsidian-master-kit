"""fsrs_scheduler.py — Free Spaced Repetition Scheduler (Epic 06 S03 / Wave 3).

Pra cada nota `type IN (reference, fleeting)`, reconstrua a historia FSRS
a partir dos `events(event_type='note_updated')`. Sem grading explicito do
usuario, usamos heuristica: cada update e "Good" (relembrou); gaps longos
significam stabilidade decrescente.

Output: `suggestions_cache(kind='review')` quando a nota tem `due <= today + 2d`.
Pulse dashboard exibe essas reviews.
"""
from __future__ import annotations

import datetime as _dt
import json
import sqlite3
from typing import Any

from core.config import SUGGESTIONS_TTL_DAYS

__all__ = ["compute_due_dates", "create_review_suggestions"]


_REVIEW_WINDOW_DAYS = 2


def _iter_update_events(
    conn: sqlite3.Connection, note_id: int
) -> list[_dt.datetime]:
    rows = conn.execute(
        "SELECT ts FROM events "
        "WHERE note_id = ? AND event_type IN ('note_created', 'note_updated') "
        "ORDER BY ts ASC",
        (note_id,),
    ).fetchall()
    out = []
    for r in rows:
        ts = r[0]
        try:
            dt = _dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=_dt.timezone.utc)
            out.append(dt)
        except (ValueError, AttributeError):
            continue
    return out


def _fsrs_due_for_note(
    updates: list[_dt.datetime],
) -> tuple[_dt.datetime | None, float, float]:
    """Simula FSRS incremental. Retorna (due, stability, difficulty)."""
    if not updates:
        return None, 0.0, 0.0
    try:
        from fsrs import Scheduler, Card, Rating
    except ImportError:
        return None, 0.0, 0.0
    scheduler = Scheduler()
    card = Card()
    # Primeiro evento = "first review"; seguintes = revisoes Good
    for i, update_dt in enumerate(updates):
        rating = Rating.Good  # heuristic: any update = user remembered
        card, _log = scheduler.review_card(card, rating, review_datetime=update_dt)
    return card.due, float(card.stability), float(card.difficulty)


def compute_due_dates(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Retorna lista `{note_id, title, path, due, stability, difficulty}`
    pra notas type=(reference|fleeting) ativas.
    """
    rows = conn.execute(
        """
        SELECT id, path, title FROM notes
        WHERE deleted_at IS NULL
          AND (status IS NULL OR status != 'arquivado')
          AND type IN ('reference', 'referencia', 'fleeting')
        """
    ).fetchall()
    results: list[dict[str, Any]] = []
    for nid, path, title in rows:
        updates = _iter_update_events(conn, nid)
        due, stab, diff = _fsrs_due_for_note(updates)
        if due is None:
            continue
        results.append(
            {
                "note_id": nid,
                "path": path,
                "title": title,
                "due": due.isoformat(),
                "stability": stab,
                "difficulty": diff,
                "update_count": len(updates),
            }
        )
    return results


def create_review_suggestions(
    conn: sqlite3.Connection,
    *,
    window_days: int = _REVIEW_WINDOW_DAYS,
) -> int:
    """Grava `kind='review'` em suggestions_cache pra notas com due iminente.

    Retorna count inserido. Dedup: nao duplica se ja existe review ativa
    pra mesma nota.
    """
    dues = compute_due_dates(conn)
    if not dues:
        return 0
    now = _dt.datetime.now(_dt.timezone.utc)
    cutoff = now + _dt.timedelta(days=window_days)
    exp = now + _dt.timedelta(days=SUGGESTIONS_TTL_DAYS)
    gen_iso = now.replace(microsecond=0).isoformat()
    exp_iso = exp.replace(microsecond=0).isoformat()
    count = 0
    for d in dues:
        try:
            due_dt = _dt.datetime.fromisoformat(d["due"].replace("Z", "+00:00"))
            if due_dt.tzinfo is None:
                due_dt = due_dt.replace(tzinfo=_dt.timezone.utc)
        except ValueError:
            continue
        if due_dt > cutoff:
            continue
        # Dedup: ja tem review ativa pra essa nota?
        existing = conn.execute(
            "SELECT 1 FROM suggestions_cache "
            "WHERE kind='review' AND dismissed=0 AND acted_on=0 "
            "AND target_note_ids = ? LIMIT 1",
            (json.dumps([d["note_id"]]),),
        ).fetchone()
        if existing:
            continue
        days_overdue = max(0, (now - due_dt).days)
        title = d["title"] or d["path"]
        content = f"Revisar [[{title}]]"
        reasoning = (
            f"FSRS indica devido ha {days_overdue} dia(s) "
            f"(stability {d['stability']:.1f}d, {d['update_count']} reviews anteriores)."
        )
        # Score: quanto mais overdue, mais alto (cap 1.0)
        score = min(1.0, 0.5 + days_overdue / 30.0)
        conn.execute(
            """
            INSERT INTO suggestions_cache
              (generated_at, expires_at, kind, target_note_ids, content, reasoning,
               score, dismissed, acted_on)
            VALUES (?, ?, 'review', ?, ?, ?, ?, 0, 0)
            """,
            (
                gen_iso,
                exp_iso,
                json.dumps([d["note_id"]]),
                content,
                reasoning,
                score,
            ),
        )
        count += 1
    conn.commit()
    return count
