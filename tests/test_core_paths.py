"""Testes unitarios para core.paths (Epic 05 S01 / Wave 1)."""
from __future__ import annotations

import pathlib

import pytest

from core.paths import MARKER_REL, resolve_vault


def test_marker_rel_constant():
    assert MARKER_REL == ".obsidian-master/marker.json"


def test_resolve_com_vault_explicito_retorna_path_absoluto(tmp_path):
    # Nao precisa de marker quando --vault e explicito (permite bootstrap).
    result = resolve_vault(str(tmp_path))
    assert result == tmp_path.resolve()
    assert result.is_absolute()


def test_resolve_com_vault_expande_tilde(tmp_path, monkeypatch):
    # ~ deve expandir. HOME aponta pra tmp_path (path real sem symlinks),
    # o que evita `/tmp` -> `/private/tmp` em macOS.
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    result = resolve_vault("~/vault")
    assert result == (fake_home / "vault").resolve()
    assert result.is_absolute()


def test_resolve_sem_vault_encontra_marker_no_proprio_dir(tmp_path, monkeypatch):
    (tmp_path / ".obsidian-master").mkdir()
    (tmp_path / ".obsidian-master" / "marker.json").write_text("{}\n")
    monkeypatch.chdir(tmp_path)
    assert resolve_vault(None) == tmp_path.resolve()


def test_resolve_sem_vault_walk_ancestor(tmp_path, monkeypatch):
    # vault root em tmp_path, cwd em sub/sub/sub
    (tmp_path / ".obsidian-master").mkdir()
    (tmp_path / ".obsidian-master" / "marker.json").write_text("{}\n")
    nested = tmp_path / "a" / "b" / "c"
    nested.mkdir(parents=True)
    monkeypatch.chdir(nested)
    assert resolve_vault(None) == tmp_path.resolve()


def test_resolve_sem_vault_sem_marker_falha_com_mensagem_ptbr(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as exc:
        resolve_vault(None)
    msg = str(exc.value.code)
    assert "obsidian-master" in msg
    assert "--vault" in msg
