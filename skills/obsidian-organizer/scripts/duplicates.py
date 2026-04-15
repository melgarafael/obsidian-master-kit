"""duplicates.py — duplicate detection (Epic 04 S03 / Wave 3).

Detecta pares (A, B) com `cos(A, B) >= DUPLICATE_MIN_COS` que sao
candidatos a duplicata conceitual (ex: "Cabala" vs "Qabalah").
Usa KNN top-K via `sqlite-vec MATCH` (path rapido) ou fallback
numpy scan.

Filtros heuristicos pra reduzir falsos positivos:
- Exclui pares com mesmo titulo + sufixo numerico (ex: `nota-01`
  vs `nota-02` — sao continuacao, nao duplicata).
- Exclui pares ja julgados (verdict NOT NULL em duplicate_candidates).
"""
from __future__ import annotations

import datetime as _dt
import importlib.util
import pathlib
import re
import sqlite3
import sys

import numpy as np

from core.config import DUPLICATE_MIN_COS, DUPLICATE_SCAN_K
from core.embeddings import unpack

__all__ = ["detect_duplicates", "save_candidates", "list_pending"]


_KNN_PATH = pathlib.Path(__file__).parent / "knn_helper.py"

# Regex: stem base + sufixo numerico (ex: "nota", "01"). Match na base.
_NUMERIC_SUFFIX_RE = re.compile(r"^(.+?)[-_ ]?(\d+)$")


def _get_vec(conn: sqlite3.Connection, note_id: int):
    if getattr(conn, "vec_loaded", False):
        row = conn.execute(
            "SELECT embedding FROM vec_notes WHERE note_id=?", (note_id,)
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT vec FROM notes_embedding_blob WHERE note_id=?", (note_id,)
        ).fetchone()
    if row is None or row[0] is None:
        return None
    return unpack(row[0])


def _distance_to_cos(dist: float) -> float:
    return max(-1.0, min(1.0, 1.0 - dist / 2.0))


def _active_note_ids(conn: sqlite3.Connection) -> list[int]:
    rows = conn.execute(
        "SELECT id FROM notes "
        "WHERE deleted_at IS NULL "
        "  AND (status IS NULL OR status != 'arquivado')"
    ).fetchall()
    return [r[0] for r in rows]


def _knn_top(
    conn: sqlite3.Connection,
    note_id: int,
    vec: np.ndarray,
    k: int,
) -> list[tuple[int, float]]:
    """Retorna top-K vizinhos de note_id, excluindo ele proprio."""
    if getattr(conn, "vec_loaded", False):
        blob = np.asarray(vec, dtype=np.float32).tobytes()
        rows = conn.execute(
            "SELECT note_id, distance FROM vec_notes "
            "WHERE embedding MATCH ? ORDER BY distance LIMIT ?",
            (blob, k + 1),
        ).fetchall()
        return [(int(r[0]), float(r[1])) for r in rows if int(r[0]) != note_id]
    # fallback scan
    rows = conn.execute("SELECT note_id, vec FROM notes_embedding_blob").fetchall()
    results = []
    for nid, blob in rows:
        if nid == note_id or blob is None:
            continue
        other = unpack(blob)
        cos = float(vec @ other)
        dist = 2.0 - 2.0 * cos
        results.append((int(nid), dist))
    results.sort(key=lambda x: x[1])
    return results[:k]


def _is_numeric_suffix_pair(a_title: str | None, b_title: str | None) -> bool:
    """True se os dois titulos tem mesma base + sufixo numerico diferente."""
    if not a_title or not b_title:
        return False
    ma = _NUMERIC_SUFFIX_RE.match(a_title.strip())
    mb = _NUMERIC_SUFFIX_RE.match(b_title.strip())
    if not ma or not mb:
        return False
    return ma.group(1).lower() == mb.group(1).lower()


