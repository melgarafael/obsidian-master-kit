"""Testes da CLI `obsidian-expand` (Epic 05 S01 shell + S02/S03 wire-up).

Cobre: argparse, required args, vault resolution, envelope JSON real com
candidates, persist (--no-dry-run), filtros por topic/area/moc-path.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import sys

import numpy as np
import pytest

from core import cli as core_cli
from core.db import connect
from core.graph import update_graph_metrics
from core.scanner import scan

_SCRIPT_PATH = (
    pathlib.Path(__file__).resolve().parent.parent
    / "skills"
    / "obsidian-expand"
    / "scripts"
    / "expand.py"
)


def _load_expand():
    name = "expand_cli"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, _SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class _DeterministicEmbedder:
    """Seed-determinado, L2-normalized — vetores distintos por texto."""

    model_name = "fake-deterministic-cli-v1"
    dim = 256

    def embed(self, texts):
        out = []
        for txt in texts:
            rng = np.random.default_rng(hash(txt) & 0xFFFFFFFF)
            vec = rng.standard_normal(256).astype(np.float32)
            vec /= np.linalg.norm(vec) or 1.0
            out.append(vec)
        if not out:
            return np.zeros((0, 256), dtype=np.float32)
        return np.stack(out)


@pytest.fixture(scope="module")
def expand():
    return _load_expand()


@pytest.fixture
def initialized_vault(tmp_path):
    rc = core_cli.main(["init-db", "--vault", str(tmp_path)])
    assert rc == 0
    return tmp_path


@pytest.fixture
def populated_vault(tmp_path):
    """Vault pequeno com notas textualmente distintas + scan completo."""
    notas = [
        ("02 - Pesquisas e Estudos/hermetismo.md",
         "# Hermetismo\nTexto sobre hermetismo antigo e Tabua de Esmeralda."),
        ("02 - Pesquisas e Estudos/alquimia.md",
         "# Alquimia\nArte hermetica da transmutacao interior e opus magnum."),
        ("02 - Pesquisas e Estudos/cabala.md",
         "# Cabala\nSephirot, Arvore da Vida, tradicao judaica."),
        ("01 - Profissional/projeto-api.md",
         "# API\nArquitetura de microservicos com Go e gRPC."),
        ("01 - Profissional/_MOC.md",
         "---\ntype: moc\n---\n# MOC Profissional\n[[projeto-api]]"),
        ("00 - Pessoal/journal-1.md", "# Journal 1\nPensamentos do dia."),
        ("00 - Pessoal/journal-2.md", "# Journal 2\nOutros pensamentos."),
    ]
    for rel, body in notas:
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    core_cli.main(["init-db", "--vault", str(tmp_path)])
    conn = connect(tmp_path)
    # Seed canonical areas (migrate skill far isso em prod)
    for slug, label, folder in (
        ("pessoal", "Pessoal", "00 - Pessoal"),
        ("profissional", "Profissional", "01 - Profissional"),
        ("pesquisa", "Pesquisas", "02 - Pesquisas e Estudos"),
        ("ai-memory", "AI Memory", "03 - Memoria da IA"),
    ):
        conn.execute(
            "INSERT OR IGNORE INTO areas (slug, label, folder, is_canonical, created_at) "
            "VALUES (?, ?, ?, 1, datetime('now'))",
            (slug, label, folder),
        )
    conn.commit()
    scan(conn, tmp_path, embedder=_DeterministicEmbedder())
    update_graph_metrics(conn)
    return tmp_path, conn


def _run_and_parse(expand, argv, capsys):
    rc = expand.main(argv)
    out = capsys.readouterr().out
    return rc, json.loads(out)


# ---------- 1. argparse basico ----------


def test_help_exits_zero(expand, capsys):
    with pytest.raises(SystemExit) as exc:
        expand.main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "bridges" in out and "gaps" in out and "generate" in out


def test_without_subcommand_fails(expand):
    with pytest.raises(SystemExit) as exc:
        expand.main([])
    assert exc.value.code == 2


def test_moc_requires_moc_path(expand, initialized_vault):
    with pytest.raises(SystemExit) as exc:
        expand.main(["moc", "--vault", str(initialized_vault)])
    assert exc.value.code == 2


def test_from_requires_note(expand, initialized_vault):
    with pytest.raises(SystemExit) as exc:
        expand.main(["from", "--vault", str(initialized_vault)])
    assert exc.value.code == 2


def test_generate_requires_suggestion_id(expand, initialized_vault):
    with pytest.raises(SystemExit) as exc:
        expand.main(["generate", "--vault", str(initialized_vault)])
    assert exc.value.code == 2


# ---------- 2. envelope comum — todos os comandos ----------


def test_bridges_envelope_tem_campos_essenciais(expand, populated_vault, capsys):
    vault, _ = populated_vault
    rc, payload = _run_and_parse(
        expand, ["bridges", "--vault", str(vault)], capsys
    )
    assert rc == 0
    for key in ("command", "vault", "vec_index", "dry_run", "candidates", "count", "persisted"):
        assert key in payload, f"missing {key}"
    assert payload["command"] == "bridges"
    assert payload["dry_run"] is True
    assert payload["persisted"] == 0  # dry-run nao persiste
    assert isinstance(payload["candidates"], list)


def test_gaps_reporta_by_kind(expand, populated_vault, capsys):
    vault, _ = populated_vault
    rc, payload = _run_and_parse(
        expand, ["gaps", "--vault", str(vault)], capsys
    )
    assert rc == 0
    assert "by_kind" in payload
    assert isinstance(payload["by_kind"], dict)


def test_from_com_note_inexistente_reporta_err(expand, populated_vault, capsys):
    vault, _ = populated_vault
    rc, payload = _run_and_parse(
        expand,
        [
            "from",
            "--vault",
            str(vault),
            "--note",
            "inexistente.md",
        ],
        capsys,
    )
    assert rc == 0
    assert payload["neighbors"] == []
    assert "note_err" in payload


def test_from_com_note_valida_retorna_neighbors_com_cos(expand, populated_vault, capsys):
    vault, _ = populated_vault
    rc, payload = _run_and_parse(
        expand,
        [
            "from",
            "--vault",
            str(vault),
            "--note",
            "02 - Pesquisas e Estudos/hermetismo.md",
            "--k",
            "3",
        ],
        capsys,
    )
    assert rc == 0
    assert "seed_id" in payload
    assert len(payload["neighbors"]) <= 3
    # Todos os vizinhos devem trazer path + cos
    for n in payload["neighbors"]:
        assert "path" in n and "cos" in n and "distance" in n


def test_moc_com_path_inexistente_reporta(expand, populated_vault, capsys):
    vault, _ = populated_vault
    rc, payload = _run_and_parse(
        expand,
        ["moc", "--vault", str(vault), "--moc-path", "naoexiste/_MOC.md"],
        capsys,
    )
    assert rc == 0
    assert payload["candidates"] == []
    assert "nao encontrada" in payload.get("note", "")


def test_generate_stub_permanece_wave_4(expand, populated_vault, capsys):
    vault, _ = populated_vault
    rc, payload = _run_and_parse(
        expand,
        [
            "generate",
            "--vault",
            str(vault),
            "--suggestion-id",
            "42",
        ],
        capsys,
    )
    assert rc == 0
    assert payload["command"] == "generate"
    assert payload["suggestion_id"] == 42
    assert payload["written_path"] is None
    assert payload["wave_pending"] is True
    assert payload["planned_for_wave"] == 4


# ---------- 3. dry-run default / no-dry-run persiste ----------


def test_dry_run_default_true(expand, populated_vault, capsys):
    vault, _ = populated_vault
    rc, payload = _run_and_parse(
        expand, ["bridges", "--vault", str(vault)], capsys
    )
    assert rc == 0
    assert payload["dry_run"] is True
    assert payload["persisted"] == 0


def test_no_dry_run_persiste_em_suggestions_cache(expand, populated_vault, capsys):
    vault, conn = populated_vault
    # Forca threshold baixo pra garantir pelo menos 1 candidato
    rc, payload = _run_and_parse(
        expand,
        [
            "bridges",
            "--vault",
            str(vault),
            "--no-dry-run",
            "--min-cos",
            "-1.0",
        ],
        capsys,
    )
    assert rc == 0
    assert payload["dry_run"] is False
    # Com min_cos=-1.0, ha pelo menos um candidato (se vault tem >= 2 notas
    # ativas com embedding)
    if payload["count"] > 0:
        assert payload["persisted"] == payload["count"]
        db_count = conn.execute(
            "SELECT COUNT(*) FROM suggestions_cache WHERE kind='bridge'"
        ).fetchone()[0]
        assert db_count == payload["persisted"]


# ---------- 4. vault discovery ----------


def test_vault_sem_marker_falha_claramente(expand, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as exc:
        expand.main(["bridges"])
    msg = str(exc.value.code)
    assert "obsidian-master" in msg
    assert "--vault" in msg
