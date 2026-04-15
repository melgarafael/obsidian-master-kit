"""gaps.py — Gap detection (Epic 05 S03 / Wave 3).

Tres detectores combinam sinais semanticos + de grafo pra propor "pontes
faltando" no vault:

1. `bridges`             — pares de notas com alta similaridade sem link direto
2. `moc_expand`          — MOCs rasos com muitas notas-candidatas na area
3. `reference_missing`   — clusters semanticos (via KNN-graph de mutuos) sem nota
                           marcada como `type='referencia'`

Todos retornam `Candidate`s com `reasoning` humano-legivel. `run_all` orquestra
os tres, aplica hard cap `SUGGESTIONS_PER_RUN_MAX`, e opcionalmente persiste
em `suggestions_cache` via `persist(conn, candidates)`.

Design:
- Zero LLM. Templates puros de string + numeros reais do DB.
- Zero clustering library nova (nao dep de HDBSCAN/sklearn). Detector 3
  usa KNN-graph de vizinhos mutuos — barato e interpretavel.
- Complexidade tipica: O(N*K) com N=notas ativas e K=knn neighbors (<=5).
  Em vault de 5k notas, roda em alguns segundos.
"""
from __future__ import annotations

import datetime as _dt
import importlib.util
import json
import pathlib
import sqlite3
import sys
from dataclasses import dataclass

from core.config import (
    BRIDGE_MIN_COS,
    CONCEPT_CLUSTER_MIN_MUTUAL,
    CONCEPT_KNN_K,
    MOC_OUT_DEGREE_SHALLOW,
    MOC_SHALLOW_RATIO,
    SUGGESTIONS_PER_RUN_MAX,
    SUGGESTIONS_TTL_DAYS,
)

__all__ = [
    "Candidate",
    "detect_bridges",
    "detect_moc_shallow",
    "detect_reference_missing",
    "run_all",
    "persist",
]


# Import knn.py lazily por path (nao e modulo Python instalado).
_KNN_PATH = pathlib.Path(__file__).parent / "knn.py"


