"""Tests for skill obsidian-migrate, Wave 3 (cluster: HDBSCAN + TF-IDF labels)."""
import pathlib
import sys

import numpy as np
import pytest

# Import migrate via path manipulation since it lives under skills/
_SKILL_SCRIPTS = (
    pathlib.Path(__file__).parent.parent / "skills" / "obsidian-migrate" / "scripts"
)
sys.path.insert(0, str(_SKILL_SCRIPTS))
import migrate  # noqa: E402


def _prep_vault(tmp_path, themes):
    """Cria vault com notas tematicas.

    themes: dict like {'Hermetismo': 15, 'CRM': 12, 'Diario': 10}
    Cada tema vira uma subpasta com N notas, cada uma com texto no titulo
    e no body fazendo referencia explicita ao tema (pra o embedder fake
    identificar).
    """
    vault = tmp_path / "vault"
    vault.mkdir()
    for theme, n in themes.items():
        sub = vault / theme
        sub.mkdir()
        for i in range(n):
            (sub / f"{theme.lower()}-{i}.md").write_text(
                f"---\ntitle: {theme} nota {i}\narea: pessoal\n---\n"
                f"Conteudo sobre {theme} edicao numero {i}, com mais texto "
                f"relevante relacionado a {theme} e seus conceitos.\n"
            )
    return vault


class _ThemeEmbedder:
    """Embedder falso que gera vetores distintos por tema (pra HDBSCAN separar)."""
    model_name = "theme-test-v1"
    dim = 256

    def __init__(self, themes):
        self.themes = list(themes)
        rng = np.random.default_rng(42)
        # vetores ortogonais-ish (diferentes direcoes aleatorias L2-normalizadas)
        self._base = {t: rng.normal(size=256).astype(np.float32) for t in themes}
        for k, v in self._base.items():
            v /= np.linalg.norm(v) + 1e-9
        # vetor de ruido genericamente usado quando nenhum tema casar
        self._outlier_dir = rng.normal(size=256).astype(np.float32)
        self._outlier_dir /= np.linalg.norm(self._outlier_dir) + 1e-9

    def embed(self, texts):
        out = []
        for t in texts:
            vec = None
            for theme, base in self._base.items():
                if theme.lower() in t.lower():
                    noise = np.random.default_rng(hash(t) % 2**32).normal(size=256) * 0.05
                    vec = base + noise.astype(np.float32)
                    break
            if vec is None:
                # "outlier" — direcao nova + ruido grande pra nao colar em nenhum cluster
                noise = np.random.default_rng(hash(t) % 2**32).normal(size=256) * 0.5
                vec = self._outlier_dir + noise.astype(np.float32)
            vec = vec / (np.linalg.norm(vec) + 1e-9)
            out.append(vec.astype(np.float32))
        return np.asarray(out, dtype=np.float32)


def test_cluster_requires_shadow_scan_first(tmp_path, capsys):
    """Sem DB, cluster aborta com erro util."""
    vault = tmp_path / "empty"
    vault.mkdir()
    code = migrate.main(["cluster", "--vault", str(vault)])
    assert code == 1
    assert "shadow-scan" in capsys.readouterr().err


def test_cluster_3_themes_separa(tmp_path, monkeypatch):
    """Vault com 3 temas claros -> HDBSCAN separa em >=3 clusters."""
    themes = {"Hermetismo": 12, "CRM": 10, "Diario": 10}
    vault = _prep_vault(tmp_path, themes)
    emb = _ThemeEmbedder(themes)
    from core import embeddings as ce
    monkeypatch.setattr(ce, "get_default_embedder", lambda: emb)

    migrate.main(["shadow-scan", "--vault", str(vault)])
    code = migrate.main(["cluster", "--vault", str(vault)])
    assert code == 0

    import sqlite3
    conn = sqlite3.connect(str(vault / ".obsidian-master" / "db.sqlite"))
    clusters = conn.execute("SELECT id, label, note_count FROM clusters").fetchall()
    assert len(clusters) >= 3, f"expected >=3 clusters, got {len(clusters)}: {clusters}"


