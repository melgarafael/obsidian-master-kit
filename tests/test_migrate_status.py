"""Tests for skill obsidian-migrate, Wave 1 (status detection)."""
import json
import pathlib
import pytest
import sys
# Import migrate via path manipulation since it lives under skills/
_SKILL_SCRIPTS = pathlib.Path(__file__).parent.parent / "skills" / "obsidian-migrate" / "scripts"
sys.path.insert(0, str(_SKILL_SCRIPTS))
import migrate  # noqa: E402


def test_status_empty_dir(tmp_path):
    assert migrate.detect_state(tmp_path) == "empty"


def test_status_empty_dir_nonexistent(tmp_path):
    assert migrate.detect_state(tmp_path / "nao_existe") == "empty"


def test_status_existing_with_md(tmp_path):
    (tmp_path / "nota1.md").write_text("# hello\n")
    (tmp_path / "subpasta").mkdir()
    (tmp_path / "subpasta" / "nota2.md").write_text("# world\n")
    assert migrate.detect_state(tmp_path) == "existing"


def test_status_ignores_obsidian_hidden_dirs(tmp_path):
    (tmp_path / ".obsidian").mkdir()
    (tmp_path / ".obsidian" / "cfg.md").write_text("# cfg\n")
    (tmp_path / ".trash").mkdir()
    (tmp_path / ".trash" / "old.md").write_text("# old\n")
    assert migrate.detect_state(tmp_path) == "empty"


def test_status_ignores_templates_dir(tmp_path):
    (tmp_path / "_templates").mkdir()
    (tmp_path / "_templates" / "t.md").write_text("# template\n")
    assert migrate.detect_state(tmp_path) == "empty"


def test_status_already_migrated(tmp_path):
    (tmp_path / "nota1.md").write_text("# hello\n")
    (tmp_path / ".obsidian-master").mkdir()
    (tmp_path / ".obsidian-master" / "marker.json").write_text(
        json.dumps({"kit_version": "0.1.0", "migration_completed": False})
    )
    assert migrate.detect_state(tmp_path) == "already_migrated"


def test_cmd_status_already_migrated_exits_1(tmp_path, capsys):
    (tmp_path / "nota1.md").write_text("# hello\n")
    (tmp_path / ".obsidian-master").mkdir()
    (tmp_path / ".obsidian-master" / "marker.json").write_text(
        json.dumps({"kit_version": "0.1.0", "migration_completed": True})
    )
    code = migrate.main(["status", "--vault", str(tmp_path)])
    assert code == 1
    out = capsys.readouterr()
    assert "already_migrated" in out.out
    assert "obsidian-librarian" in out.err


def test_cmd_status_existing_exits_0(tmp_path, capsys):
    (tmp_path / "nota1.md").write_text("# hello\n")
    code = migrate.main(["status", "--vault", str(tmp_path)])
    assert code == 0
    out = capsys.readouterr().out
    assert "existing" in out
    assert "shadow-scan" in out


def test_cmd_status_empty_exits_0(tmp_path, capsys):
    code = migrate.main(["status", "--vault", str(tmp_path)])
    assert code == 0
    out = capsys.readouterr().out
    assert "empty" in out
    assert "obsidian-init" in out


def test_stub_subcommand_exits_2(tmp_path, capsys):
    """Subcommands ainda nao implementados retornam exit 2 com guidance."""
    code = migrate.main(["propose", "--vault", str(tmp_path)])
    assert code == 2
    err = capsys.readouterr().err
    assert "Wave 4" in err
