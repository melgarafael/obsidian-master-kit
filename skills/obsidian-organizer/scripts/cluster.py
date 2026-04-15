"""cluster.py — HDBSCAN runner + TF-IDF labeling (Epic 04 S02 / Wave 2).

Parametros alinhados com `obsidian-migrate` (Epic 02) pra consistencia:
- min_cluster_size = max(5, n_notas // 200)
- min_samples = 3
- metric = 'euclidean' (equivalente a cosine em L2-normalized vectors)
- run_id = 'hdbscan-YYYYMMDD-HHMMSS'

Codigo duplicado conscientemente: migrar pra `core/clustering.py`
compartilhado e refactor de ambos os consumidores e trabalho pra outra
PR (ver Epic 06 pulse que tambem clustera). Manter localmente aqui
evita quebrar Epic 02 WIP em main.
"""
from __future__ import annotations

import datetime as _dt
import sqlite3
from typing import Any

import numpy as np

__all__ = [
    "load_notes_with_embeddings",
    "run_hdbscan",
    "summarize_clusters",
    "persist_clusters",
    "run",
]


def load_notes_with_embeddings(
    conn: sqlite3.Connection,
) -> tuple[list[dict[str, Any]], np.ndarray]:
    """(notes, embeddings matrix) das notas ativas com vetor persistido."""
    notes: list[dict[str, Any]] = []
    embs: list[np.ndarray] = []
    if getattr(conn, "vec_loaded", False):
        rows = conn.execute(
            """
            SELECT n.id, n.path, n.title, n.area_id, vn.embedding
            FROM notes n
            JOIN vec_notes vn ON vn.note_id = n.id
            WHERE n.deleted_at IS NULL
              AND (n.status IS NULL OR n.status != 'arquivado')
            """
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT n.id, n.path, n.title, n.area_id, neb.vec
            FROM notes n
            JOIN notes_embedding_blob neb ON neb.note_id = n.id
            WHERE n.deleted_at IS NULL
              AND (n.status IS NULL OR n.status != 'arquivado')
            """
        ).fetchall()
    for nid, path, title, area_id, blob in rows:
        notes.append({"id": nid, "path": path, "title": title, "area_id": area_id})
        embs.append(np.frombuffer(blob, dtype=np.float32))
    if not embs:
        return [], np.zeros((0, 0), dtype=np.float32)
    return notes, np.vstack(embs)


def run_hdbscan(
    embeddings: np.ndarray,
    *,
    min_cluster_size: int,
    min_samples: int = 3,
) -> np.ndarray:
    from sklearn.cluster import HDBSCAN

    model = HDBSCAN(
        min_cluster_size=min_cluster_size,
        min_samples=min_samples,
        metric="euclidean",
        copy=True,
    )
    return model.fit_predict(embeddings)


def summarize_clusters(
    notes: list[dict[str, Any]],
    embeddings: np.ndarray,
    labels: np.ndarray,
    *,
    top_k_tokens: int = 8,
    top_k_central: int = 3,
) -> list[dict[str, Any]]:
    """Pra cada cluster (!=-1), top tokens TF-IDF + notas centrais + label auto."""
    from sklearn.feature_extraction.text import TfidfVectorizer

    summaries: list[dict[str, Any]] = []
    unique = sorted({int(l) for l in labels if l != -1})
    if not unique:
        return summaries

    titles = [n.get("title") or "" for n in notes]
    stopwords = _stopwords()
    tfidf_mat = None
    feature_names: list[str] = []
    try:
        vec = TfidfVectorizer(
            max_features=2000,
            ngram_range=(1, 2),
            lowercase=True,
            stop_words=list(stopwords),
            token_pattern=r"(?u)\b[a-zA-ZÀ-ÿ][a-zA-ZÀ-ÿ\-']{2,}\b",
        )
        tfidf_mat = vec.fit_transform(titles)
        feature_names = list(vec.get_feature_names_out())
    except ValueError:
        tfidf_mat = None

    for cl in unique:
        idx = np.where(labels == cl)[0]
        cluster_embs = embeddings[idx]
        cluster_notes = [notes[i] for i in idx]
        centroid = cluster_embs.mean(axis=0)
        centroid = centroid / (np.linalg.norm(centroid) + 1e-9)
        dists = np.linalg.norm(cluster_embs - centroid, axis=1)
        order = np.argsort(dists)
        central = [cluster_notes[j] for j in order[:top_k_central]]
        central_dists = [float(dists[j]) for j in order[:top_k_central]]
        top_tokens: list[str] = []
        if tfidf_mat is not None and feature_names:
            cluster_tfidf = tfidf_mat[idx].mean(axis=0)
            arr = np.asarray(cluster_tfidf).flatten()
            top_tokens = [
                feature_names[k] for k in arr.argsort()[::-1][:top_k_tokens] if arr[k] > 0
            ]
        label_parts = []
        if top_tokens:
            label_parts.append(" / ".join(top_tokens[:3]))
        if central and central[0].get("title"):
            label_parts.append(f"(ex: {str(central[0]['title'])[:40]})")
        label = " ".join(label_parts) or f"cluster-{cl}"
        # Area_id dominante do cluster (se a maioria tem a mesma area)
        area_ids = [n.get("area_id") for n in cluster_notes if n.get("area_id")]
        from collections import Counter
        dominant_area = None
        if area_ids:
            most_common, freq = Counter(area_ids).most_common(1)[0]
            if freq / len(cluster_notes) > 0.5:
                dominant_area = most_common
        summaries.append(
            {
                "cluster_label_id": int(cl),
                "label": label,
                "label_source": "auto_tfidf",
                "note_count": len(idx),
                "note_ids": [int(n["id"]) for n in cluster_notes],
                "top_tokens": top_tokens,
                "central_note_ids": [int(n["id"]) for n in central],
                "central_distances": central_dists,
                "dominant_area_id": dominant_area,
            }
        )
    return summaries


def persist_clusters(
    conn: sqlite3.Connection,
    summaries: list[dict[str, Any]],
    *,
    min_cluster_size: int,
    algorithm: str = "hdbscan",
) -> str:
    """Grava clusters + cluster_notes. Retorna run_id novo (timestamp-based)."""
    run_id = _dt.datetime.now().strftime(f"{algorithm}-%Y%m%d-%H%M%S")
    now = _dt.datetime.now().astimezone().isoformat(timespec="seconds")
    with conn:
        for cs in summaries:
            cur = conn.execute(
                """
                INSERT INTO clusters
                  (run_id, label, label_source, algorithm, similarity_threshold,
                   note_count, proposed_area_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    cs["label"],
                    cs["label_source"],
                    algorithm,
                    float(min_cluster_size),
                    cs["note_count"],
                    cs.get("dominant_area_id"),
                    now,
                ),
            )
            cluster_id = cur.lastrowid
            central_map = dict(zip(cs["central_note_ids"], cs["central_distances"]))
            for nid in cs["note_ids"]:
                conn.execute(
                    "INSERT INTO cluster_notes (cluster_id, note_id, distance_to_centroid) "
                    "VALUES (?, ?, ?)",
                    (cluster_id, nid, central_map.get(nid)),
                )
    return run_id


