"""propose.py — agrega tudo em migration_plan (Epic 04 S06 / Wave 6).

Le os outputs das waves anteriores (suggestions_cache + duplicate_candidates
pendentes) e gera linhas em `migration_plan` com `status='pending'` e
`batch_id` que agrupa entries do mesmo run.

NAO executa moves nem merges — `obsidian-migrate apply --batch N` faz a
execucao real. organizer e **proposta**, migrate e **execucao**.

Merge proposal de duplicatas: entries com reason='merge_duplicate'
apontam `current_location=keep_target`, `proposed_location=keep_source`
(mantendo o source como autoritativo). Migrate apply vai renomear
o alternate pra `.merged-<ts>.md`, concatenar conteudo, e atualizar
wikilinks em outras notas.
"""
from __future__ import annotations

import datetime as _dt
import json
import sqlite3
from typing import Any

__all__ = ["propose", "summary"]


def _next_batch_id(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT COALESCE(MAX(batch_id), 0) + 1 FROM migration_plan"
    ).fetchone()
    return int(row[0])


def _path_for_note(conn: sqlite3.Connection, note_id: int) -> str | None:
    row = conn.execute("SELECT path FROM notes WHERE id = ?", (note_id,)).fetchone()
    return row[0] if row else None


def _gather_suggestions(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Puxa suggestions ativas (nao dismiss, nao acted_on) das ondas 3/4/5."""
    rows = conn.execute(
        """
        SELECT id, kind, target_note_ids, content, reasoning, score
        FROM suggestions_cache
        WHERE dismissed = 0 AND acted_on = 0
          AND kind IN ('moc_missing', 'area_mismatch', 'bridge')
        ORDER BY score DESC NULLS LAST, id ASC
        """
    ).fetchall()
    out = []
    for r in rows:
        try:
            ids = json.loads(r[2])
        except (json.JSONDecodeError, TypeError):
            ids = []
        out.append(
            {
                "suggestion_id": r[0],
                "kind": r[1],
                "note_ids": ids,
                "content": r[3],
                "reasoning": r[4],
                "score": r[5],
            }
        )
    return out


def _gather_duplicates(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Duplicate_candidates com verdict='merge' (aprovado pra fundir)."""
    rows = conn.execute(
        """
        SELECT dc.id, dc.note_a_id, dc.note_b_id, dc.cosine_similarity,
               na.path, nb.path
        FROM duplicate_candidates dc
        JOIN notes na ON na.id = dc.note_a_id
        JOIN notes nb ON nb.id = dc.note_b_id
        WHERE dc.verdict = 'merge'
        """
    ).fetchall()
    return [
        {
            "duplicate_id": r[0],
            "note_a_id": r[1],
            "note_b_id": r[2],
            "cos": float(r[3]),
            "a_path": r[4],
            "b_path": r[5],
        }
        for r in rows
    ]


def propose(
    conn: sqlite3.Connection,
    *,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Gera proposta consolidada. Com dry_run=True, nao escreve migration_plan.

    Retorna dict com: batch_id (None se dry_run), entries[], summary{}.
    """
    suggestions = _gather_suggestions(conn)
    duplicates = _gather_duplicates(conn)
    entries: list[dict[str, Any]] = []

    for s in suggestions:
        for nid in s["note_ids"][:3]:
            path = _path_for_note(conn, nid)
            if path is None:
                continue
            entries.append(
                {
                    "note_id": nid,
                    "current_location": path,
                    "proposed_location": path,  # organizer nao move; marca pra revisao
                    "reason": f"{s['kind']}: {s['reasoning'][:120]}",
                    "confidence": s["score"] or 0.3,
                    "kind": s["kind"],
                }
            )

    for d in duplicates:
        entries.append(
            {
                "note_id": d["note_b_id"],
                "current_location": d["b_path"],
                "proposed_location": d["a_path"],  # keep A, fund B em A
                "reason": (
                    f"merge_duplicate: cos={d['cos']:.2f}. "
                    f"Funde [[{d['b_path']}]] em [[{d['a_path']}]] "
                    "(migrate apply concatena + redireciona wikilinks)"
                ),
                "confidence": d["cos"],
                "kind": "merge_duplicate",
            }
        )

    batch_id: int | None = None
    if not dry_run and entries:
        batch_id = _next_batch_id(conn)
        now = _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()
        for e in entries:
            conn.execute(
                """
                INSERT INTO migration_plan
                  (note_path, current_location, proposed_location,
                   proposed_area_id, cluster_id, reason, confidence,
                   batch_id, status)
                VALUES (?, ?, ?, NULL, NULL, ?, ?, ?, 'pending')
                """,
                (
                    e["current_location"],
                    e["current_location"],
                    e["proposed_location"],
                    e["reason"],
                    e["confidence"],
                    batch_id,
                ),
            )
        conn.commit()

    by_kind: dict[str, int] = {}
    for e in entries:
        by_kind[e["kind"]] = by_kind.get(e["kind"], 0) + 1

    return {
        "dry_run": dry_run,
        "batch_id": batch_id,
        "entry_count": len(entries),
        "by_kind": by_kind,
        "entries_preview": entries[:10],
    }


def summary(conn: sqlite3.Connection) -> dict[str, Any]:
    """Relatorio consolidado: contagens dos 4 detectors + clusters recentes."""
    counts = {
        "notes_active": conn.execute(
            "SELECT COUNT(*) FROM notes WHERE deleted_at IS NULL "
            "AND (status IS NULL OR status != 'arquivado')"
        ).fetchone()[0],
        "clusters_latest_run": 0,
        "latest_run_id": None,
        "suggestions_pending": {
            "moc_missing": 0,
            "area_mismatch": 0,
            "bridge": 0,
        },
        "duplicates_pending": 0,
        "migration_plan_batches_pending": 0,
    }

    latest_run_row = conn.execute(
        "SELECT run_id, COUNT(*) FROM clusters "
        "WHERE run_id = (SELECT run_id FROM clusters ORDER BY created_at DESC LIMIT 1) "
        "GROUP BY run_id"
    ).fetchone()
    if latest_run_row:
        counts["latest_run_id"] = latest_run_row[0]
        counts["clusters_latest_run"] = int(latest_run_row[1])

    rows = conn.execute(
        """
        SELECT kind, COUNT(*) FROM suggestions_cache
        WHERE dismissed = 0 AND acted_on = 0
        GROUP BY kind
        """
    ).fetchall()
    for kind, n in rows:
        if kind in counts["suggestions_pending"]:
            counts["suggestions_pending"][kind] = int(n)

    counts["duplicates_pending"] = int(
        conn.execute(
            "SELECT COUNT(*) FROM duplicate_candidates WHERE verdict IS NULL"
        ).fetchone()[0]
    )
    counts["migration_plan_batches_pending"] = int(
        conn.execute(
            "SELECT COUNT(DISTINCT batch_id) FROM migration_plan WHERE status='pending'"
        ).fetchone()[0]
    )

    return counts
