"""Anomaly detection tests (Epic 06 S04 / Wave 4)."""
from __future__ import annotations

import datetime as _dt
import importlib.util
import pathlib
import sys

import pytest

from core import cli as core_cli
from core.db import connect

_PATH = (
    pathlib.Path(__file__).resolve().parent.parent
    / "skills" / "obsidian-pulse" / "scripts" / "anomaly.py"
)


def _load():
    name = "pulse_anomaly_tests"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, _PATH)
    assert spec is not None and spec.loader is not None
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


@pytest.fixture(scope="module")
def anom():
    return _load()


def _seed_area(conn, slug="profissional", label="Profissional", folder="01 - Profissional"):
    conn.execute(
        "INSERT INTO areas (slug, label, folder, is_canonical, created_at) "
        "VALUES (?, ?, ?, 1, datetime('now'))",
        (slug, label, folder),
    )
    conn.commit()
    return conn.execute("SELECT id FROM areas WHERE slug=?", (slug,)).fetchone()[0]


def _seed_event(conn, *, note_id, area_id, ts, event_type="note_updated"):
    conn.execute(
        "INSERT INTO events (ts, event_type, note_id, area_id, date) "
        "VALUES (?, ?, ?, ?, ?)",
        (ts, event_type, note_id, area_id, ts[:10]),
    )


def _seed_note(conn, path, title="t", area_id=None):
    conn.execute(
        "INSERT INTO notes (path, title, area_id, status, deleted_at, indexed_at) "
        "VALUES (?, ?, ?, 'ativo', NULL, datetime('now'))",
        (path, title, area_id),
    )
    conn.commit()
    return conn.execute("SELECT id FROM notes WHERE path=?", (path,)).fetchone()[0]


@pytest.fixture
def vault_com_streak_quebrado(tmp_path):
    core_cli.main(["init-db", "--vault", str(tmp_path)])
    conn = connect(tmp_path)
    area_id = _seed_area(conn)
    nid = _seed_note(conn, "01 - Profissional/nota.md", area_id=area_id)
    # 20 dias consecutivos de atividade, parando ha 3 dias
    today = _dt.date.today()
    for days_ago in range(3, 23):
        ts = (today - _dt.timedelta(days=days_ago)).isoformat() + "T10:00:00+00:00"
        _seed_event(conn, note_id=nid, area_id=area_id, ts=ts)
    conn.commit()
    return tmp_path, conn, area_id


def test_detect_broken_streaks_dispara(anom, vault_com_streak_quebrado):
    _, conn, _ = vault_com_streak_quebrado
    alerts = anom.detect_broken_streaks(conn)
    assert len(alerts) >= 1
    a = alerts[0]
    assert a["kind"] == "streak_broken"
    assert a["severity"] == "warn"
    assert "Quer olhar?" in a["reasoning"]


def test_streak_ativo_nao_alerta(anom, tmp_path):
    core_cli.main(["init-db", "--vault", str(tmp_path)])
    conn = connect(tmp_path)
    area_id = _seed_area(conn)
    nid = _seed_note(conn, "n.md", area_id=area_id)
    today = _dt.date.today()
    # 20 dias incluindo hoje
    for days_ago in range(0, 20):
        ts = (today - _dt.timedelta(days=days_ago)).isoformat() + "T10:00:00+00:00"
        _seed_event(conn, note_id=nid, area_id=area_id, ts=ts)
    conn.commit()
    assert anom.detect_broken_streaks(conn) == []


def test_detect_abandoned_area(anom, tmp_path):
    core_cli.main(["init-db", "--vault", str(tmp_path)])
    conn = connect(tmp_path)
    area_id = _seed_area(conn)
    nid = _seed_note(conn, "n.md", area_id=area_id)
    today = _dt.date.today()
    # Cadencia regular: 1 evento a cada 2 dias por 60 dias, depois gap de 20 dias
    for days_ago in range(22, 82, 2):
        ts = (today - _dt.timedelta(days=days_ago)).isoformat() + "T10:00:00+00:00"
        _seed_event(conn, note_id=nid, area_id=area_id, ts=ts)
    conn.commit()
    alerts = anom.detect_abandoned_areas(conn)
    assert len(alerts) >= 1
    a = alerts[0]
    assert a["kind"] == "area_abandoned"
    assert "p95" in a["reasoning"]
    assert a["severity"] == "info"


def test_save_alerts_respeita_max_1_warn_por_dia(anom, vault_com_streak_quebrado):
    _, conn, _ = vault_com_streak_quebrado
    # Cria 2 "warn" simulados — so o primeiro mantem severity warn; segundo vira info
    anomalies = [
        {
            "kind": "streak_broken", "area_id": 1, "severity": "warn",
            "content": "c1", "reasoning": "r1",
        },
        {
            "kind": "streak_broken", "area_id": 2, "severity": "warn",
            "content": "c2", "reasoning": "r2",
        },
    ]
    n = anom.save_alerts(conn, anomalies)
    assert n == 2
    warns = conn.execute(
        "SELECT COUNT(*) FROM alerts_cache WHERE severity='warn'"
    ).fetchone()[0]
    infos = conn.execute(
        "SELECT COUNT(*) FROM alerts_cache WHERE severity='info'"
    ).fetchone()[0]
    assert warns == 1
    assert infos == 1


def test_save_alerts_dedup_por_kind_area_dia(anom, vault_com_streak_quebrado):
    _, conn, area_id = vault_com_streak_quebrado
    a = {
        "kind": "streak_broken", "area_id": area_id, "severity": "warn",
        "content": "c", "reasoning": "r",
    }
    n1 = anom.save_alerts(conn, [a])
    n2 = anom.save_alerts(conn, [a])  # dedup
    assert n1 == 1 and n2 == 0


def test_reasoning_tom_anti_diagnostico(anom, vault_com_streak_quebrado):
    _, conn, _ = vault_com_streak_quebrado
    anomalies = anom.detect_anomalies(conn)
    # Nenhum reasoning deve usar forma diagnostica "voce esta"
    for a in anomalies:
        assert "voce esta" not in a["reasoning"].lower()
