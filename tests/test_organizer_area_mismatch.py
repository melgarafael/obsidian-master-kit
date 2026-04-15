"""Testes area_mismatch.py (Epic 04 S05 / Wave 5)."""
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
    / "skills" / "obsidian-organizer" / "scripts" / "area_mismatch.py"
)


def _load():
    name = "organizer_area_mismatch_tests"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, _PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


class _SimpleEmbedder:
    model_name = "fake-sm-v1"
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
def am():
    return _load()


@pytest.fixture
def vault_com_mismatches(tmp_path):
    """Notas com area divergente da pasta e alinhadas, mistura."""
    notas = [
        # Mismatch: nota em Pesquisas com area=pessoal
        ("02 - Pesquisas e Estudos/mismatch1.md",
         "---\narea: pessoal\ntype: nota\nstatus: ativo\n---\n# Mismatch1\n"),
        # Mismatch: nota em Pessoal com area=profissional
        ("00 - Pessoal/mismatch2.md",
         "---\narea: profissional\ntype: nota\nstatus: ativo\n---\n# Mismatch2\n"),
        # OK: area bate com pasta
        ("01 - Profissional/ok1.md",
         "---\narea: profissional\ntype: nota\nstatus: ativo\n---\n# OK1\n"),
        # Sem area no frontmatter — nao flaga
        ("01 - Profissional/sem-area.md",
         "---\ntype: nota\nstatus: ativo\n---\n# SemArea\n"),
        # Sem frontmatter — nao flaga
        ("01 - Profissional/sem-fm.md", "# SemFrontmatter\nsem nada"),
        # Pasta nao canonica — nao flaga (nao tem mapping)
        ("custom/custom1.md",
         "---\narea: pessoal\ntype: nota\nstatus: ativo\n---\n# CustomArea\n"),
    ]
    for rel, body in notas:
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    core_cli.main(["init-db", "--vault", str(tmp_path)])
    conn = connect(tmp_path)
    scan(conn, tmp_path, embedder=_SimpleEmbedder())
    return tmp_path, conn


def test_detect_mismatches_encontra_ambos(am, vault_com_mismatches):
    _, conn = vault_com_mismatches
    mismatches = am.detect_mismatches(conn)
    paths = {m["path"] for m in mismatches}
    assert "02 - Pesquisas e Estudos/mismatch1.md" in paths
    assert "00 - Pessoal/mismatch2.md" in paths


def test_detect_ignora_area_alinhada(am, vault_com_mismatches):
    _, conn = vault_com_mismatches
    mismatches = am.detect_mismatches(conn)
    paths = {m["path"] for m in mismatches}
    assert "01 - Profissional/ok1.md" not in paths


def test_detect_ignora_sem_area_no_frontmatter(am, vault_com_mismatches):
    _, conn = vault_com_mismatches
    mismatches = am.detect_mismatches(conn)
    paths = {m["path"] for m in mismatches}
    assert "01 - Profissional/sem-area.md" not in paths
    assert "01 - Profissional/sem-fm.md" not in paths


def test_detect_ignora_pasta_nao_canonica(am, vault_com_mismatches):
    _, conn = vault_com_mismatches
    mismatches = am.detect_mismatches(conn)
    paths = {m["path"] for m in mismatches}
    # 'custom/' nao esta no AREA_FOLDER_MAP — nao flaga
    assert "custom/custom1.md" not in paths


def test_detect_reasoning_tem_area_declarada_e_esperada(am, vault_com_mismatches):
    _, conn = vault_com_mismatches
    mismatches = am.detect_mismatches(conn)
    for m in mismatches:
        assert m["declared_area"] != m["expected_area"]
        assert m["declared_area"] in m["reasoning"]
        assert m["expected_area"] in m["reasoning"]


def test_save_suggestions_grava_kind_area_mismatch(am, vault_com_mismatches):
    _, conn = vault_com_mismatches
    mismatches = am.detect_mismatches(conn)
    n = am.save_suggestions(conn, mismatches)
    assert n == len(mismatches)
    rows = conn.execute(
        "SELECT kind, reasoning FROM suggestions_cache WHERE kind='area_mismatch'"
    ).fetchall()
    assert len(rows) == n
    for kind, reasoning in rows:
        assert kind == "area_mismatch"
        assert reasoning and "area" in reasoning.lower()


def test_save_dedup_nao_duplica_suggestion_ativa(am, vault_com_mismatches):
    _, conn = vault_com_mismatches
    mismatches = am.detect_mismatches(conn)
    am.save_suggestions(conn, mismatches)
    # Segunda invocacao nao re-insere
    n2 = am.save_suggestions(conn, mismatches)
    assert n2 == 0
