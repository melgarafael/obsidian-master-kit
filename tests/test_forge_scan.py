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


from scan_context import gerar_nota_atomica, gerar_contexto_agregado  # noqa: E402


def test_gerar_nota_atomica(tmp_path: Path, fixture_atualizar_mtime: None) -> None:
    vault = tmp_path / "vault"
    (vault / "04 - Negocio" / "contexto").mkdir(parents=True)
    gerar_nota_atomica(vault_root=vault, repo_info={
        "nome": "repo-ativo-python",
        "caminho": str(FIX / "repo-ativo-python"),
    })
    nota = vault / "04 - Negocio" / "contexto" / "repo-ativo-python.md"
    assert nota.exists()
    from frontmatter import read_frontmatter
    meta, body = read_frontmatter(nota)
    assert meta["tipo"] == "contexto_projeto"
    assert meta["nome"] == "repo-ativo-python"
    assert "python" in meta["stack"]
    assert "repo-ativo-python" in body


def test_gerar_contexto_agregado(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    (vault / "04 - Negocio" / "contexto").mkdir(parents=True)
    gerar_contexto_agregado(
        vault_root=vault,
        repos=[{"nome": "a", "caminho": "/x/a"}, {"nome": "b", "caminho": "/x/b"}],
        fontes=[{"tipo": "pasta", "caminho": "/x", "ultima_varredura": "2026-04-22T14:00"}],
    )
    nota = vault / "04 - Negocio" / "_contexto.md"
    assert nota.exists()
    from frontmatter import read_frontmatter
    meta, body = read_frontmatter(nota)
    assert meta["projetos_ativos"] == 2
    assert "a" in body and "b" in body


from scan_context import scan, init_config  # noqa: E402


def test_scan_end_to_end(tmp_path: Path, fixture_atualizar_mtime: None) -> None:
    vault = tmp_path / "vault"
    (vault / "04 - Negocio").mkdir(parents=True)
    init_config(vault_root=vault, pastas=[str(FIX)])
    result = scan(vault_root=vault, silent=True)
    assert result["projetos_ativos"] >= 2
    assert (vault / "04 - Negocio" / "_contexto.md").exists()


def test_init_config_grava(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    (vault / "04 - Negocio").mkdir(parents=True)
    init_config(vault_root=vault, pastas=["/a", "/b"])
    cfg = vault / "04 - Negocio" / "_config-scan.md"
    from frontmatter import read_frontmatter
    meta, _ = read_frontmatter(cfg)
    assert meta["pastas_observadas"] == ["/a", "/b"]
    assert meta["janela_ativo_dias"] == 30
