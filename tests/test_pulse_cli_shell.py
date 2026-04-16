"""Shell da CLI obsidian-pulse (Epic 06 S01 / Wave 1)."""
from __future__ import annotations

import importlib.util
import json
import pathlib
import sys

import pytest

from core import cli as core_cli

_SCRIPT = (
    pathlib.Path(__file__).resolve().parent.parent
    / "skills" / "obsidian-pulse" / "scripts" / "pulse.py"
)


def _load():
    name = "pulse_cli"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, _SCRIPT)
    assert spec is not None and spec.loader is not None
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


@pytest.fixture(scope="module")
def pulse():
    return _load()


@pytest.fixture
def initialized_vault(tmp_path):
    assert core_cli.main(["init-db", "--vault", str(tmp_path)]) == 0
    return tmp_path


def _run(pulse, argv, capsys):
    rc = pulse.main(argv)
    out = capsys.readouterr().out
    return rc, json.loads(out)


def test_help(pulse, capsys):
    with pytest.raises(SystemExit) as exc:
        pulse.main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    for sub in ("refresh", "serve", "daemon", "status"):
        assert sub in out


def test_without_subcommand_fails(pulse):
    with pytest.raises(SystemExit) as exc:
        pulse.main([])
    assert exc.value.code == 2


def test_refresh_roda_stages(pulse, initialized_vault, capsys):
    rc, p = _run(pulse, ["refresh", "--vault", str(initialized_vault)], capsys)
    assert rc == 0
    assert p["command"] == "refresh"
    assert "stages" in p
    stage_labels = {s["stage"] for s in p["stages"]}
    assert {"fsrs", "anomaly", "ranking"}.issubset(stage_labels)
    assert p["total_duration_ms"] >= 0


# serve/daemon bloqueiam em uvicorn.run — nao testaveis via CLI direto.
# Cobertura via test_pulse_server.py usando build_app + TestClient.


def test_status_funcional_em_vault_vazio(pulse, initialized_vault, capsys):
    rc, p = _run(pulse, ["status", "--vault", str(initialized_vault)], capsys)
    assert rc == 0
    assert p["command"] == "status"
    assert p["notes_active"] == 0
    assert p["suggestions_pending"] == 0
    assert p["alerts_pending"] == 0
    assert p["last_scan"] is None


def test_vault_sem_marker_falha(pulse, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as exc:
        pulse.main(["status"])
    msg = str(exc.value.code)
    assert "obsidian-master" in msg
