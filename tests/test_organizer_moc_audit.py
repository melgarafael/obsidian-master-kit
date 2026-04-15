"""Testes para moc_audit.py (Epic 04 S04 / Wave 4)."""
from __future__ import annotations

import importlib.util
import json
import pathlib
import sys

import numpy as np
import pytest

from core import cli as core_cli
from core.db import connect
from core.scanner import scan

_PATH = (
    pathlib.Path(__file__).resolve().parent.parent
    / "skills" / "obsidian-organizer" / "scripts" / "moc_audit.py"
)
_CLUSTER_PATH = (
    pathlib.Path(__file__).resolve().parent.parent
    / "skills" / "obsidian-organizer" / "scripts" / "cluster.py"
)


def _load(name, path):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class _ClusteredEmbedder:
    model_name = "fake-moc-v1"
    dim = 256

    def __init__(self):
        self._bases: dict[str, np.ndarray] = {}

    def _base(self, g):
        if g not in self._bases:
            rng = np.random.default_rng(hash(g) & 0xFFFFFFFF)
            v = rng.standard_normal(self.dim).astype(np.float32)
            v /= np.linalg.norm(v) or 1.0
            self._bases[g] = v
        return self._bases[g]

    def embed(self, texts):
        out = []
        for t in texts:
            group = None
            for g in ("esoterico", "tech", "pessoal"):
                if g in t.lower():
                    group = g
                    break
            if group:
                base = self._base(group)
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
def moc():
    return _load("organizer_moc_audit_tests", _PATH)


@pytest.fixture(scope="module")
def cluster():
    return _load("organizer_cluster_for_moc_tests", _CLUSTER_PATH)


@pytest.fixture
def vault_com_cluster_sem_moc(tmp_path, cluster):
    """Cria vault com 12 notas 'esoterico' (sem MOC) + 12 'tech' (com _MOC.md).

    Clustering produz 2 clusters >= 10; organizer deve flaggar so o esoterico.
    """
    for i in range(12):
        (tmp_path / f"esoterico-{i:02d}.md").write_text(
            f"# Nota esoterico {i}\nconteudo esoterico {i}", encoding="utf-8"
        )
        (tmp_path / f"tech-{i:02d}.md").write_text(
            f"# Nota tech {i}\nconteudo tech {i}", encoding="utf-8"
        )
    (tmp_path / "_MOC-tech.md").write_text(
        "---\ntype: moc\n---\n# MOC tech\nconteudo tech central", encoding="utf-8"
    )
    core_cli.main(["init-db", "--vault", str(tmp_path)])
    conn = connect(tmp_path)
    scan(conn, tmp_path, embedder=_ClusteredEmbedder())
    cluster.run(conn)
    return tmp_path, conn


def test_audit_encontra_cluster_sem_moc(moc, vault_com_cluster_sem_moc):
    _, conn = vault_com_cluster_sem_moc
    proposals = moc.audit_mocs(conn, min_notes=10)
    # Esperamos ao menos 1 proposta (esoterico, sem MOC)
    assert len(proposals) >= 1
    p = proposals[0]
    assert p["note_count"] >= 10
    assert "notas" in p["reasoning"].lower()
    assert "cluster" in p["reasoning"].lower()
    assert len(p["note_ids"]) >= 10


def test_audit_nao_flagga_cluster_com_moc(moc, vault_com_cluster_sem_moc):
    _, conn = vault_com_cluster_sem_moc
    proposals = moc.audit_mocs(conn, min_notes=10)
    # Nenhuma proposta deve apontar pra cluster contendo o nota-MOC tech
    moc_note_id = conn.execute(
        "SELECT id FROM notes WHERE path = '_MOC-tech.md'"
    ).fetchone()[0]
    for p in proposals:
        assert moc_note_id not in p["note_ids"]


def test_audit_respeita_min_notes(moc, vault_com_cluster_sem_moc):
    _, conn = vault_com_cluster_sem_moc
    # min alto exclui todos
    assert moc.audit_mocs(conn, min_notes=1000) == []


def test_audit_sem_clusters_retorna_vazio(moc, tmp_path):
    core_cli.main(["init-db", "--vault", str(tmp_path)])
    conn = connect(tmp_path)
    assert moc.audit_mocs(conn) == []


def test_save_suggestions_grava_em_cache_com_reasoning(moc, vault_com_cluster_sem_moc):
    _, conn = vault_com_cluster_sem_moc
    proposals = moc.audit_mocs(conn, min_notes=10)
    if not proposals:
        pytest.skip("fixture nao gerou propostas")
    n = moc.save_suggestions(conn, proposals)
    assert n == len(proposals)
    rows = conn.execute(
        "SELECT kind, reasoning, target_note_ids FROM suggestions_cache "
        "WHERE kind='moc_missing'"
    ).fetchall()
    assert len(rows) == n
    for kind, reasoning, targets_json in rows:
        assert kind == "moc_missing"
        assert reasoning and len(reasoning) > 20
        assert isinstance(json.loads(targets_json), list)


def test_audit_nao_duplica_sugestao_para_mesmo_cluster(moc, vault_com_cluster_sem_moc):
    _, conn = vault_com_cluster_sem_moc
    p1 = moc.audit_mocs(conn, min_notes=10)
    if not p1:
        pytest.skip("fixture sem proposals")
    moc.save_suggestions(conn, p1)
    # Segunda chamada nao deve produzir duplicata ativa
    p2 = moc.audit_mocs(conn, min_notes=10)
    assert len(p2) == 0, "audit nao pode redisparar cluster ja com suggestion ativa"


def test_create_moc_stub_cria_arquivo(moc, vault_com_cluster_sem_moc):
    vault, conn = vault_com_cluster_sem_moc
    proposals = moc.audit_mocs(conn, min_notes=10)
    if not proposals:
        pytest.skip("fixture nao gerou propostas")
    p = proposals[0]
    path = moc.create_moc_stub(vault, p, conn)
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert "type: moc" in text
    assert "status: draft" in text
    assert "generated_by: obsidian-organizer" in text
    assert "[[" in text  # tem pelo menos 1 wikilink
