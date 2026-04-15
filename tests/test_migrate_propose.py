import json
import pathlib
import sys
import pytest
import numpy as np

_SKILL_SCRIPTS = pathlib.Path(__file__).parent.parent / "skills" / "obsidian-migrate" / "scripts"
sys.path.insert(0, str(_SKILL_SCRIPTS))
import migrate


class _ThemeEmbedder:
    model_name = "theme-test-v1"
    dim = 256
    def __init__(self, themes):
        self.themes = list(themes)
        rng = np.random.default_rng(42)
        self._base = {t: rng.normal(size=256).astype(np.float32) for t in themes}
        for k, v in self._base.items():
            v /= np.linalg.norm(v) + 1e-9
    def embed(self, texts):
        out = []
        for t in texts:
            vec = np.zeros(256, dtype=np.float32)
            for theme, base in self._base.items():
                if theme.lower() in t.lower():
                    noise = np.random.default_rng(hash(t) % 2**32).normal(size=256) * 0.05
                    vec = base + noise.astype(np.float32)
                    break
            vec = vec / (np.linalg.norm(vec) + 1e-9)
            out.append(vec.astype(np.float32))
        return np.asarray(out, dtype=np.float32)


def _prep_vault_clustered(tmp_path, themes, monkeypatch):
    """Cria vault com pastas tematicas + roda shadow-scan + cluster."""
    vault = tmp_path / "vault"
    vault.mkdir()
    for theme, n in themes.items():
        sub = vault / theme
        sub.mkdir()
        for i in range(n):
            (sub / f"{theme.lower()}-{i}.md").write_text(
                f"---\ntitle: {theme} nota {i}\n---\nconteudo sobre {theme} item {i}\n"
            )
    emb = _ThemeEmbedder(themes)
    from core import embeddings as ce
    monkeypatch.setattr(ce, "get_default_embedder", lambda: emb)
    migrate.main(["shadow-scan", "--vault", str(vault)])
    migrate.main(["cluster", "--vault", str(vault)])
    return vault


def test_propose_requires_clusters(tmp_path, capsys):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "x.md").write_text("# hi\n")
    code = migrate.main(["propose", "--vault", str(vault)])
    assert code == 1
    assert "shadow-scan" in capsys.readouterr().err


def test_propose_generates_proposal_md(tmp_path, monkeypatch):
    themes = {"Hermetismo": 12, "CRM": 10}
    vault = _prep_vault_clustered(tmp_path, themes, monkeypatch)
    code = migrate.main(["propose", "--vault", str(vault)])
    assert code == 0
    prop = vault / ".obsidian-master" / "migration-proposal.md"
    assert prop.exists()
    content = prop.read_text(encoding="utf-8")
    assert "## Mapeamento pasta" in content
    assert "## Preview do CLAUDE.md" in content
    assert "## Mapa de Areas" in content


def test_propose_persists_clear_areas(tmp_path, monkeypatch):
    themes = {"Hermetismo": 12, "CRM": 10}
    vault = _prep_vault_clustered(tmp_path, themes, monkeypatch)
    migrate.main(["propose", "--vault", str(vault)])
    import sqlite3
    conn = sqlite3.connect(str(vault / ".obsidian-master" / "db.sqlite"))
    slugs = {r[0] for r in conn.execute("SELECT slug FROM areas WHERE is_canonical=0").fetchall()}
    # Both themes should have single-cluster dominance >=60%
    assert "hermetismo" in slugs
    assert "crm" in slugs


def test_propose_is_idempotent(tmp_path, monkeypatch):
    themes = {"Hermetismo": 12, "CRM": 10}
    vault = _prep_vault_clustered(tmp_path, themes, monkeypatch)
    migrate.main(["propose", "--vault", str(vault)])
    # second run: areas still just 2 (no duplicates)
    migrate.main(["propose", "--vault", str(vault)])
    import sqlite3
    conn = sqlite3.connect(str(vault / ".obsidian-master" / "db.sqlite"))
    count = conn.execute("SELECT COUNT(*) FROM areas WHERE is_canonical=0").fetchone()[0]
    assert count == 2


def test_propose_never_writes_outside_obsidian_master(tmp_path, monkeypatch):
    """Garantia: propose NAO cria CLAUDE.md ou movimenta arquivo nesta etapa."""
    themes = {"Hermetismo": 12, "CRM": 10}
    vault = _prep_vault_clustered(tmp_path, themes, monkeypatch)
    # Snapshot arquivos fora de .obsidian-master antes
    before = {str(p.relative_to(vault)) for p in vault.rglob("*")
              if ".obsidian-master" not in p.parts and p.is_file()}
    migrate.main(["propose", "--vault", str(vault)])
    after = {str(p.relative_to(vault)) for p in vault.rglob("*")
             if ".obsidian-master" not in p.parts and p.is_file()}
    assert before == after, "propose modificou arquivos fora de .obsidian-master"


def test_slug_helper():
    from migrate import _slug
    assert _slug("01 - Profissional") == "profissional"
    assert _slug("00 - Pessoal") == "pessoal"
    assert _slug("Research & Dev") == "research-dev"
    assert _slug("A/B Testing") == "a-b-testing"
    assert _slug("   ") == "area"


def test_propose_lists_all_folders_including_ambiguous(tmp_path, monkeypatch):
    """Pasta ambigua (sem cluster dominante) aparece na tabela."""
    # Cria uma pasta onde as notas caem em 2 clusters misturados
    themes = {"Hermetismo": 8, "CRM": 7}
    vault = tmp_path / "vault"
    vault.mkdir()
    mista = vault / "Misturada"
    mista.mkdir()
    for i in range(8):
        (mista / f"hermetismo-mix-{i}.md").write_text("---\ntitle: Hermetismo MIX\n---\nconteudo hermetismo\n")
    for i in range(7):
        (mista / f"crm-mix-{i}.md").write_text("---\ntitle: CRM MIX\n---\nconteudo crm\n")
    emb = _ThemeEmbedder(themes)
    from core import embeddings as ce
    monkeypatch.setattr(ce, "get_default_embedder", lambda: emb)
    migrate.main(["shadow-scan", "--vault", str(vault)])
    migrate.main(["cluster", "--vault", str(vault)])
    code = migrate.main(["propose", "--vault", str(vault)])
    assert code == 0
    content = (vault / ".obsidian-master" / "migration-proposal.md").read_text(encoding="utf-8")
    assert "Misturada" in content
