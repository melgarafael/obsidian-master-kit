"""Testes para cluster.py — HDBSCAN runner (Epic 04 S02 / Wave 2)."""
from __future__ import annotations

import importlib.util
import pathlib
import sys

import numpy as np
import pytest

from core import cli as core_cli
from core.db import connect
from core.scanner import scan

_CLUSTER_PATH = (
    pathlib.Path(__file__).resolve().parent.parent
    / "skills" / "obsidian-organizer" / "scripts" / "cluster.py"
)


def _load_cluster():
    name = "organizer_cluster_tests"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, _CLUSTER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class _ClusteredEmbedder:
    """Agrupa por tag no path: esoterico/tech/pessoal viram clusters."""

    model_name = "fake-clustered-v1"
    dim = 256

    def __init__(self):
        self._groups: dict[str, np.ndarray] = {}

    def _group_base(self, g):
        if g not in self._groups:
            rng = np.random.default_rng(hash(g) & 0xFFFFFFFF)
            v = rng.standard_normal(self.dim).astype(np.float32)
            v /= np.linalg.norm(v) or 1.0
            self._groups[g] = v
        return self._groups[g]

    def embed(self, texts):
        out = []
        for t in texts:
            group = None
            for g in ("esoterico", "tech", "pessoal"):
                if g in t.lower():
                    group = g
                    break
            if group:
                base = self._group_base(group)
                rng = np.random.default_rng(hash(t) & 0xFFFFFFFF)
                v = base + rng.standard_normal(self.dim).astype(np.float32) * 0.03
            else:
                rng = np.random.default_rng(hash(t) & 0xFFFFFFFF)
                v = rng.standard_normal(self.dim).astype(np.float32)
            v /= np.linalg.norm(v) or 1.0
            out.append(v)
        if not out:
            return np.zeros((0, self.dim), dtype=np.float32)
        return np.stack(out)


@pytest.fixture(scope="module")
def cluster():
    return _load_cluster()


@pytest.fixture
def vault_clustered(tmp_path):
    """Vault com 15 notas em 3 grupos de 5 pra forcar HDBSCAN a achar clusters."""
    for i in range(5):
        (tmp_path / f"esoterico-{i}.md").write_text(
            f"# Nota esoterico {i}\nconteudo esoterico com variacao {i}",
            encoding="utf-8",
        )
        (tmp_path / f"tech-{i}.md").write_text(
            f"# Nota tech {i}\nconteudo tech numero {i}",
            encoding="utf-8",
        )
        (tmp_path / f"pessoal-{i}.md").write_text(
            f"# Nota pessoal {i}\ntexto pessoal distinto {i}",
            encoding="utf-8",
        )
    core_cli.main(["init-db", "--vault", str(tmp_path)])
    conn = connect(tmp_path)
    scan(conn, tmp_path, embedder=_ClusteredEmbedder())
    return tmp_path, conn


def test_load_notes_com_embeddings(cluster, vault_clustered):
    _, conn = vault_clustered
    notes, embs = cluster.load_notes_with_embeddings(conn)
    assert len(notes) == 15
    assert embs.shape == (15, 256)
    # Todos tem id, path, title
    for n in notes:
        assert "id" in n and "path" in n


def test_run_hdbscan_retorna_labels(cluster, vault_clustered):
    _, conn = vault_clustered
    notes, embs = cluster.load_notes_with_embeddings(conn)
    labels = cluster.run_hdbscan(embs, min_cluster_size=3)
    assert len(labels) == len(notes)
    assert all(isinstance(l, (int, np.integer)) for l in labels)


def test_run_hdbscan_acha_pelo_menos_um_cluster(cluster, vault_clustered):
    _, conn = vault_clustered
    notes, embs = cluster.load_notes_with_embeddings(conn)
    labels = cluster.run_hdbscan(embs, min_cluster_size=3)
    unique = set(int(l) for l in labels if l != -1)
    assert len(unique) >= 1, "esperava >= 1 cluster em vault clustered"


def test_summarize_gera_label_por_cluster(cluster, vault_clustered):
    _, conn = vault_clustered
    notes, embs = cluster.load_notes_with_embeddings(conn)
    labels = cluster.run_hdbscan(embs, min_cluster_size=3)
    summaries = cluster.summarize_clusters(notes, embs, labels)
    assert len(summaries) >= 1
    for s in summaries:
        assert "label" in s and s["label"]
        assert "note_count" in s and s["note_count"] >= 3
        assert "central_note_ids" in s
        assert len(s["central_note_ids"]) <= 3


def test_persist_clusters_grava_tabela(cluster, vault_clustered):
    _, conn = vault_clustered
    notes, embs = cluster.load_notes_with_embeddings(conn)
    labels = cluster.run_hdbscan(embs, min_cluster_size=3)
    summaries = cluster.summarize_clusters(notes, embs, labels)
    run_id = cluster.persist_clusters(conn, summaries, min_cluster_size=3)
    assert run_id.startswith("hdbscan-")
    count = conn.execute(
        "SELECT COUNT(*) FROM clusters WHERE run_id = ?", (run_id,)
    ).fetchone()[0]
    assert count == len(summaries)
    # cluster_notes populou
    total_notes = conn.execute(
        "SELECT COUNT(*) FROM cluster_notes cn "
        "JOIN clusters c ON c.id = cn.cluster_id WHERE c.run_id = ?",
        (run_id,),
    ).fetchone()[0]
    assert total_notes >= 9  # pelo menos 3 clusters x 3 notas


def test_run_orchestra_end_to_end(cluster, vault_clustered):
    _, conn = vault_clustered
    result = cluster.run(conn)
    assert "run_id" in result
    assert result["note_count"] == 15
    assert result["cluster_count"] >= 1
    assert result["min_cluster_size"] >= 5  # 15 // 200 = 0 -> max(5, 0) = 5
    assert "clusters" in result


def test_run_com_notas_insuficientes_retorna_error(cluster, tmp_path):
    core_cli.main(["init-db", "--vault", str(tmp_path)])
    conn = connect(tmp_path)
    result = cluster.run(conn)
    assert "error" in result
    assert result["note_count"] == 0


def test_run_id_unico_por_chamada(cluster, vault_clustered):
    _, conn = vault_clustered
    r1 = cluster.run(conn)
    import time
    time.sleep(1.1)  # garante timestamp diferente (precisao segundo)
    r2 = cluster.run(conn)
    assert r1["run_id"] != r2["run_id"]


def test_runs_antigos_sao_preservados(cluster, vault_clustered):
    _, conn = vault_clustered
    r1 = cluster.run(conn)
    import time
    time.sleep(1.1)
    r2 = cluster.run(conn)
    # Ambos runs devem ainda existir
    run_ids = set(
        row[0] for row in conn.execute("SELECT DISTINCT run_id FROM clusters").fetchall()
    )
    assert r1["run_id"] in run_ids
    assert r2["run_id"] in run_ids
