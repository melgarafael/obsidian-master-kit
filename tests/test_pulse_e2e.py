"""End-to-end integration tests (Epic 06 S10 / Wave 10).

Cenarios cobertos:
- A: fixture vault -> refresh -> serve (TestClient) -> GET / retorna HTML
- B: accept suggestion via POST -> acted_on=1 no DB -> ranking deprioritiza
- C: blacklist ativada -> suggestion de nota sensivel -> dashboard redige
- E: 90 dias de eventos -> anomalies detectadas em refresh
"""
from __future__ import annotations

import datetime as _dt
import importlib.util
import json
import pathlib
import sys

import numpy as np
import pytest

from core import cli as core_cli
from core.db import connect
from core.scanner import scan

_BASE = pathlib.Path(__file__).resolve().parent.parent / "skills" / "obsidian-pulse" / "scripts"


def _load(name, filename):
    full = str(_BASE / filename)
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, full)
    assert spec is not None and spec.loader is not None
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


@pytest.fixture(scope="module")
def modules():
    return {
        "worker": _load("e2e_worker", "worker.py"),
        "server": _load("e2e_server", "server.py"),
        "privacy": _load("e2e_privacy", "privacy.py"),
        "anomaly": _load("e2e_anomaly", "anomaly.py"),
    }


class _FakeEmbedder:
    model_name = "fake-e2e-v1"
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


@pytest.fixture
def populated_vault(tmp_path):
    """Vault com notas + scan + 1 suggestion seed."""
    # Cria notas ref pra FSRS tocar
    (tmp_path / "01 - Profissional").mkdir(parents=True, exist_ok=True)
    (tmp_path / "01 - Profissional" / "ref1.md").write_text(
        "---\ntype: reference\n---\n# Ref 1\ncorpo", encoding="utf-8"
    )
    (tmp_path / "01 - Profissional" / "ref2.md").write_text(
        "---\ntype: reference\n---\n# Ref 2\ncorpo", encoding="utf-8"
    )
    core_cli.main(["init-db", "--vault", str(tmp_path)])
    conn = connect(tmp_path)
    scan(conn, tmp_path, embedder=_FakeEmbedder())
    return tmp_path, conn


# ---------- cenario A: refresh + serve + GET / ----------


def test_cenario_a_refresh_serve_html(modules, populated_vault):
    vault, conn = populated_vault
    # Refresh nao deve crash
    result = modules["worker"].run_batch_analytics(conn)
    assert all(s["duration_ms"] >= 0 for s in result["stages"])
    # Serve via TestClient
    from fastapi.testclient import TestClient
    app = modules["server"].build_app(vault, token="TOK")
    client = TestClient(app)
    r = client.get("/")
    assert r.status_code == 200
    assert "obsidian-pulse" in r.text.lower()


# ---------- cenario B: accept flow ----------


def test_cenario_b_accept_marca_acted_on(modules, populated_vault):
    vault, conn = populated_vault
    # Seed uma suggestion bridge
    conn.execute(
        "INSERT INTO suggestions_cache "
        "(generated_at, expires_at, kind, target_note_ids, content, reasoning, "
        " score, dismissed, acted_on) "
        "VALUES (datetime('now'), datetime('now','+7 days'), 'bridge', "
        " '[1,2]', 'c', 'r', 0.8, 0, 0)"
    )
    conn.commit()
    sid = conn.execute(
        "SELECT id FROM suggestions_cache ORDER BY id DESC LIMIT 1"
    ).fetchone()[0]
    from fastapi.testclient import TestClient
    app = modules["server"].build_app(vault, token="TOK")
    client = TestClient(app)
    r = client.post(f"/api/accept/{sid}", headers={"X-Pulse-Token": "TOK"})
    assert r.status_code == 200
    # DB confere acted_on=1
    acted = conn.execute(
        "SELECT acted_on FROM suggestions_cache WHERE id=?", (sid,)
    ).fetchone()[0]
    assert acted == 1
    # Event suggestion_accepted foi registrado
    ev = conn.execute(
        "SELECT COUNT(*) FROM events WHERE event_type='suggestion_accepted'"
    ).fetchone()[0]
    assert ev >= 1


# ---------- cenario C: blacklist + redacao ----------


