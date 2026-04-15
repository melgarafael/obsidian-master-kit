"""Graph metrics: in/out-degree, PageRank, MOC candidates.

Le links + notes do SQLite, calcula via networkx, persiste em colunas
notes.in_degree/out_degree/pagerank. Betweenness e opt-in e nao persiste
(schema nao tem coluna).
"""

from __future__ import annotations

import logging
import time
from typing import Any

import networkx as nx

__all__ = ["update_graph_metrics", "find_mocs"]

_LOG = logging.getLogger(__name__)


def update_graph_metrics(conn, with_betweenness: bool = False) -> dict[str, Any]:
    """Atualiza in_degree, out_degree, pagerank em notes.

    Parametros:
      conn: sqlite3.Connection
      with_betweenness: se True, calcula betweenness_centrality (O(n^3),
        caro) e inclui no dict retornado. NAO persiste (schema sem coluna).

    Links quebrados (to_note_id IS NULL) sao ignorados no grafo.
    Notas soft-deleted (deleted_at IS NOT NULL) sao excluidas.

    Retorna: dict com 'nodes', 'edges', 'duration_s', 'pagerank_sum',
             opcionalmente 'betweenness': dict[note_id, float].
    """
    t0 = time.perf_counter()

    # 1. Load nodes (active notes)
    node_rows = conn.execute(
        "SELECT id FROM notes WHERE deleted_at IS NULL"
    ).fetchall()
    node_ids = [r[0] for r in node_rows]

    # 2. Load edges (resolved links only)
    edge_rows = conn.execute(
        "SELECT from_note_id, to_note_id FROM links WHERE to_note_id IS NOT NULL"
    ).fetchall()

    # 3. Build DiGraph
    G = nx.DiGraph()
    G.add_nodes_from(node_ids)
    # Only add edges whose endpoints are both active nodes
    active = set(node_ids)
    edges = [(a, b) for (a, b) in edge_rows if a in active and b in active]
    G.add_edges_from(edges)

    # 4. Compute metrics
    in_deg = dict(G.in_degree())
    out_deg = dict(G.out_degree())
    if len(node_ids) > 0:
        pagerank = nx.pagerank(G, alpha=0.85)
    else:
        pagerank = {}

    # 5. Persist (single transaction)
    with conn:  # implicit BEGIN/COMMIT
        for nid in node_ids:
            conn.execute(
                "UPDATE notes SET in_degree=?, out_degree=?, pagerank=? WHERE id=?",
                (in_deg.get(nid, 0), out_deg.get(nid, 0), pagerank.get(nid, 0.0), nid),
            )

    result: dict[str, Any] = {
        "nodes": len(node_ids),
        "edges": len(edges),
        "duration_s": round(time.perf_counter() - t0, 3),
        "pagerank_sum": round(sum(pagerank.values()), 6),
    }

    if with_betweenness:
        bw = nx.betweenness_centrality(G) if len(node_ids) > 1 else {}
        result["betweenness"] = bw
        _LOG.info("betweenness calculada (not persisted): %d nodes", len(bw))

    return result


def find_mocs(conn, min_out_degree: int = 10, min_in_degree: int = 5) -> list[int]:
    """Heuristica: notas com muitos links de saida + entrada.

    Ordena por pagerank desc. Nao implica que ja sao _MOC.md; organizer
    (Epic 04) propoe creation nos clusters densos sem MOC existente.
    """
    rows = conn.execute(
        """
        SELECT id FROM notes
        WHERE deleted_at IS NULL
          AND out_degree > ?
          AND in_degree > ?
        ORDER BY pagerank DESC
        """,
        (min_out_degree, min_in_degree),
    ).fetchall()
    return [r[0] for r in rows]
