"""FSRS scheduler tests (Epic 06 S03 / Wave 3)."""
from __future__ import annotations

import datetime as _dt
import importlib.util
import json
import pathlib
import sys

import pytest

from core import cli as core_cli
from core.db import connect

_PATH = (
    pathlib.Path(__file__).resolve().parent.parent
    / "skills" / "obsidian-pulse" / "scripts" / "fsrs_scheduler.py"
)


def _load():
    name = "pulse_fsrs_tests"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, _PATH)
    assert spec is not None and spec.loader is not None
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


@pytest.fixture(scope="module")
def fsrs_mod():
    return _load()


@pytest.fixture
def vault_com_reviews(tmp_path):
    """Vault com 2 notas 'reference' + eventos simulados de updates."""
    core_cli.main(["init-db", "--vault", str(tmp_path)])
    conn = connect(tmp_path)
    # Seed notes + events
    for path, title in (
        ("ref-old.md", "Ref Old"),
        ("ref-recent.md", "Ref Recent"),
        ("nota-normal.md", "Nota Normal"),
    ):
        type_ = "reference" if path.startswith("ref-") else "nota"
        conn.execute(
            "INSERT INTO notes (path, title, type, status, created, updated, indexed_at) "
            "VALUES (?, ?, ?, 'ativo', '2026-01-01', '2026-01-01', '2026-01-01')",
            (path, title, type_),
        )
    conn.commit()
    # Eventos: ref-old tem 3 updates antigos (devida), ref-recent tem 1 recente
    old_id = conn.execute("SELECT id FROM notes WHERE path='ref-old.md'").fetchone()[0]
    recent_id = conn.execute(
        "SELECT id FROM notes WHERE path='ref-recent.md'"
    ).fetchone()[0]
    # 3 events nos primeiros 60 dias de 2025 (antigo)
    for days_ago in (120, 90, 60):
        dt = (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=days_ago)).isoformat()
        date_str = dt[:10]
        conn.execute(
            "INSERT INTO events (ts, event_type, note_id, date) "
            "VALUES (?, 'note_updated', ?, ?)",
            (dt, old_id, date_str),
        )
    # 1 event ontem (recente)
    dt = (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=1)).isoformat()
    conn.execute(
        "INSERT INTO events (ts, event_type, note_id, date) "
        "VALUES (?, 'note_updated', ?, ?)",
        (dt, recent_id, dt[:10]),
    )
    conn.commit()
    return tmp_path, conn


def test_compute_due_dates_retorna_so_reference_fleeting(fsrs_mod, vault_com_reviews):
    _, conn = vault_com_reviews
    dues = fsrs_mod.compute_due_dates(conn)
    # Nota-normal type='nota' nao conta
    paths = {d["path"] for d in dues}
    assert "ref-old.md" in paths
    assert "ref-recent.md" in paths
    assert "nota-normal.md" not in paths


def test_compute_due_dates_inclui_stability_difficulty(fsrs_mod, vault_com_reviews):
    _, conn = vault_com_reviews
    dues = fsrs_mod.compute_due_dates(conn)
    for d in dues:
        assert d["stability"] > 0
        assert d["difficulty"] > 0
        assert d["update_count"] >= 1


def test_create_review_suggestions_gera_so_pra_devidas(fsrs_mod, vault_com_reviews):
    _, conn = vault_com_reviews
    n = fsrs_mod.create_review_suggestions(conn, window_days=2)
    # ref-old (3 updates ate 60 dias atras) provavelmente esta devida
    # ref-recent (1 update ontem) estabilidade baixa, pode ou nao aparecer
    assert n >= 1
    rows = conn.execute(
        "SELECT reasoning, target_note_ids FROM suggestions_cache WHERE kind='review'"
    ).fetchall()
    assert len(rows) == n
    for reasoning, _ in rows:
        assert "FSRS" in reasoning
        assert "stability" in reasoning


def test_dedup_nao_duplica_review_ativa(fsrs_mod, vault_com_reviews):
    _, conn = vault_com_reviews
    n1 = fsrs_mod.create_review_suggestions(conn)
    n2 = fsrs_mod.create_review_suggestions(conn)
    assert n1 >= 1
    assert n2 == 0  # segunda chamada nao duplica
    total = conn.execute(
        "SELECT COUNT(*) FROM suggestions_cache WHERE kind='review'"
    ).fetchone()[0]
    assert total == n1


def test_vault_sem_notas_reference_retorna_zero(fsrs_mod, tmp_path):
    core_cli.main(["init-db", "--vault", str(tmp_path)])
    conn = connect(tmp_path)
    assert fsrs_mod.compute_due_dates(conn) == []
    assert fsrs_mod.create_review_suggestions(conn) == 0
