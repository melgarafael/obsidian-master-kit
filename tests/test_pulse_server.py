"""FastAPI server tests (Epic 06 S06 / Wave 6)."""
from __future__ import annotations

import importlib.util
import json
import pathlib
import sys

import pytest

from core import cli as core_cli
from core.db import connect

_PATH = (
    pathlib.Path(__file__).resolve().parent.parent
    / "skills" / "obsidian-pulse" / "scripts" / "server.py"
)


def _load():
    name = "pulse_server_tests"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, _PATH)
    assert spec is not None and spec.loader is not None
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


@pytest.fixture(scope="module")
def srv():
    return _load()


@pytest.fixture
def vault(tmp_path):
    core_cli.main(["init-db", "--vault", str(tmp_path)])
    return tmp_path


@pytest.fixture
def app_client(srv, vault):
    from fastapi.testclient import TestClient
    app = srv.build_app(vault, token="testtoken")
    return TestClient(app), "testtoken"


def test_token_gerado_e_persistido(srv, vault):
    t1 = srv._get_or_create_token(vault)
    t2 = srv._get_or_create_token(vault)
    assert t1 == t2  # idempotente
    token_path = vault / ".obsidian-master" / "pulse-token.txt"
    assert token_path.exists()


def test_api_requer_token(app_client):
    client, _ = app_client
    r = client.get("/api/status")
    assert r.status_code == 401


def test_api_aceita_token_via_header(app_client):
    client, token = app_client
    r = client.get("/api/status", headers={"X-Pulse-Token": token})
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_api_aceita_token_via_query(app_client):
    client, token = app_client
    r = client.get(f"/api/status?token={token}")
    assert r.status_code == 200


def test_api_rejeita_token_errado(app_client):
    client, _ = app_client
    r = client.get("/api/status", headers={"X-Pulse-Token": "wrong"})
    assert r.status_code == 401


def test_api_suggestions_vault_vazio(app_client):
    client, token = app_client
    r = client.get("/api/suggestions", headers={"X-Pulse-Token": token})
    assert r.status_code == 200
    assert r.json() == {"suggestions": [], "count": 0}


def test_api_alerts_vault_vazio(app_client):
    client, token = app_client
    r = client.get("/api/alerts", headers={"X-Pulse-Token": token})
    assert r.status_code == 200
    assert r.json()["alerts"] == []


def test_api_heatmap_vault_vazio(app_client):
    client, token = app_client
    r = client.get("/api/heatmap", headers={"X-Pulse-Token": token})
    assert r.status_code == 200
    assert r.json() == {"days": []}


def test_api_insights_vault_vazio(app_client):
    client, token = app_client
    r = client.get("/api/insights", headers={"X-Pulse-Token": token})
    assert r.status_code == 200
    assert r.json() == {"insights": []}


def test_api_accept_marca_acted_on(app_client, vault):
    client, token = app_client
    conn = connect(vault)
    conn.execute(
        "INSERT INTO suggestions_cache "
        "(generated_at, expires_at, kind, target_note_ids, content, reasoning, score, dismissed, acted_on) "
        "VALUES (datetime('now'), datetime('now','+7 days'), 'bridge', '[1]', 'c', 'r', 0.5, 0, 0)"
    )
    conn.commit()
    sid = conn.execute(
        "SELECT id FROM suggestions_cache ORDER BY id DESC LIMIT 1"
    ).fetchone()[0]
    r = client.post(
        f"/api/accept/{sid}", headers={"X-Pulse-Token": token}
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True
    acted = conn.execute(
        "SELECT acted_on FROM suggestions_cache WHERE id=?", (sid,)
    ).fetchone()[0]
    assert acted == 1


def test_api_dismiss_marca_dismissed(app_client, vault):
    client, token = app_client
    conn = connect(vault)
    conn.execute(
        "INSERT INTO suggestions_cache "
        "(generated_at, expires_at, kind, target_note_ids, content, reasoning, score, dismissed, acted_on) "
        "VALUES (datetime('now'), datetime('now','+7 days'), 'review', '[1]', 'c', 'r', 0.5, 0, 0)"
    )
    conn.commit()
    sid = conn.execute(
        "SELECT id FROM suggestions_cache ORDER BY id DESC LIMIT 1"
    ).fetchone()[0]
    r = client.post(
        f"/api/dismiss/{sid}", headers={"X-Pulse-Token": token}
    )
    assert r.status_code == 200
    dismissed = conn.execute(
        "SELECT dismissed, dismissed_at FROM suggestions_cache WHERE id=?", (sid,)
    ).fetchone()
    assert dismissed[0] == 1
    assert dismissed[1] is not None


def test_dashboard_root_retorna_html(app_client):
    client, _ = app_client
    r = client.get("/")
    assert r.status_code == 200
    assert "obsidian-pulse" in r.text.lower()


def test_dashboard_tem_6_tabs(app_client):
    client, _ = app_client
    r = client.get("/")
    body = r.text
    for tab in ("hoje", "pulso", "grafo", "saude", "descobrir", "insights"):
        assert f'data-tab="{tab}"' in body


def test_dashboard_usa_cal_heatmap(app_client):
    client, _ = app_client
    r = client.get("/")
    assert "cal-heatmap" in r.text
    assert "CalHeatmap" in r.text


def test_dashboard_nao_usa_innerHTML(app_client):
    """Anti-XSS: garantir que nao tem innerHTML (so textContent + DOM API)."""
    client, _ = app_client
    r = client.get("/")
    assert "innerHTML" not in r.text
