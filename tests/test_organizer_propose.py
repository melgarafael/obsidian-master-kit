"""Testes propose.py (Epic 04 S06 / Wave 6)."""
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
    / "skills" / "obsidian-organizer" / "scripts" / "propose.py"
)


def _load():
    name = "organizer_propose_tests"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, _PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


class _SimpleEmbedder:
    model_name = "fake-prop-v1"
    dim = 256

    def embed(self, texts):
        out = []
        for t in texts:
            rng = np.random.default_rng(hash(t) & 0xFFFFFFFF)
            v = rng.standard_normal(256).astype(np.float32)
            v /= np.linalg.norm(v) or 1.0
            out.append(v)
        if not out:
            return np.zeros((0, 256), dtype=np.float32)
        return np.stack(out)


@pytest.fixture(scope="module")
def prop():
    return _load()


@pytest.fixture
def vault_com_outputs(tmp_path):
    """Vault com notas + suggestions seeded + duplicate com verdict=merge."""
    notas = [
        ("01 - Profissional/nota-a.md",
         "---\narea: pessoal\ntype: nota\nstatus: ativo\n---\n# A\n"),
        ("01 - Profissional/nota-b.md", "# B\n"),
        ("02 - Pesquisas e Estudos/nota-c.md", "# C\n"),
        ("02 - Pesquisas e Estudos/nota-d.md", "# D\n"),
    ]
    for rel, body in notas:
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    core_cli.main(["init-db", "--vault", str(tmp_path)])
    conn = connect(tmp_path)
    scan(conn, tmp_path, embedder=_SimpleEmbedder())
    # Seed: 1 suggestion area_mismatch + 1 suggestion moc_missing + 1 duplicate verdict=merge
    ids = dict(conn.execute("SELECT path, id FROM notes").fetchall())
    a = ids["01 - Profissional/nota-a.md"]
    b = ids["01 - Profissional/nota-b.md"]
    c = ids["02 - Pesquisas e Estudos/nota-c.md"]
    d = ids["02 - Pesquisas e Estudos/nota-d.md"]
    conn.execute(
        """INSERT INTO suggestions_cache
           (generated_at, expires_at, kind, target_note_ids, content, reasoning,
            score, dismissed, acted_on)
           VALUES (datetime('now'), datetime('now','+7 days'), 'area_mismatch',
                   ?, 'c', 'r', 0.4, 0, 0)""",
        (json.dumps([a]),),
    )
    conn.execute(
        """INSERT INTO suggestions_cache
           (generated_at, expires_at, kind, target_note_ids, content, reasoning,
            score, dismissed, acted_on)
           VALUES (datetime('now'), datetime('now','+7 days'), 'moc_missing',
                   ?, 'moc falta', 'reasoning', 0.6, 0, 0)""",
        (json.dumps([c, d]),),
    )
    conn.execute(
        """INSERT INTO duplicate_candidates
           (note_a_id, note_b_id, cosine_similarity, detected_at, verdict)
           VALUES (?, ?, 0.85, datetime('now'), 'merge')""",
        (c, d),
    )
    conn.commit()
    return tmp_path, conn


def test_propose_dry_run_nao_escreve_migration_plan(prop, vault_com_outputs):
    _, conn = vault_com_outputs
    result = prop.propose(conn, dry_run=True)
    assert result["dry_run"] is True
    assert result["entry_count"] > 0
    assert result["batch_id"] is None
    count = conn.execute("SELECT COUNT(*) FROM migration_plan").fetchone()[0]
    assert count == 0


def test_propose_no_dry_run_escreve_batch(prop, vault_com_outputs):
    _, conn = vault_com_outputs
    result = prop.propose(conn, dry_run=False)
    assert result["dry_run"] is False
    assert result["batch_id"] is not None
    assert result["entry_count"] > 0
    rows = conn.execute(
        "SELECT note_path, reason, batch_id, status FROM migration_plan"
    ).fetchall()
    assert len(rows) == result["entry_count"]
    for _, _, batch_id, status in rows:
        assert batch_id == result["batch_id"]
        assert status == "pending"


def test_propose_inclui_merge_para_duplicate_aprovada(prop, vault_com_outputs):
    _, conn = vault_com_outputs
    result = prop.propose(conn, dry_run=True)
    kinds = [e["kind"] for e in result["entries_preview"]]
    assert "merge_duplicate" in kinds


def test_propose_by_kind_tem_varias_fontes(prop, vault_com_outputs):
    _, conn = vault_com_outputs
    result = prop.propose(conn, dry_run=True)
    assert len(result["by_kind"]) >= 2  # pelo menos moc_missing + merge_duplicate


def test_propose_sem_outputs_retorna_vazio(prop, tmp_path):
    core_cli.main(["init-db", "--vault", str(tmp_path)])
    conn = connect(tmp_path)
    result = prop.propose(conn, dry_run=False)
    assert result["entry_count"] == 0
    assert result["batch_id"] is None


def test_propose_batch_id_incrementa(prop, vault_com_outputs):
    _, conn = vault_com_outputs
    r1 = prop.propose(conn, dry_run=False)
    r2 = prop.propose(conn, dry_run=False)
    assert r2["batch_id"] > r1["batch_id"]


def test_summary_consolida_estado(prop, vault_com_outputs):
    _, conn = vault_com_outputs
    s = prop.summary(conn)
    assert s["notes_active"] == 4
    assert s["suggestions_pending"]["area_mismatch"] >= 1
    assert s["suggestions_pending"]["moc_missing"] >= 1
    # duplicate com verdict=merge NAO conta em pending (verdict nao-NULL)
    assert s["duplicates_pending"] == 0


def test_summary_vault_vazio(prop, tmp_path):
    core_cli.main(["init-db", "--vault", str(tmp_path)])
    conn = connect(tmp_path)
    s = prop.summary(conn)
    assert s["notes_active"] == 0
    assert s["latest_run_id"] is None
    assert s["duplicates_pending"] == 0
