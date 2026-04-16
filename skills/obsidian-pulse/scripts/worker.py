"""worker.py — Stage B batch analytics (Epic 06 S02 / Wave 2).

Orquestra:
1. FSRS scheduler  -> review suggestions
2. Anomaly detect  -> alerts (streak/abandoned/keyword)
3. Ranking refresh -> select_top registra suggestion_shown

run_batch_analytics(conn) e idempotente: rodar 2x seguidos nao duplica
(dedup esta nos modulos). Log estruturado por stage com duracao.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sqlite3
import sys
import time
from typing import Any

__all__ = ["run_batch_analytics"]


_BASE = pathlib.Path(__file__).parent
_FSRS_PATH = _BASE / "fsrs_scheduler.py"
_ANOMALY_PATH = _BASE / "anomaly.py"
_RANKING_PATH = _BASE / "ranking.py"


def _load(name: str, path: pathlib.Path):
    existing = sys.modules.get(name)
    if existing is not None:
        return existing
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


def _time_stage(label: str, fn):
    t0 = time.perf_counter()
    result = fn()
    dt = time.perf_counter() - t0
    return {"stage": label, "duration_ms": round(dt * 1000, 1), "result": result}


def run_batch_analytics(conn: sqlite3.Connection) -> dict[str, Any]:
    """Roda todos os stages. Retorna dict com stages[] e totals."""
    fsrs = _load("_pulse_fsrs", _FSRS_PATH)
    anomaly = _load("_pulse_anomaly", _ANOMALY_PATH)
    ranking = _load("_pulse_ranking", _RANKING_PATH)

    stages: list[dict[str, Any]] = []

    # Stage 1: FSRS review suggestions
    stages.append(_time_stage(
        "fsrs",
        lambda: fsrs.create_review_suggestions(conn),
    ))

    # Stage 2: anomaly detection + save alerts
    def _anomaly_stage():
        detected = anomaly.detect_anomalies(conn)
        saved = anomaly.save_alerts(conn, detected)
        return {"detected": len(detected), "saved": saved}

    stages.append(_time_stage("anomaly", _anomaly_stage))

    # Stage 3: ranking + suggestion_shown registration
    def _ranking_stage():
        top = ranking.select_top(conn, limit=10)
        return {"top_count": len(top)}

    stages.append(_time_stage("ranking", _ranking_stage))

    total_ms = sum(s["duration_ms"] for s in stages)
    return {
        "stages": stages,
        "total_duration_ms": round(total_ms, 1),
    }
