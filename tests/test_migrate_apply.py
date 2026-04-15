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


def _full_e2e_setup(tmp_path, monkeypatch):
    """Scaffold + shadow-scan + cluster + propose + plan + approve batch 1."""
    vault = tmp_path / "vault"
    vault.mkdir()
    for theme in ["hermetismo", "crm"]:
        sub = vault / f"old-{theme}"
        sub.mkdir()
        for i in range(8):
            (sub / f"{theme}-{i}.md").write_text(
                f"---\ntitle: {theme.capitalize()} nota {i}\n---\n"
                f"conteudo sobre {theme} item {i}. Linka [[{theme}-{(i+1)%8}]].\n"
            )
    emb = _ThemeEmbedder(["hermetismo", "crm"])
    from core import embeddings as ce
    monkeypatch.setattr(ce, "get_default_embedder", lambda: emb)
    migrate.main(["shadow-scan", "--vault", str(vault)])
    migrate.main(["cluster", "--vault", str(vault)])
    migrate.main(["propose", "--vault", str(vault)])
    # Edit proposal: map old-hermetismo -> hermetismo, old-crm -> crm
    prop = vault / ".obsidian-master" / "migration-proposal.md"
    content = prop.read_text(encoding="utf-8")
    content = content.replace("`old-hermetismo`", "`hermetismo`")
    content = content.replace("`old-crm`", "`crm`")
    prop.write_text(content, encoding="utf-8")
    migrate.main(["plan", "--vault", str(vault)])
    # Approve all
    inputs = iter(["y", "y"])
    monkeypatch.setattr("builtins.input", lambda _=None: next(inputs))
    migrate.main(["approve", "--vault", str(vault), "--batch", "all"])
    return vault


def test_apply_moves_files_and_updates_db(tmp_path, monkeypatch):
    vault = _full_e2e_setup(tmp_path, monkeypatch)
    code = migrate.main(["apply", "--vault", str(vault), "--batch", "1"])
    assert code == 0
    # Files moved
    assert not (vault / "old-hermetismo").exists() or not any((vault / "old-hermetismo").iterdir())
    # New folder has the notes
    assert (vault / "hermetismo").exists() or (vault / "crm").exists()
    # DB updated
    import sqlite3
    conn = sqlite3.connect(str(vault / ".obsidian-master" / "db.sqlite"))
    applied = conn.execute(
        "SELECT COUNT(*) FROM migration_plan WHERE status='applied'"
    ).fetchone()[0]
    assert applied > 0
    # Event emitted
    moved = conn.execute(
        "SELECT COUNT(*) FROM events WHERE event_type='note_moved'"
    ).fetchone()[0]
    assert moved > 0


def test_apply_all_creates_marker_completed(tmp_path, monkeypatch):
    vault = _full_e2e_setup(tmp_path, monkeypatch)
    migrate.main(["apply", "--vault", str(vault), "--batch", "all"])
    marker = vault / ".obsidian-master" / "marker.json"
    assert marker.exists()
    data = json.loads(marker.read_text(encoding="utf-8"))
    assert data["migration_completed"] is True


def _multi_batch_setup(tmp_path, monkeypatch):
    """Vault com 2+ batches de notas aprovadas (>=25 hermetismo + 10 crm pra
    HDBSCAN ter contraste entre clusters)."""
    vault = tmp_path / "vault"; vault.mkdir()
    h = vault / "old-hermetismo"; h.mkdir()
    for i in range(25):
        (h / f"hermetismo-{i}.md").write_text(
            f"---\ntitle: Hermetismo {i}\n---\nconteudo hermetismo {i}\n"
        )
    c = vault / "old-crm"; c.mkdir()
    for i in range(10):
        (c / f"crm-{i}.md").write_text(f"---\ntitle: CRM {i}\n---\npipeline crm {i}\n")
    emb = _ThemeEmbedder(["hermetismo", "crm"])
    from core import embeddings as ce
    monkeypatch.setattr(ce, "get_default_embedder", lambda: emb)
    migrate.main(["shadow-scan", "--vault", str(vault)])
    migrate.main(["cluster", "--vault", str(vault)])
    migrate.main(["propose", "--vault", str(vault)])
    prop = vault / ".obsidian-master" / "migration-proposal.md"
    content = prop.read_text(encoding="utf-8")
    content = content.replace("`old-hermetismo`", "`hermetismo`")
    content = content.replace("`old-crm`", "`crm`")
    prop.write_text(content, encoding="utf-8")
    migrate.main(["plan", "--vault", str(vault)])
    inputs = iter(["y", "y"])
    monkeypatch.setattr("builtins.input", lambda _=None: next(inputs))
    migrate.main(["approve", "--vault", str(vault), "--batch", "all"])
    return vault


def test_apply_single_batch_does_not_mark_completed(tmp_path, monkeypatch):
    """Com multi-batch, apply de 1 batch SO nao deve marcar completed."""
    vault = _multi_batch_setup(tmp_path, monkeypatch)
    migrate.main(["apply", "--vault", str(vault), "--batch", "1"])
    marker = vault / ".obsidian-master" / "marker.json"
    if marker.exists():
        data = json.loads(marker.read_text(encoding="utf-8"))
        assert data.get("migration_completed") is not True


