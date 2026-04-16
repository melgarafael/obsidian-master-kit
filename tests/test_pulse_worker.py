"""Worker orchestrator tests (Epic 06 S02 / Wave 2)."""
from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

from core import cli as core_cli
from core.db import connect

_PATH = (
    pathlib.Path(__file__).resolve().parent.parent
    / "skills" / "obsidian-pulse" / "scripts" / "worker.py"
)


def _load():
    name = "pulse_worker_tests"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, _PATH)
    assert spec is not None and spec.loader is not None
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


@pytest.fixture(scope="module")
def worker():
    return _load()


def test_run_batch_vault_vazio_completa_sem_erro(worker, tmp_path):
    core_cli.main(["init-db", "--vault", str(tmp_path)])
    conn = connect(tmp_path)
    result = worker.run_batch_analytics(conn)
    assert "stages" in result
    labels = {s["stage"] for s in result["stages"]}
    assert labels == {"fsrs", "anomaly", "ranking"}
    for s in result["stages"]:
        assert s["duration_ms"] >= 0


def test_run_batch_idempotente(worker, tmp_path):
    core_cli.main(["init-db", "--vault", str(tmp_path)])
    conn = connect(tmp_path)
    r1 = worker.run_batch_analytics(conn)
    r2 = worker.run_batch_analytics(conn)
    # Segundo run nao deve disparar erro nem acumular sugestoes dedupaveis
    assert len(r1["stages"]) == len(r2["stages"])
    # FSRS no vault vazio cria 0 both times
    assert r1["stages"][0]["result"] == 0
    assert r2["stages"][0]["result"] == 0


def test_run_batch_total_duration_consistente(worker, tmp_path):
    core_cli.main(["init-db", "--vault", str(tmp_path)])
    conn = connect(tmp_path)
    result = worker.run_batch_analytics(conn)
    soma = sum(s["duration_ms"] for s in result["stages"])
    # Total dentro de 0.5ms de discrepancia por round-off
    assert abs(result["total_duration_ms"] - soma) < 1.0
