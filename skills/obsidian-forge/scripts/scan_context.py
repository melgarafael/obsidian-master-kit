"""Scanner de contexto — detecta projetos ativos + gera notas atomicas."""
from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Any


def detectar_repos(*, pastas: list[Path], janela_ativo_dias: int,
                   limite_profundidade: int, ignore: list[str]) -> list[dict[str, Any]]:
    repos: list[dict[str, Any]] = []
    agora = time.time()
    janela_commit = janela_ativo_dias * 86400
    janela_file = 7 * 86400

    for pasta in pastas:
        pasta = Path(pasta).resolve()
        if not pasta.exists():
            continue
        for git_dir in _walk_git_dirs(pasta, limite_profundidade, ignore):
            repo_path = git_dir.parent
            if _ativo(repo_path, agora, janela_commit, janela_file):
                repos.append({"nome": repo_path.name, "caminho": str(repo_path)})
    return repos[:30]


def _walk_git_dirs(root: Path, max_depth: int, ignore: list[str]):
    def rec(path: Path, depth: int):
        if depth > max_depth:
            return
        if path.name in ignore:
            return
        try:
            for child in path.iterdir():
                if not child.is_dir():
                    continue
                if child.name == ".git":
                    yield child
                    return
                if child.name.startswith("."):
                    continue
                if child.name in ignore:
                    continue
                yield from rec(child, depth + 1)
        except (PermissionError, OSError):
            return
    yield from rec(root, 0)


def _ativo(repo_path: Path, agora: float, janela_commit: float, janela_file: float) -> bool:
    ts = _ultimo_commit_ts(repo_path)
    if ts and (agora - ts) <= janela_commit:
        return True
    for f in repo_path.rglob("*"):
        if not f.is_file() or ".git" in f.parts:
            continue
        try:
            if (agora - f.stat().st_mtime) <= janela_file:
                return True
        except OSError:
            continue
    return False


def _ultimo_commit_ts(repo_path: Path) -> float | None:
    try:
        # Verify git resolves to the local .git, not a parent repo
        check = subprocess.run(
            ["git", "-C", str(repo_path), "rev-parse", "--git-dir"],
            capture_output=True, text=True, timeout=2,
        )
        if check.returncode != 0:
            return None
        git_dir = (repo_path / check.stdout.strip()).resolve()
        if git_dir != (repo_path / ".git").resolve():
            return None

        out = subprocess.run(
            ["git", "-C", str(repo_path), "log", "-1", "--format=%ct"],
            capture_output=True, text=True, timeout=2,
        )
        if out.returncode == 0 and out.stdout.strip():
            return float(out.stdout.strip())
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


def detectar_stack(repo_path: Path) -> list[str]:
    s: list[str] = []
    if (repo_path / "pyproject.toml").exists() or (repo_path / "requirements.txt").exists():
        s.append("python")
    if (repo_path / "package.json").exists():
        s.append("node")
    if (repo_path / "Cargo.toml").exists():
        s.append("rust")
    if (repo_path / "go.mod").exists():
        s.append("go")
    return s


def ler_readme_resumo(repo_path: Path, max_chars: int = 500) -> str | None:
    for nome in ("README.md", "readme.md", "Readme.md"):
        p = repo_path / nome
        if p.exists():
            try:
                return p.read_text(encoding="utf-8")[:max_chars]
            except OSError:
                return None
    return None
