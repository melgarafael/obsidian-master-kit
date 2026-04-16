"""Recommendation ranking tests (Epic 06 S05 / Wave 5)."""
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
    / "skills" / "obsidian-pulse" / "scripts" / "ranking.py"
)


def _load():
    name = "pulse_ranking_tests"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, _PATH)
    assert spec is not None and spec.loader is not None
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


@pytest.fixture(scope="module")
def rk():
    return _load()


def _seed_suggestion(conn, kind, score, *, target_ids=None, dismissed=False):
    now = _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0)
    exp = now + _dt.timedelta(days=7)
    conn.execute(
        """
        INSERT INTO suggestions_cache
          (generated_at, expires_at, kind, target_note_ids, content, reasoning,
           score, dismissed, dismissed_at, acted_on)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
        """,
        (
            now.isoformat(),
            exp.isoformat(),
            kind,
            json.dumps(target_ids or [1]),
            "c",
            "r",
            score,
            1 if dismissed else 0,
            now.isoformat() if dismissed else None,
        ),
    )
    conn.commit()


@pytest.fixture
def populated_cache(tmp_path):
    core_cli.main(["init-db", "--vault", str(tmp_path)])
    conn = connect(tmp_path)
    _seed_suggestion(conn, "review", 0.9)
    _seed_suggestion(conn, "bridge", 0.8)
    _seed_suggestion(conn, "moc_missing", 0.7)
    return conn


def test_rank_ordena_por_score_ajustado(rk, populated_cache):
    ranked = rk.rank(populated_cache)
    assert len(ranked) == 3
    # Scores em ordem decrescente
    for i in range(1, len(ranked)):
        assert ranked[i - 1]["score"] >= ranked[i]["score"]


def test_rank_aplica_peso_por_kind(rk, populated_cache):
    ranked = rk.rank(populated_cache)
    by_id = {r["kind"]: r for r in ranked}
    # review tem peso 0.35, bridge 0.25 — mesmo com base_score diferente,
    # review (0.9*0.35) = 0.315 vs bridge (0.8*0.25) = 0.20. review primeiro.
    review = by_id["review"]
    bridge = by_id["bridge"]
    assert review["score"] > bridge["score"]


def test_rank_same_kind_decay(rk, tmp_path):
    core_cli.main(["init-db", "--vault", str(tmp_path)])
    conn = connect(tmp_path)
    # 4 sugestoes do mesmo kind
    for _ in range(4):
        _seed_suggestion(conn, "bridge", 0.8)
    ranked = rk.rank(conn)
    scores = [r["score"] for r in ranked]
    # Primeiro tem decay 1.0, segundo 0.7, terceiro 0.4, quarto 0.1 — ordem DESC
    assert scores[0] > scores[1] > scores[2] > scores[3]


def test_select_top_respeita_limit(rk, populated_cache):
    top2 = rk.select_top(populated_cache, limit=2)
    assert len(top2) == 2


def test_select_top_exclui_dismissed(rk, tmp_path):
    core_cli.main(["init-db", "--vault", str(tmp_path)])
    conn = connect(tmp_path)
    _seed_suggestion(conn, "review", 0.9)
    _seed_suggestion(conn, "bridge", 0.8, dismissed=True)
    ranked = rk.rank(conn)
    kinds = [r["kind"] for r in ranked]
    assert "bridge" not in kinds
    assert "review" in kinds


def test_vault_vazio_retorna_lista_vazia(rk, tmp_path):
    core_cli.main(["init-db", "--vault", str(tmp_path)])
    conn = connect(tmp_path)
    assert rk.rank(conn) == []
    assert rk.select_top(conn) == []
