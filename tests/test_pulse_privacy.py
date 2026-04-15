"""Privacy redaction tests (Epic 06 S08 / Wave 8)."""
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
    / "skills" / "obsidian-pulse" / "scripts" / "privacy.py"
)
_SERVER_PATH = (
    pathlib.Path(__file__).resolve().parent.parent
    / "skills" / "obsidian-pulse" / "scripts" / "server.py"
)


def _load(name, path):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


@pytest.fixture(scope="module")
def priv():
    return _load("pulse_privacy_tests", _PATH)


@pytest.fixture
def vault_com_blacklist(tmp_path):
    core_cli.main(["init-db", "--vault", str(tmp_path)])
    conn = connect(tmp_path)
    # Seed area + notas
    conn.execute(
        "INSERT INTO areas (slug, label, folder, is_canonical, created_at) "
        "VALUES ('pessoal', 'Pessoal', '00 - Pessoal', 1, datetime('now'))"
    )
    conn.commit()
    area_id = conn.execute("SELECT id FROM areas LIMIT 1").fetchone()[0]
    for path in (
        "00 - Pessoal/Journaling/diario-2026.md",
        "00 - Pessoal/publica.md",
        "01 - Profissional/ok.md",
    ):
        conn.execute(
            "INSERT INTO notes (path, title, area_id, status, indexed_at) "
            "VALUES (?, ?, ?, 'ativo', datetime('now'))",
            (path, path.split("/")[-1], area_id),
        )
    conn.commit()
    # Blacklist: tudo em Journaling/
    bl = tmp_path / ".obsidian-master" / "blacklist.json"
    bl.write_text(json.dumps({"patterns": ["00 - Pessoal/Journaling/**"]}),
                  encoding="utf-8")
    return tmp_path, conn


def test_load_blacklist_le_patterns(priv, vault_com_blacklist):
    vault, _ = vault_com_blacklist
    patterns = priv.load_blacklist(vault)
    assert "00 - Pessoal/Journaling/**" in patterns


def test_load_blacklist_aceita_lista_plain(priv, tmp_path):
    (tmp_path / ".obsidian-master").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".obsidian-master" / "blacklist.json").write_text(
        json.dumps(["pasta/**", "secret.md"]), encoding="utf-8"
    )
    patterns = priv.load_blacklist(tmp_path)
    assert "pasta/**" in patterns
    assert "secret.md" in patterns


def test_load_blacklist_sem_arquivo_retorna_vazio(priv, tmp_path):
    assert priv.load_blacklist(tmp_path) == []


def test_mark_sensitive_notes_marca_corretamente(priv, vault_com_blacklist):
    vault, conn = vault_com_blacklist
    n = priv.mark_sensitive_notes(conn, vault)
    assert n == 1  # so a nota em Journaling
    rows = conn.execute(
        "SELECT path, sensitive FROM notes ORDER BY id"
    ).fetchall()
    by_path = {r[0]: r[1] for r in rows}
    assert by_path["00 - Pessoal/Journaling/diario-2026.md"] == 1
    assert by_path["00 - Pessoal/publica.md"] == 0
    assert by_path["01 - Profissional/ok.md"] == 0


def test_redact_entry_esconde_sensitive(priv, vault_com_blacklist):
    vault, conn = vault_com_blacklist
    priv.mark_sensitive_notes(conn, vault)
    sensitive_id = conn.execute(
        "SELECT id FROM notes WHERE path='00 - Pessoal/Journaling/diario-2026.md'"
    ).fetchone()[0]
    entry = {
        "id": 1,
        "target_note_ids": [sensitive_id],
        "content": "Revisar [[diario-2026]]",
        "reasoning": "Titulo privado aparecendo aqui",
    }
    redacted = priv.redact_entry(conn, entry, show_sensitive=False)
    assert "diario-2026" not in redacted["content"]
    assert "diario-2026" not in redacted["reasoning"]
    assert "sensivel" in redacted["content"].lower()
    assert redacted["sensitive"] is True


def test_redact_nao_muda_entry_publica(priv, vault_com_blacklist):
    vault, conn = vault_com_blacklist
    priv.mark_sensitive_notes(conn, vault)
    public_id = conn.execute(
        "SELECT id FROM notes WHERE path='00 - Pessoal/publica.md'"
    ).fetchone()[0]
    entry = {
        "id": 2,
        "target_note_ids": [public_id],
        "content": "Nota publica",
        "reasoning": "ok",
    }
    result = priv.redact_entry(conn, entry)
    assert result["content"] == "Nota publica"


def test_redact_show_sensitive_true_preserva(priv, vault_com_blacklist):
    vault, conn = vault_com_blacklist
    priv.mark_sensitive_notes(conn, vault)
    sid = conn.execute(
        "SELECT id FROM notes WHERE path='00 - Pessoal/Journaling/diario-2026.md'"
    ).fetchone()[0]
    entry = {
        "id": 3,
        "target_note_ids": [sid],
        "content": "Revisar [[diario-2026]]",
        "reasoning": "content original",
    }
    result = priv.redact_entry(conn, entry, show_sensitive=True)
    assert result["content"] == "Revisar [[diario-2026]]"


def test_api_suggestions_redige_sensitive_por_default(vault_com_blacklist):
    vault, conn = vault_com_blacklist
    priv = _load("pulse_privacy_tests", _PATH)
    priv.mark_sensitive_notes(conn, vault)
    # Seed suggestion apontando pra nota sensivel
    sid = conn.execute(
        "SELECT id FROM notes WHERE path='00 - Pessoal/Journaling/diario-2026.md'"
    ).fetchone()[0]
    conn.execute(
        """
        INSERT INTO suggestions_cache
          (generated_at, expires_at, kind, target_note_ids, content, reasoning,
           score, dismissed, acted_on)
        VALUES (datetime('now'), datetime('now','+7 days'), 'review',
                ?, 'Revisar [[diario]]', 'Privado explicito', 0.5, 0, 0)
        """,
        (json.dumps([sid]),),
    )
    conn.commit()
    srv = _load("pulse_server_tests", _SERVER_PATH)
    from fastapi.testclient import TestClient
    app = srv.build_app(vault, token="T")
    client = TestClient(app)
    r = client.get("/api/suggestions", headers={"X-Pulse-Token": "T"})
    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 1
    # Default: redigido
    assert "diario" not in data["suggestions"][0]["content"]
    # Com show_sensitive=true, preservado
    r2 = client.get(
        "/api/suggestions?show_sensitive=true",
        headers={"X-Pulse-Token": "T"},
    )
    assert "diario" in r2.json()["suggestions"][0]["content"]