def _already_judged_pairs(conn: sqlite3.Connection) -> set[tuple[int, int]]:
    """Pares com verdict NOT NULL — nao reaparecer."""
    rows = conn.execute(
        "SELECT note_a_id, note_b_id FROM duplicate_candidates "
        "WHERE verdict IS NOT NULL"
    ).fetchall()
    out: set[tuple[int, int]] = set()
    for a, b in rows:
        out.add((min(a, b), max(a, b)))
    return out


def detect_duplicates(
    conn: sqlite3.Connection,
    *,
    min_cos: float | None = None,
    k: int | None = None,
) -> list[dict]:
    """Retorna lista de pares `{note_a_id, note_b_id, cos, a_title, b_title}`
    ordenada por cos DESC.
    """
    threshold = DUPLICATE_MIN_COS if min_cos is None else min_cos
    scan_k = DUPLICATE_SCAN_K if k is None else k
    active = _active_note_ids(conn)
    titles = dict(
        conn.execute(
            "SELECT id, title FROM notes WHERE deleted_at IS NULL"
        ).fetchall()
    )
    judged = _already_judged_pairs(conn)
    seen: set[tuple[int, int]] = set()
    results: list[dict] = []
    for note_id in active:
        vec = _get_vec(conn, note_id)
        if vec is None:
            continue
        for neigh_id, dist in _knn_top(conn, note_id, vec, scan_k):
            pair = (min(note_id, neigh_id), max(note_id, neigh_id))
            if pair in seen or pair in judged:
                continue
            cos = _distance_to_cos(dist)
            if cos < threshold:
                continue
            a_title = titles.get(pair[0])
            b_title = titles.get(pair[1])
            if _is_numeric_suffix_pair(a_title, b_title):
                continue
            seen.add(pair)
            results.append(
                {
                    "note_a_id": pair[0],
                    "note_b_id": pair[1],
                    "cos": round(cos, 4),
                    "a_title": a_title,
                    "b_title": b_title,
                }
            )
    results.sort(key=lambda d: d["cos"], reverse=True)
    return results


def save_candidates(conn: sqlite3.Connection, pairs: list[dict]) -> int:
    """Insere pares em duplicate_candidates. Retorna count inserido (skipa
    ja-existentes com mesmo par ordenado)."""
    if not pairs:
        return 0
    now = _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()
    # Pre-fetch existing pending/judged pairs pra dedup
    existing = set()
    for a, b in conn.execute(
        "SELECT note_a_id, note_b_id FROM duplicate_candidates"
    ).fetchall():
        existing.add((min(a, b), max(a, b)))
    count = 0
    for p in pairs:
        pair = (min(p["note_a_id"], p["note_b_id"]), max(p["note_a_id"], p["note_b_id"]))
        if pair in existing:
            continue
        conn.execute(
            "INSERT INTO duplicate_candidates "
            "(note_a_id, note_b_id, cosine_similarity, detected_at, verdict) "
            "VALUES (?, ?, ?, ?, NULL)",
            (pair[0], pair[1], p["cos"], now),
        )
        existing.add(pair)
        count += 1
    conn.commit()
    return count


def list_pending(conn: sqlite3.Connection) -> list[dict]:
    """Lista candidatos em duplicate_candidates que ainda nao foram julgados."""
    rows = conn.execute(
        """
        SELECT dc.id, dc.note_a_id, dc.note_b_id, dc.cosine_similarity,
               na.title, nb.title, dc.detected_at
        FROM duplicate_candidates dc
        JOIN notes na ON na.id = dc.note_a_id
        JOIN notes nb ON nb.id = dc.note_b_id
        WHERE dc.verdict IS NULL
        ORDER BY dc.cosine_similarity DESC
        """
    ).fetchall()
    return [
        {
            "id": r[0],
            "note_a_id": r[1],
            "note_b_id": r[2],
            "cos": round(float(r[3]), 4),
            "a_title": r[4],
            "b_title": r[5],
            "detected_at": r[6],
        }
        for r in rows
    ]