def _load_knn_module():
    name = "_expand_knn"
    existing = sys.modules.get(name)
    if existing is not None:
        return existing
    spec = importlib.util.spec_from_file_location(name, _KNN_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@dataclass(frozen=True)
class Candidate:
    kind: str
    target_note_ids: list[int]
    content: str
    reasoning: str
    score: float


# ---------- helpers ----------


def _active_note_rows(conn: sqlite3.Connection) -> list[tuple[int, str, str | None, str | None, int]]:
    """(id, path, title, type, out_degree) das notas ativas com embedding."""
    table = "vec_notes" if getattr(conn, "vec_loaded", False) else "notes_embedding_blob"
    cursor = conn.execute(
        f"""
        SELECT n.id, n.path, n.title, n.type, n.out_degree
        FROM notes n
        WHERE n.deleted_at IS NULL
          AND (n.status IS NULL OR n.status != 'arquivado')
          AND EXISTS (SELECT 1 FROM {table} v WHERE v.{"note_id" if table == "notes_embedding_blob" else "note_id"} = n.id)
        """
    )
    return [
        (row[0], row[1], row[2], row[3], row[4]) for row in cursor.fetchall()
    ]


def _link_set(conn: sqlite3.Connection) -> set[tuple[int, int]]:
    """Set de pares `(from, to)` de links resolvidos. Undirected (inclui inverso)."""
    pairs: set[tuple[int, int]] = set()
    for row in conn.execute(
        "SELECT from_note_id, to_note_id FROM links WHERE to_note_id IS NOT NULL"
    ):
        a, b = int(row[0]), int(row[1])
        pairs.add((a, b))
        pairs.add((b, a))
    return pairs


def _display_name(title: str | None, path: str) -> str:
    if title and title.strip():
        return title.strip()
    return pathlib.Path(path).stem


def _distance_to_cos(dist: float) -> float:
    """Converte L2-distance (unit vectors) de volta pra cosine."""
    return max(-1.0, min(1.0, 1.0 - dist / 2.0))


# ---------- detector 1: bridges ----------


def detect_bridges(
    conn: sqlite3.Connection,
    *,
    min_cos: float | None = None,
    limit: int | None = None,
) -> list[Candidate]:
    """Pares de notas proximas semanticamente sem link direto."""
    threshold = BRIDGE_MIN_COS if min_cos is None else min_cos
    cap = SUGGESTIONS_PER_RUN_MAX if limit is None else limit
    knn_mod = _load_knn_module()
    notes = _active_note_rows(conn)
    if len(notes) < 2:
        return []
    by_id = {n[0]: n for n in notes}
    links = _link_set(conn)
    seen_pairs: set[tuple[int, int]] = set()
    candidates: list[Candidate] = []

    for note_id, _path, title, _type, _out in notes:
        neighbors = knn_mod.knn(conn, note_id, k=CONCEPT_KNN_K)
        for neigh_id, dist in neighbors:
            if neigh_id == note_id or neigh_id not in by_id:
                continue
            pair = (min(note_id, neigh_id), max(note_id, neigh_id))
            if pair in seen_pairs:
                continue
            if (note_id, neigh_id) in links:
                continue
            cos = _distance_to_cos(dist)
            if cos < threshold:
                continue
            seen_pairs.add(pair)
            a_name = _display_name(by_id[pair[0]][2], by_id[pair[0]][1])
            b_name = _display_name(by_id[pair[1]][2], by_id[pair[1]][1])
            reasoning = (
                f"[[{a_name}]] e [[{b_name}]] tem similaridade {cos:.2f} "
                "mas nao ha link direto entre elas."
            )
            content = f"Ponte sugerida entre [[{a_name}]] e [[{b_name}]]."
            candidates.append(
                Candidate(
                    kind="bridge",
                    target_note_ids=[pair[0], pair[1]],
                    content=content,
                    reasoning=reasoning,
                    score=cos,
                )
            )

    candidates.sort(key=lambda c: c.score, reverse=True)
    return candidates[:cap]


# ---------- detector 2: moc_expand ----------


def _is_moc(path: str, title: str | None, type_: str | None) -> bool:
    if type_ == "moc":
        return True
    if path.endswith("_MOC.md"):
        return True
    return bool(title) and title.strip().lower().startswith("moc")


def detect_moc_shallow(
    conn: sqlite3.Connection,
    *,
    limit: int | None = None,
) -> list[Candidate]:
    """MOCs rasos: poucos out-links apesar de area ao redor ser densa."""
    cap = SUGGESTIONS_PER_RUN_MAX if limit is None else limit
    cursor = conn.execute(
        """
        SELECT id, path, title, type, area_id, out_degree
        FROM notes
        WHERE deleted_at IS NULL
          AND (status IS NULL OR status != 'arquivado')
          AND (
               type = 'moc'
            OR path LIKE '%_MOC.md'
            OR LOWER(COALESCE(title, '')) LIKE 'moc%'
          )
        """
    )
    moc_rows = cursor.fetchall()
    if not moc_rows:
        return []
    candidates: list[Candidate] = []
    for moc_id, moc_path, moc_title, _type, area_id, out_degree in moc_rows:
        if out_degree >= MOC_OUT_DEGREE_SHALLOW * MOC_SHALLOW_RATIO:
            continue
        if area_id is None:
            # MOC sem area — nao da pra contar notas da area
            continue
        count = conn.execute(
            """
            SELECT COUNT(*)
            FROM notes
            WHERE area_id = ?
              AND id != ?
              AND deleted_at IS NULL
              AND (status IS NULL OR status != 'arquivado')
            """,
            (area_id, moc_id),
        ).fetchone()[0]
        if count <= out_degree * MOC_SHALLOW_RATIO:
            continue
        name = _display_name(moc_title, moc_path)
        deficit = count - out_degree
        reasoning = (
            f"MOC [[{name}]] tem {out_degree} out-links mas a area "
            f"tem {count} notas ativas — faltam pelo menos {deficit} referencias."
        )
        content = f"Expandir MOC [[{name}]]: {deficit} notas orfas no cluster."
        # Score = deficit normalizado (cap em 1.0)
        score = min(1.0, deficit / 30.0)
        candidates.append(
            Candidate(
                kind="moc_expand",
                target_note_ids=[moc_id],
                content=content,
                reasoning=reasoning,
                score=score,
            )
        )

    candidates.sort(key=lambda c: c.score, reverse=True)
    return candidates[:cap]


# ---------- detector 3: reference_missing ----------


def detect_reference_missing(
    conn: sqlite3.Connection,
    *,
    limit: int | None = None,
) -> list[Candidate]:
    """Clusters semanticos (via mutual-KNN graph) sem nota de referencia."""
    cap = SUGGESTIONS_PER_RUN_MAX if limit is None else limit
    knn_mod = _load_knn_module()
    notes = _active_note_rows(conn)
    if len(notes) < CONCEPT_CLUSTER_MIN_MUTUAL + 1:
        return []
    by_id = {n[0]: n for n in notes}

    # Calcula knn uma vez por nota e monta adjacencia.
    adj: dict[int, set[int]] = {}
    for note_id, *_ in notes:
        top = knn_mod.knn(conn, note_id, k=CONCEPT_KNN_K)
        adj[note_id] = {nid for nid, _ in top}

    # Arestas mutuas: B em adj[A] E A em adj[B].
    mutual: dict[int, set[int]] = {nid: set() for nid in adj}
    for a in adj:
        for b in adj[a]:
            if b in adj and a in adj[b]:
                mutual[a].add(b)

    seen_clusters: set[tuple[int, ...]] = set()
    candidates: list[Candidate] = []
    for seed, neighbors in mutual.items():
        if len(neighbors) < CONCEPT_CLUSTER_MIN_MUTUAL:
            continue
        cluster_members = sorted({seed, *neighbors})
        sig = tuple(cluster_members)
        if sig in seen_clusters:
            continue
        seen_clusters.add(sig)
        # Se algum membro e type='referencia', pula.
        types = {by_id[nid][3] for nid in cluster_members if nid in by_id}
        if "referencia" in types:
            continue
        # Reasoning: cita ate 3 titulos
        titles = [
            _display_name(by_id[nid][2], by_id[nid][1])
            for nid in cluster_members
            if nid in by_id
        ][:3]
        titles_str = ", ".join(f"[[{t}]]" for t in titles)
        n = len(cluster_members)
        reasoning = (
            f"{n} notas formam cluster mutuo por similaridade semantica "
            f"({titles_str}{'...' if n > 3 else ''}) mas nenhuma e "
            "marcada como type='referencia' — pode faltar a nota de conceito."
        )
        content = f"Cluster de {n} notas sem referencia central."
        score = min(1.0, (n - CONCEPT_CLUSTER_MIN_MUTUAL) / 10.0 + 0.3)
        candidates.append(
            Candidate(
                kind="reference_missing",
                target_note_ids=cluster_members,
                content=content,
                reasoning=reasoning,
                score=score,
            )
        )

    candidates.sort(key=lambda c: c.score, reverse=True)
    return candidates[:cap]


# ---------- orquestrador + persistencia ----------


def run_all(
    conn: sqlite3.Connection,
    *,
    limit: int | None = None,
) -> list[Candidate]:
    """Roda os 3 detectores e intercala resultados respeitando hard cap."""
    cap = SUGGESTIONS_PER_RUN_MAX if limit is None else limit
    bridges = detect_bridges(conn)
    mocs = detect_moc_shallow(conn)
    refs = detect_reference_missing(conn)
    # Intercala: bridge, moc, reference, bridge, moc, reference... ate cap.
    # Garante diversidade de tipos no top mesmo se um detector gerar muito.
    out: list[Candidate] = []
    queues = [iter(bridges), iter(mocs), iter(refs)]
    active = list(range(3))
    while active and len(out) < cap:
        still: list[int] = []
        for qi in active:
            try:
                out.append(next(queues[qi]))
            except StopIteration:
                continue
            else:
                still.append(qi)
            if len(out) >= cap:
                break
        active = still
    return out[:cap]


def persist(
    conn: sqlite3.Connection,
    candidates: list[Candidate],
    *,
    ttl_days: int | None = None,
    now: _dt.datetime | None = None,
) -> int:
    """Grava candidatos em `suggestions_cache`. Retorna count inserido.

    `generated_at` e `expires_at` (now + ttl_days). Re-invocacoes nao
    dedup automatico — orquestrador superior (pulse worker) e responsavel
    por limpar expirados antes.
    """
    if not candidates:
        return 0
    ttl = SUGGESTIONS_TTL_DAYS if ttl_days is None else ttl_days
    generated = now or _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0)
    expires = generated + _dt.timedelta(days=ttl)
    gen_iso = generated.isoformat()
    exp_iso = expires.isoformat()
    inserted = 0
    for c in candidates:
        conn.execute(
            """
            INSERT INTO suggestions_cache
                (generated_at, expires_at, kind, target_note_ids,
                 content, reasoning, score, dismissed, acted_on)
            VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0)
            """,
            (
                gen_iso,
                exp_iso,
                c.kind,
                json.dumps(c.target_note_ids),
                c.content,
                c.reasoning,
                c.score,
            ),
        )
        inserted += 1
    conn.commit()
    return inserted