def run(conn: sqlite3.Connection) -> dict[str, Any]:
    """Orchestrator: load -> hdbscan -> summarize -> persist. Retorna dict."""
    notes, embeddings = load_notes_with_embeddings(conn)
    n = len(notes)
    if n < 10:
        return {
            "error": f"apenas {n} notas com embedding (minimo 10 pra HDBSCAN)",
            "note_count": n,
        }
    min_cluster_size = max(5, n // 200)
    labels = run_hdbscan(embeddings, min_cluster_size=min_cluster_size, min_samples=3)
    summaries = summarize_clusters(notes, embeddings, labels)
    run_id = persist_clusters(conn, summaries, min_cluster_size=min_cluster_size)
    n_noise = int(np.sum(labels == -1))
    return {
        "run_id": run_id,
        "note_count": n,
        "cluster_count": len(summaries),
        "noise_count": n_noise,
        "min_cluster_size": min_cluster_size,
        "clusters": [
            {
                "label_id": cs["cluster_label_id"],
                "label": cs["label"],
                "note_count": cs["note_count"],
                "dominant_area_id": cs.get("dominant_area_id"),
            }
            for cs in summaries
        ],
    }


# ---------- stopwords (pt-br + en minimo) ----------


def _stopwords() -> set[str]:
    return {
        # pt-br
        "de", "da", "do", "das", "dos", "e", "o", "a", "os", "as", "um", "uma",
        "em", "na", "no", "nas", "nos", "para", "por", "com", "sem", "sob",
        "entre", "ate", "se", "ou", "mas", "nao", "sim", "que", "como", "quando",
        "onde", "porque", "qual", "quais", "sua", "seu", "suas", "seus", "eu",
        "voce", "ele", "ela", "nos", "vos", "eles", "elas", "este", "esta",
        "estes", "estas", "esse", "essa", "esses", "essas", "aquele", "aquela",
        "aqueles", "aquelas", "isto", "isso", "aquilo",
        # en
        "the", "a", "an", "of", "and", "or", "but", "if", "then", "else",
        "in", "on", "at", "to", "for", "with", "by", "from", "about", "as",
        "is", "are", "was", "were", "be", "been", "being", "have", "has",
        "had", "do", "does", "did", "will", "would", "could", "should", "may",
        "might", "must", "can", "this", "that", "these", "those", "i", "you",
        "he", "she", "we", "they", "it", "my", "your", "our", "their",
    }
