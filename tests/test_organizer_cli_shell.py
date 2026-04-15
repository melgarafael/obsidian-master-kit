"""Shell da CLI `obsidian-organizer` (Epic 04 S01 / Wave 1)."""
from __future__ import annotations

import importlib.util
import json
import pathlib
import sys

import pytest

from core import cli as core_cli

_SCRIPT = (
    pathlib.Path(__file__).resolve().parent.parent
    / "skills" / "obsidian-organizer" / "scripts" / "organizer.py"
)


def _load():
    name = "organizer_cli"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def org():
    return _load()


@pytest.fixture
def initialized_vault(tmp_path):
    assert core_cli.main(["init-db", "--vault", str(tmp_path)]) == 0
    return tmp_path


def _run(org, argv, capsys):
    rc = org.main(argv)
    out = capsys.readouterr().out
    return rc, json.loads(out)


def test_help(org, capsys):
    with pytest.raises(SystemExit) as exc:
        org.main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    for sub in ("cluster", "duplicates", "moc-audit", "area-mismatch", "propose", "report"):
        assert sub in out


def test_without_subcommand_fails(org):
    with pytest.raises(SystemExit) as exc:
        org.main([])
    assert exc.value.code == 2


def test_cluster_vault_vazio_reporta_erro_util(org, initialized_vault, capsys):
    """Vault sem notas suficientes pra HDBSCAN: cmd retorna rc=1 com error."""
    rc, p = _run(org, ["cluster", "--vault", str(initialized_vault)], capsys)
    assert rc == 1
    assert p["command"] == "cluster"
    assert "error" in p
    assert p["note_count"] == 0


def test_cluster_latest_vazio_antes_de_run(org, initialized_vault, capsys):
    rc, p = _run(
        org, ["cluster", "--vault", str(initialized_vault), "--latest"], capsys
    )
    assert rc == 0
    assert p["latest"] is True
    assert p["clusters"] == []
    assert p["run_id"] is None


def test_duplicates_vault_vazio_retorna_zero_candidatos(org, initialized_vault, capsys):
    rc, p = _run(org, ["duplicates", "--vault", str(initialized_vault)], capsys)
    assert rc == 0
    assert p["command"] == "duplicates"
    assert p["candidates"] == []
    assert p["count"] == 0
    assert p["persisted"] == 0


def test_duplicates_min_cos_override(org, initialized_vault, capsys):
    rc, p = _run(
        org,
        ["duplicates", "--vault", str(initialized_vault), "--min-cos", "0.75"],
        capsys,
    )
    assert rc == 0
    assert p["min_cos"] == 0.75


def test_moc_audit_sem_clusters_retorna_vazio(org, initialized_vault, capsys):
    rc, p = _run(org, ["moc-audit", "--vault", str(initialized_vault)], capsys)
    assert rc == 0
    assert p["command"] == "moc-audit"
    assert p["missing_moc"] == []
    assert p["count"] == 0


def test_area_mismatch_stub(org, initialized_vault, capsys):
    rc, p = _run(org, ["area-mismatch", "--vault", str(initialized_vault)], capsys)
    assert rc == 0
    assert p["command"] == "area-mismatch"
    assert p["planned_for_wave"] == 5
    assert p["mismatches"] == []


def test_propose_stub(org, initialized_vault, capsys):
    rc, p = _run(org, ["propose", "--vault", str(initialized_vault)], capsys)
    assert rc == 0
    assert p["command"] == "propose"
    assert p["planned_for_wave"] == 6
    assert p["dry_run"] is True


def test_propose_no_dry_run_flag(org, initialized_vault, capsys):
    rc, p = _run(
        org, ["propose", "--vault", str(initialized_vault), "--no-dry-run"], capsys
    )
    assert rc == 0
    assert p["dry_run"] is False


def test_report_stub(org, initialized_vault, capsys):
    rc, p = _run(org, ["report", "--vault", str(initialized_vault)], capsys)
    assert rc == 0
    assert p["command"] == "report"


def test_vec_index_reportado(org, initialized_vault, capsys):
    rc, p = _run(org, ["cluster", "--vault", str(initialized_vault)], capsys)
    assert p["vec_index"] in ("ok", "fallback")


def test_vault_sem_marker_falha_claramente(org, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as exc:
        org.main(["cluster"])
    msg = str(exc.value.code)
    assert "obsidian-master" in msg
