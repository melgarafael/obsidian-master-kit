"""Testes do scanner."""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

FORGE_DIR = Path(__file__).parent.parent / "skills" / "obsidian-forge" / "scripts"
sys.path.insert(0, str(FORGE_DIR))

from scan_context import detectar_repos, detectar_stack, ler_readme_resumo  # noqa: E402

FIX = Path(__file__).parent / "fixtures" / "forge" / "projetos-fake"


@pytest.fixture
def fixture_atualizar_mtime() -> None:
    agora = time.time()
    velho = agora - (60 * 86400)
    for r in [FIX / "repo-ativo-python", FIX / "repo-ativo-node"]:
        for f in r.rglob("*"):
            if f.is_file() and ".git" not in f.parts:
                os.utime(f, (agora, agora))
    for f in (FIX / "repo-velho").rglob("*"):
        if f.is_file() and ".git" not in f.parts:
            os.utime(f, (velho, velho))


def test_detectar_repos_filtra_mtime(fixture_atualizar_mtime: None) -> None:
    repos = detectar_repos(pastas=[FIX], janela_ativo_dias=30, limite_profundidade=3, ignore=[])
    nomes = {r["nome"] for r in repos}
    assert "repo-ativo-python" in nomes
    assert "repo-ativo-node" in nomes
    assert "repo-velho" not in nomes


def test_detectar_repos_profundidade(tmp_path: Path) -> None:
    deep = tmp_path / "a" / "b" / "c" / "d" / "repo-deep"
    (deep / ".git").mkdir(parents=True)
    (deep / "README.md").write_text("# d")
    (deep / ".git" / "HEAD").write_text("ref:")
    repos = detectar_repos(pastas=[tmp_path], janela_ativo_dias=999,
                           limite_profundidade=3, ignore=[])
    assert not any(r["nome"] == "repo-deep" for r in repos)


def test_detectar_repos_ignore(tmp_path: Path) -> None:
    (tmp_path / "node_modules" / "algo" / ".git").mkdir(parents=True)
    (tmp_path / "node_modules" / "algo" / ".git" / "HEAD").write_text("ref:")
    repos = detectar_repos(pastas=[tmp_path], janela_ativo_dias=999,
                           limite_profundidade=5, ignore=["node_modules"])
    assert repos == []


def test_detectar_stack_python() -> None:
    assert "python" in detectar_stack(FIX / "repo-ativo-python")


def test_detectar_stack_node() -> None:
    assert "node" in detectar_stack(FIX / "repo-ativo-node")


def test_readme_resumo() -> None:
    t = ler_readme_resumo(FIX / "repo-ativo-python")
    assert t is not None
    assert len(t) <= 500
    assert "repo-ativo-python" in t


def test_readme_ausente(tmp_path: Path) -> None:
    assert ler_readme_resumo(tmp_path) is None