def test_apply_enforces_batch_order(tmp_path, monkeypatch):
    """Aplicar batch 2 antes do 1 deve falhar."""
    vault = _multi_batch_setup(tmp_path, monkeypatch)
    code = migrate.main(["apply", "--vault", str(vault), "--batch", "2"])
    assert code == 1


def test_rollback_restores_files(tmp_path, monkeypatch):
    vault = _full_e2e_setup(tmp_path, monkeypatch)
    migrate.main(["apply", "--vault", str(vault), "--batch", "1"])
    # Rollback
    code = migrate.main(["rollback", "--vault", str(vault), "--batch", "1"])
    assert code == 0
    # Files back in old folders
    assert (vault / "old-hermetismo").exists()
    # DB reflects rollback
    import sqlite3
    conn = sqlite3.connect(str(vault / ".obsidian-master" / "db.sqlite"))
    rolled_back = conn.execute(
        "SELECT COUNT(*) FROM migration_plan WHERE status='rolled_back'"
    ).fetchone()[0]
    assert rolled_back > 0


def test_rollback_unsets_marker_completed(tmp_path, monkeypatch):
    vault = _full_e2e_setup(tmp_path, monkeypatch)
    migrate.main(["apply", "--vault", str(vault), "--batch", "all"])
    marker_pre = json.loads((vault / ".obsidian-master" / "marker.json").read_text(encoding="utf-8"))
    assert marker_pre["migration_completed"] is True
    migrate.main(["rollback", "--vault", str(vault), "--batch", "1"])
    marker_post = json.loads((vault / ".obsidian-master" / "marker.json").read_text(encoding="utf-8"))
    assert marker_post["migration_completed"] is False


def test_wikilinks_refactored_on_move(tmp_path, monkeypatch):
    """Testa refactor de wikilinks path-based.

    Cria vault onde nota-A em pasta-X usa [[pasta-X/nota-B]] (path-based).
    Apos migrate para area 'alvo', o link deve ser reescrito pra [[alvo/nota-B]].
    """
    vault = tmp_path / "vault"
    vault.mkdir()
    src = vault / "old-hermetismo"
    src.mkdir()
    (src / "nota-A.md").write_text(
        "---\ntitle: A\n---\nLinka [[old-hermetismo/nota-B]] path-based.\n"
    )
    (src / "nota-B.md").write_text("---\ntitle: B\n---\nConteudo.\n")
    # Embed + cluster
    emb = _ThemeEmbedder(["hermetismo", "crm"])
    # Precisa de mais notas pra clustering — cria mais, e inclui uma segunda pasta
    # com outro tema pra HDBSCAN ter contraste (min_cluster_size=5 precisa de densidade
    # relativa entre clusters — sem contraste, todas as 12 viram noise)
    for i in range(10):
        (src / f"hermetismo-{i}.md").write_text(f"---\ntitle: H{i}\n---\nhermetismo texto\n")
    crm_sub = vault / "old-crm"; crm_sub.mkdir()
    for i in range(8):
        (crm_sub / f"crm-{i}.md").write_text(f"---\ntitle: CRM {i}\n---\npipeline crm funnel\n")
    from core import embeddings as ce
    monkeypatch.setattr(ce, "get_default_embedder", lambda: emb)
    migrate.main(["shadow-scan", "--vault", str(vault)])
    migrate.main(["cluster", "--vault", str(vault)])
    migrate.main(["propose", "--vault", str(vault)])
    # Inject slug for old-hermetismo
    prop = vault / ".obsidian-master" / "migration-proposal.md"
    content = prop.read_text(encoding="utf-8")
    content = content.replace("`old-hermetismo`", "`alvo`")
    prop.write_text(content, encoding="utf-8")
    migrate.main(["plan", "--vault", str(vault)])
    inputs = iter(["y", "y"])
    monkeypatch.setattr("builtins.input", lambda _=None: next(inputs))
    migrate.main(["approve", "--vault", str(vault), "--batch", "all"])
    migrate.main(["apply", "--vault", str(vault), "--batch", "all"])
    # Check nota-A now linka [[alvo/nota-B]]
    new_a = vault / "alvo" / "nota-A.md"
    assert new_a.exists()
    body = new_a.read_text(encoding="utf-8")
    assert "[[alvo/nota-B]]" in body
    assert "[[old-hermetismo/nota-B]]" not in body


def test_migration_002_adds_note_moved_event(tmp_path):
    """Schema migration 002: events.event_type agora aceita 'note_moved'."""
    from core.db import connect
    conn = connect(tmp_path)
    # Try inserting a note_moved event; should succeed
    conn.execute(
        "INSERT INTO events(event_type, ts, date) VALUES ('note_moved', '2026-04-15T10:00:00', '2026-04-15')"
    )
    conn.commit()
    rows = conn.execute(
        "SELECT COUNT(*) FROM events WHERE event_type='note_moved'"
    ).fetchone()[0]
    assert rows == 1
    # And confirms schema_version >= 2
    ver = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]
    assert ver >= 2