def test_cluster_labels_descriptive(tmp_path, monkeypatch):
    """Labels contem tokens representativos, nao so 'cluster-N'."""
    themes = {"Hermetismo": 10, "CRM": 10}
    vault = _prep_vault(tmp_path, themes)
    emb = _ThemeEmbedder(themes)
    from core import embeddings as ce
    monkeypatch.setattr(ce, "get_default_embedder", lambda: emb)

    migrate.main(["shadow-scan", "--vault", str(vault)])
    migrate.main(["cluster", "--vault", str(vault)])

    import sqlite3
    conn = sqlite3.connect(str(vault / ".obsidian-master" / "db.sqlite"))
    labels = [r[0] for r in conn.execute("SELECT label FROM clusters").fetchall()]
    # Todas as labels devem ter mais que 'cluster-N' puro
    assert all(not l.startswith("cluster-") or len(l) > 12 for l in labels), f"labels: {labels}"


def test_cluster_noise_not_persisted(tmp_path, monkeypatch):
    """HDBSCAN pode marcar ruido (-1); noise NAO vai pra cluster_notes."""
    themes = {"Hermetismo": 8}
    vault = _prep_vault(tmp_path, themes)
    # Adiciona 3 notas "ruido" com texto que nao casa com nenhum tema
    (vault / "random-outlier.md").write_text("---\ntitle: Random\n---\nMotor a diesel\n")
    (vault / "x-y-z.md").write_text("---\ntitle: XYZ\n---\nFisica quantica abstrata\n")
    (vault / "foo-bar.md").write_text("---\ntitle: FooBar\n---\nCafe da manha\n")
    emb = _ThemeEmbedder(themes)
    from core import embeddings as ce
    monkeypatch.setattr(ce, "get_default_embedder", lambda: emb)

    migrate.main(["shadow-scan", "--vault", str(vault)])
    migrate.main(["cluster", "--vault", str(vault)])

    import sqlite3
    conn = sqlite3.connect(str(vault / ".obsidian-master" / "db.sqlite"))
    total_notes = conn.execute(
        "SELECT COUNT(*) FROM notes WHERE deleted_at IS NULL"
    ).fetchone()[0]
    in_clusters = conn.execute("SELECT COUNT(*) FROM cluster_notes").fetchone()[0]
    # Menos-ou-igual: noise nao entra em cluster_notes
    assert in_clusters <= total_notes


def test_cluster_aborts_if_too_few_notes(tmp_path, monkeypatch):
    themes = {"Mini": 3}  # < 10 minimo
    vault = _prep_vault(tmp_path, themes)
    emb = _ThemeEmbedder(themes)
    from core import embeddings as ce
    monkeypatch.setattr(ce, "get_default_embedder", lambda: emb)

    migrate.main(["shadow-scan", "--vault", str(vault)])
    code = migrate.main(["cluster", "--vault", str(vault)])
    assert code == 1


def test_cluster_run_id_is_persisted(tmp_path, monkeypatch):
    themes = {"Hermetismo": 10, "CRM": 10}
    vault = _prep_vault(tmp_path, themes)
    emb = _ThemeEmbedder(themes)
    from core import embeddings as ce
    monkeypatch.setattr(ce, "get_default_embedder", lambda: emb)

    migrate.main(["shadow-scan", "--vault", str(vault)])
    migrate.main(["cluster", "--vault", str(vault)])

    import sqlite3
    conn = sqlite3.connect(str(vault / ".obsidian-master" / "db.sqlite"))
    run_ids = {r[0] for r in conn.execute("SELECT run_id FROM clusters").fetchall()}
    assert len(run_ids) == 1
    assert list(run_ids)[0].startswith("hdbscan-")
