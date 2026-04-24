"""conftest.py — bootstrap de fixtures do forge."""
from pathlib import Path

FIX_ROOT = Path(__file__).parent / "fixtures" / "forge" / "projetos-fake"


def pytest_configure(config):
    """Bootstrap .git/HEAD para fixtures do forge antes de qualquer coleta."""
    for repo in ["repo-ativo-python", "repo-ativo-node", "repo-velho"]:
        git_dir = FIX_ROOT / repo / ".git"
        git_dir.mkdir(exist_ok=True)
        head = git_dir / "HEAD"
        if not head.exists():
            head.write_text("ref: refs/heads/main\n")