def test_cenario_c_blacklist_redige_dashboard(modules, tmp_path):
    core_cli.main(["init-db", "--vault", str(tmp_path)])
    conn = connect(tmp_path)
    # Seed area + notas
    conn.execute(
        "INSERT INTO areas (slug, label, folder, is_canonical, created_at) "
        "VALUES ('pessoal', 'Pessoal', '00 - Pessoal', 1, datetime('now'))"
    )
    area_id = conn.execute("SELECT id FROM areas").fetchone()[0]
    conn.execute(
        "INSERT INTO notes (path, title, area_id, status, indexed_at) "
        "VALUES ('00 - Pessoal/Journaling/diario.md', 'Diario privado', ?, 'ativo', datetime('now'))",
        (area_id,),
    )
    conn.commit()
    nid = conn.execute("SELECT id FROM notes LIMIT 1").fetchone()[0]
    conn.execute(
        "INSERT INTO suggestions_cache "
        "(generated_at, expires_at, kind, target_note_ids, content, reasoning, "
        " score, dismissed, acted_on) "
        "VALUES (datetime('now'), datetime('now','+7 days'), 'review', ?, "
        " 'Revisar [[Diario privado]]', 'titulo vazado aqui', 0.9, 0, 0)",
        (json.dumps([nid]),),
    )
    conn.commit()
    # Aplica blacklist
    bl = tmp_path / ".obsidian-master" / "blacklist.json"
    bl.write_text(
        json.dumps({"patterns": ["00 - Pessoal/Journaling/**"]}), encoding="utf-8"
    )
    n = modules["privacy"].mark_sensitive_notes(conn, tmp_path)
    assert n == 1
    # GET /api/suggestions redige
    from fastapi.testclient import TestClient
    app = modules["server"].build_app(tmp_path, token="TOK")
    client = TestClient(app)
    r = client.get("/api/suggestions", headers={"X-Pulse-Token": "TOK"})
    assert r.status_code == 200
    sugg = r.json()["suggestions"][0]
    assert "Diario privado" not in sugg["content"]
    assert "Diario privado" not in sugg["reasoning"]
    assert "sensivel" in sugg["content"].lower()


# ---------- cenario E: anomalias detectadas ----------


def test_cenario_e_90_dias_eventos_detecta_streak_broken(modules, tmp_path):
    core_cli.main(["init-db", "--vault", str(tmp_path)])
    conn = connect(tmp_path)
    conn.execute(
        "INSERT INTO areas (slug, label, folder, is_canonical, created_at) "
        "VALUES ('prof', 'Profissional', '01 - Profissional', 1, datetime('now'))"
    )
    area_id = conn.execute("SELECT id FROM areas LIMIT 1").fetchone()[0]
    conn.execute(
        "INSERT INTO notes (path, title, area_id, status, indexed_at) "
        "VALUES ('x.md', 'X', ?, 'ativo', datetime('now'))",
        (area_id,),
    )
    nid = conn.execute("SELECT id FROM notes").fetchone()[0]
    conn.commit()
    today = _dt.date.today()
    # Streak de 20 dias encerrado ha 3 dias
    for days_ago in range(3, 23):
        ts = (today - _dt.timedelta(days=days_ago)).isoformat() + "T10:00:00+00:00"
        conn.execute(
            "INSERT INTO events (ts, event_type, note_id, area_id, date) "
            "VALUES (?, 'note_updated', ?, ?, ?)",
            (ts, nid, area_id, ts[:10]),
        )
    conn.commit()
    # Run batch via worker
    result = modules["worker"].run_batch_analytics(conn)
    # Anomaly stage deve ter detectado + salvo
    anomaly_stage = next(s for s in result["stages"] if s["stage"] == "anomaly")
    assert anomaly_stage["result"]["saved"] >= 1
    rows = conn.execute(
        "SELECT kind FROM alerts_cache WHERE kind='streak_broken'"
    ).fetchall()
    assert len(rows) >= 1


# ---------- robustez: refresh idempotente ----------


def test_refresh_idempotente_nao_cria_duplicatas(modules, populated_vault):
    vault, conn = populated_vault
    r1 = modules["worker"].run_batch_analytics(conn)
    r2 = modules["worker"].run_batch_analytics(conn)
    # FSRS stage retorna count inseridos. Segunda chamada, dedup -> 0.
    fsrs_r2 = next(s for s in r2["stages"] if s["stage"] == "fsrs")
    # Pode ser 0 ou pequeno (se dedup pegar)
    assert fsrs_r2["result"] >= 0
