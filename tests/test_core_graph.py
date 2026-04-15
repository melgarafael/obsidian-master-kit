import sqlite3
import pathlib
import pytest
from core.db import connect
from core.graph import update_graph_metrics, find_mocs


def _make_note(conn, nid, path, title, deleted=False):
    conn.execute(
        """INSERT INTO notes(id, path, title, mtime, body_hash,
             frontmatter_json, indexed_at, deleted_at)
           VALUES (?, ?, ?, ?, '', '{}', '', ?)""",
        (nid, path, title, 0.0, 'now' if deleted else None),
    )


def _make_link(conn, from_id, to_id, to_target="x"):
    conn.execute(
        "INSERT INTO links(from_note_id, to_note_id, to_target) VALUES (?, ?, ?)",
        (from_id, to_id, to_target),
    )


def test_update_graph_metrics_basico(tmp_path):
    conn = connect(tmp_path)
    _make_note(conn, 1, "a.md", "A")
    _make_note(conn, 2, "b.md", "B")
    _make_note(conn, 3, "c.md", "C")
    _make_link(conn, 1, 2)
    _make_link(conn, 1, 3)
    conn.commit()
    res = update_graph_metrics(conn)
    assert res["nodes"] == 3
    assert res["edges"] == 2
    # check UPDATEs landed
    row = conn.execute("SELECT in_degree, out_degree FROM notes WHERE id=1").fetchone()
    assert row == (0, 2)
    row = conn.execute("SELECT in_degree, out_degree FROM notes WHERE id=2").fetchone()
    assert row == (1, 0)


def test_update_graph_metrics_pagerank_sum_um(tmp_path):
    conn = connect(tmp_path)
    for i in range(1, 6):
        _make_note(conn, i, f"n{i}.md", f"N{i}")
    _make_link(conn, 1, 2); _make_link(conn, 2, 3); _make_link(conn, 3, 4)
    _make_link(conn, 4, 5); _make_link(conn, 5, 1)
    conn.commit()
    res = update_graph_metrics(conn)
    assert abs(res["pagerank_sum"] - 1.0) < 0.001


def test_update_graph_metrics_links_quebrados_nao_contam(tmp_path):
    conn = connect(tmp_path)
    _make_note(conn, 1, "a.md", "A")
    _make_note(conn, 2, "b.md", "B")
    # broken link: to_note_id NULL
    conn.execute(
        "INSERT INTO links(from_note_id, to_note_id, to_target) VALUES (?, NULL, 'ghost')",
        (1,),
    )
    # real link
    _make_link(conn, 1, 2)
    conn.commit()
    update_graph_metrics(conn)
    row = conn.execute("SELECT in_degree, out_degree FROM notes WHERE id=1").fetchone()
    # out_degree = 1 (only resolved link counts via our WHERE IS NOT NULL query)
    assert row[1] == 1


def test_update_graph_metrics_soft_deleted_excluido(tmp_path):
    conn = connect(tmp_path)
    _make_note(conn, 1, "a.md", "A")
    _make_note(conn, 2, "b.md", "B", deleted=True)
    _make_link(conn, 1, 2)
    conn.commit()
    res = update_graph_metrics(conn)
    assert res["nodes"] == 1  # only note 1 is active


def test_update_graph_metrics_idempotente(tmp_path):
    conn = connect(tmp_path)
    _make_note(conn, 1, "a.md", "A")
    _make_note(conn, 2, "b.md", "B")
    _make_link(conn, 1, 2)
    conn.commit()
    res1 = update_graph_metrics(conn)
    res2 = update_graph_metrics(conn)
    assert res1["pagerank_sum"] == res2["pagerank_sum"]


def test_update_graph_metrics_grafo_vazio(tmp_path):
    conn = connect(tmp_path)
    res = update_graph_metrics(conn)
    assert res["nodes"] == 0
    assert res["pagerank_sum"] == 0.0


def test_update_graph_metrics_auto_link(tmp_path):
    conn = connect(tmp_path)
    _make_note(conn, 1, "a.md", "A")
    _make_link(conn, 1, 1)
    conn.commit()
    res = update_graph_metrics(conn)
    assert res["edges"] == 1


def test_find_mocs_heuristica(tmp_path):
    conn = connect(tmp_path)
    # nota MOC-like: out=12 in=6 (alto), nota normal: out=5 in=2
    for i in range(1, 30):
        _make_note(conn, i, f"n{i}.md", f"N{i}")
    # nota 1 tem out_degree 12 e in_degree 6
    for i in range(2, 14):
        _make_link(conn, 1, i)
    for i in range(14, 20):
        _make_link(conn, i, 1)
    # nota 20 tem out_degree 5 e in_degree 2
    for i in range(21, 26):
        _make_link(conn, 20, i)
    for i in range(26, 28):
        _make_link(conn, i, 20)
    conn.commit()
    update_graph_metrics(conn)
    mocs = find_mocs(conn, min_out_degree=10, min_in_degree=5)
    assert 1 in mocs
    assert 20 not in mocs


def test_find_mocs_vazio(tmp_path):
    conn = connect(tmp_path)
    update_graph_metrics(conn)
    assert find_mocs(conn) == []


def test_betweenness_opt_in(tmp_path):
    conn = connect(tmp_path)
    _make_note(conn, 1, "a.md", "A")
    _make_note(conn, 2, "b.md", "B")
    _make_note(conn, 3, "c.md", "C")
    _make_link(conn, 1, 2)
    _make_link(conn, 2, 3)
    conn.commit()
    res = update_graph_metrics(conn, with_betweenness=True)
    assert "betweenness" in res
    # node 2 is on path 1->2->3
    assert res["betweenness"][2] > 0
    # without flag: no key
    res2 = update_graph_metrics(conn, with_betweenness=False)
    assert "betweenness" not in res2


def test_performance_100_nodes(tmp_path):
    import random
    conn = connect(tmp_path)
    for i in range(1, 101):
        _make_note(conn, i, f"n{i}.md", f"N{i}")
    random.seed(42)
    for _ in range(300):
        a = random.randint(1, 100)
        b = random.randint(1, 100)
        if a != b:
            _make_link(conn, a, b)
    conn.commit()
    res = update_graph_metrics(conn)
    assert res["duration_s"] < 1.0
    assert res["nodes"] == 100
