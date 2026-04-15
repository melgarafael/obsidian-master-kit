"""Testes para o shell da CLI `obsidian-expand` (Epic 05 S01 / Wave 1).

Wave 1 e shell: valida que argparse funciona, cada sub-comando roda ate
produzir envelope JSON com marcador `wave_pending=True`, vault discovery
funciona e mensagens de erro sao uteis. Logica real (KNN, gaps, generate)
vem nas waves seguintes.

Padrao seguido: importar `expand.main` via importlib (script nao e pacote
Python), chamar direto com argv explicito, capturar stdout via capsys.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib

import pytest

from core import cli as core_cli

_SCRIPT_PATH = (
    pathlib.Path(__file__).resolve().parent.parent
    / "skills"
    / "obsidian-expand"
    / "scripts"
    / "expand.py"
)


def _load_expand():
    spec = importlib.util.spec_from_file_location("expand_cli", _SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def expand():
    return _load_expand()


@pytest.fixture
def initialized_vault(tmp_path):
    """Vault com marker + DB via core.cli init-db — pronto pra expand."""
    rc = core_cli.main(["init-db", "--vault", str(tmp_path)])
    assert rc == 0
    return tmp_path


# ---------- 1. argparse basico ----------


def test_help_exits_zero(expand, capsys):
    with pytest.raises(SystemExit) as exc:
        expand.main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "bridges" in out
    assert "gaps" in out
    assert "generate" in out


def test_without_subcommand_fails(expand):
    # argparse com required=True em subparsers sai 2 sem sub-comando
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


# ---------- 2. sub-comandos de analise — envelope JSON estavel ----------


def _run_and_parse(expand, argv, capsys):
    rc = expand.main(argv)
    out = capsys.readouterr().out
    return rc, json.loads(out)


def test_bridges_stub_envelope(expand, initialized_vault, capsys):
    rc, payload = _run_and_parse(
        expand,
        ["bridges", "--vault", str(initialized_vault)],
        capsys,
    )
    assert rc == 0
    assert payload["command"] == "bridges"
    assert payload["vault"] == str(initialized_vault)
    assert payload["wave_pending"] is True
    assert payload["planned_for_wave"] == 3
    assert payload["candidates"] == []
    assert payload["topic"] is None
    assert payload["min_cos"] is None


def test_bridges_com_topic_e_min_cos(expand, initialized_vault, capsys):
    rc, payload = _run_and_parse(
        expand,
        [
            "bridges",
            "--vault",
            str(initialized_vault),
            "--topic",
            "hermetismo",
            "--min-cos",
            "0.25",
        ],
        capsys,
    )
    assert rc == 0
    assert payload["topic"] == "hermetismo"
    assert payload["min_cos"] == 0.25


def test_moc_stub_envelope(expand, initialized_vault, capsys):
    rc, payload = _run_and_parse(
        expand,
        [
            "moc",
            "--vault",
            str(initialized_vault),
            "--moc-path",
            "02 - Pesquisas/_MOC.md",
        ],
        capsys,
    )
    assert rc == 0
    assert payload["command"] == "moc"
    assert payload["moc_path"] == "02 - Pesquisas/_MOC.md"
    assert payload["planned_for_wave"] == 3


def test_gaps_stub_envelope(expand, initialized_vault, capsys):
    rc, payload = _run_and_parse(
        expand,
        ["gaps", "--vault", str(initialized_vault), "--area", "pesquisa"],
        capsys,
    )
    assert rc == 0
    assert payload["command"] == "gaps"
    assert payload["area"] == "pesquisa"
    assert payload["planned_for_wave"] == 3


def test_from_stub_envelope(expand, initialized_vault, capsys):
    rc, payload = _run_and_parse(
        expand,
        [
            "from",
            "--vault",
            str(initialized_vault),
            "--note",
            "02 - Pesquisas/hermetismo.md",
            "--k",
            "15",
        ],
        capsys,
    )
    assert rc == 0
    assert payload["command"] == "from"
    assert payload["note"] == "02 - Pesquisas/hermetismo.md"
    assert payload["k"] == 15


def test_generate_stub_envelope(expand, initialized_vault, capsys):
    rc, payload = _run_and_parse(
        expand,
        [
            "generate",
            "--vault",
            str(initialized_vault),
            "--suggestion-id",
            "42",
        ],
        capsys,
    )
    assert rc == 0
    assert payload["command"] == "generate"
    assert payload["suggestion_id"] == 42
    assert payload["written_path"] is None
    assert payload["planned_for_wave"] == 4


# ---------- 3. dry-run default e no-dry-run flag ----------


def test_dry_run_default_true(expand, initialized_vault, capsys):
    rc, payload = _run_and_parse(
        expand,
        ["bridges", "--vault", str(initialized_vault)],
        capsys,
    )
    assert rc == 0
    assert payload["dry_run"] is True


def test_no_dry_run_flag_desativa(expand, initialized_vault, capsys):
    rc, payload = _run_and_parse(
        expand,
        ["bridges", "--vault", str(initialized_vault), "--no-dry-run"],
        capsys,
    )
    assert rc == 0
    assert payload["dry_run"] is False


# ---------- 4. vault discovery: erro util sem marker ----------


def test_vault_sem_marker_falha_claramente(expand, tmp_path, monkeypatch):
    # tmp_path nao tem marker — mas passar --vault explicito aceita ainda assim.
    # O caminho de erro e quando nao ha --vault nem marker em ancestors.
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as exc:
        expand.main(["bridges"])
    # sys.exit("msg") resulta em code sendo a string msg (nao 1), mas nao-zero.
    assert exc.value.code != 0
    msg = str(exc.value.code)
    assert "obsidian-master" in msg
    assert "--vault" in msg


# ---------- 5. vec_index status reportado (ok ou fallback) ----------


def test_envelope_reporta_status_vec_index(expand, initialized_vault, capsys):
    rc, payload = _run_and_parse(
        expand,
        ["gaps", "--vault", str(initialized_vault)],
        capsys,
    )
    assert rc == 0
    assert payload["vec_index"] in ("ok", "fallback")
