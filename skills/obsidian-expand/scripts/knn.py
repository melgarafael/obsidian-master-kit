"""knn.py — KNN engine para obsidian-expand (Epic 05 S02 / Wave 2).

Top-K vizinhos semanticos de uma nota via sqlite-vec (path rapido) com
fallback automatico pra scan em numpy quando a extension nao esta
carregada.

Contratos
---------
- Embeddings no DB sao L2-normalized (contrato Epic 01). Portanto
  `dot(a, b) == cos(a, b)` e a distancia L2 reportada pelo vec0 esta
  em `[0, 2]` com menor = mais similar. Rankings por L2-ASC e por
  coseno-DESC sao equivalentes.
- Retornamos distancia (nao similaridade) porque vec0 reporta distancia
  e queremos consistencia entre os dois paths.
- Filtros aplicados (sempre, ambos os paths):
    * exclui a propria `note_id`
    * exclui `notes.status == 'arquivado'`
    * exclui `notes.deleted_at IS NOT NULL`

Se a nota-query nao tem embedding no DB, retorna `[]` (nao levanta —
gap semantico em nota nunca embedada e um sinal legitimo de "nao pode
recomendar").
"""
from __future__ import annotations

import sqlite3
from typing import Iterable

import numpy as np

from core.embeddings import CANONICAL_DIM, unpack

__all__ = ["knn"]


# Margem pra compensar filtragem pos-hoc no path vec0 (notas arquivadas /
# deletadas que o vec0 ainda ve como candidatas). Em vault saudavel a
# maioria e ativa, 3x + 50 cobre 99% dos casos.
_VEC0_OVERFETCH_MULT = 3
_VEC0_OVERFETCH_BASE = 50


def knn(
    conn: sqlite3.Connection,
    note_id: int,
    k: int = 20,
) -> list[tuple[int, float]]:
    """Top-K vizinhos semanticos de `note_id`.

    Retorna lista `(neighbor_id, distance)` ordenada por `distance` asc.
    Lista pode ter < k itens se:
    - vault pequeno (poucos vizinhos disponiveis),
    - nota-query nao tem embedding (retorna `[]`),
    - filtros removem muitos candidatos e fetch inicial insuficiente (raro).
    """
    if k <= 0:
        return []
    query_vec = _get_note_vec(conn, note_id)
    if query_vec is None:
        return []
    active_ids = _active_note_ids(conn, exclude=note_id)
    if not active_ids:
        return []
    if getattr(conn, "vec_loaded", False):
        candidates = _knn_vec0(conn, query_vec, k)
    else:
        candidates = _knn_blob_scan(conn, query_vec)
    active = set(active_ids)
    filtered = [(nid, dist) for nid, dist in candidates if nid in active]
    return filtered[:k]


# ---------- helpers internos ----------


def _get_note_vec(conn: sqlite3.Connection, note_id: int) -> np.ndarray | None:
    """Recupera embedding da nota como ndarray (dim,) float32.

    Tenta vec_notes primeiro (quando vec_loaded); cai pra
    notes_embedding_blob caso contrario. Retorna None se nao ha registro.
    """
    if getattr(conn, "vec_loaded", False):
        row = conn.execute(
            "SELECT embedding FROM vec_notes WHERE note_id = ?",
            (note_id,),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT vec FROM notes_embedding_blob WHERE note_id = ?",
            (note_id,),
        ).fetchone()
    if row is None or row[0] is None:
        return None
    return unpack(row[0])


def _active_note_ids(conn: sqlite3.Connection, exclude: int) -> list[int]:
    """IDs das notas ativas (nao arquivadas, nao deletadas), exceto `exclude`."""
    cursor = conn.execute(
        "SELECT id FROM notes "
        "WHERE id != ? "
        "  AND deleted_at IS NULL "
        "  AND (status IS NULL OR status != 'arquivado')",
        (exclude,),
    )
    return [row[0] for row in cursor.fetchall()]


def _knn_vec0(
    conn: sqlite3.Connection,
    query_vec: np.ndarray,
    k: int,
) -> list[tuple[int, float]]:
    """Path rapido via `vec_notes MATCH`. Overfetch pra permitir filtragem."""
    limit = k * _VEC0_OVERFETCH_MULT + _VEC0_OVERFETCH_BASE
    blob = np.asarray(query_vec, dtype=np.float32).tobytes()
    cursor = conn.execute(
        "SELECT note_id, distance "
        "FROM vec_notes "
        "WHERE embedding MATCH ? "
        "ORDER BY distance "
        "LIMIT ?",
        (blob, limit),
    )
    return [(int(row[0]), float(row[1])) for row in cursor.fetchall()]


def _knn_blob_scan(
    conn: sqlite3.Connection,
    query_vec: np.ndarray,
) -> list[tuple[int, float]]:
    """Path fallback: scan completo em numpy, dot product em unit-vectors.

    Distancia retornada convertida de cos pra L2-equivalente:
    `||a - b||^2 = 2 - 2*cos(a, b)` quando ambos sao unit vectors.
    Assim o ranking casa com o path vec0 (menor = mais similar).
    """
    rows = conn.execute(
        "SELECT note_id, vec FROM notes_embedding_blob"
    ).fetchall()
    if not rows:
        return []
    ids: list[int] = []
    vecs: list[np.ndarray] = []
    for note_id, blob in rows:
        if blob is None:
            continue
        ids.append(int(note_id))
        vecs.append(unpack(blob))
    if not vecs:
        return []
    matrix = np.stack(vecs)
    query = np.asarray(query_vec, dtype=np.float32)
    # dot product entre unit vectors == cos(a, b)
    cosines = matrix @ query
    # L2-equivalent distance (ranking consistente com vec0 path)
    distances = 2.0 - 2.0 * cosines
    order = np.argsort(distances)
    return [(ids[i], float(distances[i])) for i in order]
