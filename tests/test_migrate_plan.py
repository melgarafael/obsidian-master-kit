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


def _full_setup(tmp_path, monkeypatch, themes):
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
    migrate.main(["propose", "--vault", str(vault)])
    return vault


def test_plan_requires_propose(tmp_path, capsys):
    vault = tmp_path / "empty"
    vault.mkdir()
    code = migrate.main(["plan", "--vault", str(vault)])
    assert code == 1


def test_plan_generates_migration_plan_entries(tmp_path, monkeypatch):
    vault = _full_setup(tmp_path, monkeypatch, {"Hermetismo": 25, "CRM": 22})
    code = migrate.main(["plan", "--vault", str(vault)])
    assert code == 0
    import sqlite3
    conn = sqlite3.connect(str(vault / ".obsidian-master" / "db.sqlite"))
    rows = conn.execute("SELECT batch_id, status FROM migration_plan").fetchall()
    assert len(rows) > 0
    # All pending
    assert all(r[1] == "pending" for r in rows)
    # Batch size 20: 47 notes -> 3 batches (expected)
    batches = set(r[0] for r in rows)
    assert len(batches) >= 2


def test_plan_does_not_move_files(tmp_path, monkeypatch):
    vault = _full_setup(tmp_path, monkeypatch, {"Hermetismo": 12, "CRM": 10})
    snapshot_before = {str(p.relative_to(vault)) for p in vault.rglob("*.md")}
    migrate.main(["plan", "--vault", str(vault)])
    snapshot_after = {str(p.relative_to(vault)) for p in vault.rglob("*.md")}
    assert snapshot_before == snapshot_after


def test_plan_is_idempotent(tmp_path, monkeypatch):
    vault = _full_setup(tmp_path, monkeypatch, {"Hermetismo": 12, "CRM": 10})
    migrate.main(["plan", "--vault", str(vault)])
    import sqlite3
    conn = sqlite3.connect(str(vault / ".obsidian-master" / "db.sqlite"))
    count1 = conn.execute("SELECT COUNT(*) FROM migration_plan").fetchone()[0]
    migrate.main(["plan", "--vault", str(vault)])
    count2 = conn.execute("SELECT COUNT(*) FROM migration_plan").fetchone()[0]
    # Pending rows replaced; counts should match
    assert count1 == count2


def test_approve_batch_y_flow(tmp_path, monkeypatch):
    vault = _full_setup(tmp_path, monkeypatch, {"Hermetismo": 10, "CRM": 10})
    migrate.main(["plan", "--vault", str(vault)])
    # Simulate user saying 'y' to everything
    inputs = iter(["y"] * 50)
    monkeypatch.setattr("builtins.input", lambda _=None: next(inputs))
    code = migrate.main(["approve", "--vault", str(vault), "--batch", "1"])
    assert code == 0
    import sqlite3
    conn = sqlite3.connect(str(vault / ".obsidian-master" / "db.sqlite"))
    approved = conn.execute(
        "SELECT COUNT(*) FROM migration_plan WHERE batch_id=1 AND status='approved'"
    ).fetchone()[0]
    assert approved > 0


def test_approve_batch_n_flow(tmp_path, monkeypatch):
    vault = _full_setup(tmp_path, monkeypatch, {"Hermetismo": 10, "CRM": 10})
    migrate.main(["plan", "--vault", str(vault)])
    inputs = iter(["n"] * 50)
    monkeypatch.setattr("builtins.input", lambda _=None: next(inputs))
    migrate.main(["approve", "--vault", str(vault), "--batch", "1"])
    import sqlite3
    conn = sqlite3.connect(str(vault / ".obsidian-master" / "db.sqlite"))
    rejected = conn.execute(
        "SELECT COUNT(*) FROM migration_plan WHERE batch_id=1 AND status='rejected'"
    ).fetchone()[0]
    assert rejected > 0


def test_approve_batch_a_all_yes(tmp_path, monkeypatch):
    vault = _full_setup(tmp_path, monkeypatch, {"Hermetismo": 15, "CRM": 12})
    migrate.main(["plan", "--vault", str(vault)])
    # First answer 'a' -> all yes from here
    inputs = iter(["a"])
    monkeypatch.setattr("builtins.input", lambda _=None: next(inputs))
    migrate.main(["approve", "--vault", str(vault), "--batch", "1"])
    import sqlite3
    conn = sqlite3.connect(str(vault / ".obsidian-master" / "db.sqlite"))
    rows = conn.execute(
        "SELECT status FROM migration_plan WHERE batch_id=1"
    ).fetchall()
    assert all(r[0] == "approved" for r in rows)


def test_approve_batch_s_skip(tmp_path, monkeypatch):
    vault = _full_setup(tmp_path, monkeypatch, {"Hermetismo": 10, "CRM": 10})
    migrate.main(["plan", "--vault", str(vault)])
    # First answer 'y', second 's' -> skip remainder
    answers = ["y", "s"]
    idx = [0]

    def _input(_=None):
        v = answers[idx[0]]
        idx[0] += 1
        return v

    monkeypatch.setattr("builtins.input", _input)
    migrate.main(["approve", "--vault", str(vault), "--batch", "1"])
    import sqlite3
    conn = sqlite3.connect(str(vault / ".obsidian-master" / "db.sqlite"))
    pending = conn.execute(
        "SELECT COUNT(*) FROM migration_plan WHERE batch_id=1 AND status='pending'"
    ).fetchone()[0]
    approved = conn.execute(
        "SELECT COUNT(*) FROM migration_plan WHERE batch_id=1 AND status='approved'"
    ).fetchone()[0]
    assert approved == 1
    assert pending >= 1  # remaining notes still pending


def test_approve_all_requires_double_confirm(tmp_path, monkeypatch):
    vault = _full_setup(tmp_path, monkeypatch, {"Hermetismo": 10, "CRM": 10})
    migrate.main(["plan", "--vault", str(vault)])
    # First 'y', second 'y' -> approved
    inputs = iter(["y", "y"])
    monkeypatch.setattr("builtins.input", lambda _=None: next(inputs))
    code = migrate.main(["approve", "--vault", str(vault), "--batch", "all"])
    assert code == 0
    import sqlite3
    conn = sqlite3.connect(str(vault / ".obsidian-master" / "db.sqlite"))
    pending = conn.execute(
        "SELECT COUNT(*) FROM migration_plan WHERE status='pending'"
    ).fetchone()[0]
    assert pending == 0


def test_approve_all_abort_on_first_n(tmp_path, monkeypatch):
    vault = _full_setup(tmp_path, monkeypatch, {"Hermetismo": 10, "CRM": 10})
    migrate.main(["plan", "--vault", str(vault)])
    inputs = iter(["n"])
    monkeypatch.setattr("builtins.input", lambda _=None: next(inputs))
    code = migrate.main(["approve", "--vault", str(vault), "--batch", "all"])
    assert code == 1
    import sqlite3
    conn = sqlite3.connect(str(vault / ".obsidian-master" / "db.sqlite"))
    # Nothing should have been approved
    approved = conn.execute(
        "SELECT COUNT(*) FROM migration_plan WHERE status='approved'"
    ).fetchone()[0]
    assert approved == 0


def test_approve_query_by_status(tmp_path, monkeypatch):
    """Acceptance: SELECT status, COUNT(*) FROM migration_plan GROUP BY status funciona."""
    vault = _full_setup(tmp_path, monkeypatch, {"Hermetismo": 10, "CRM": 10})
    migrate.main(["plan", "--vault", str(vault)])
    import sqlite3
    conn = sqlite3.connect(str(vault / ".obsidian-master" / "db.sqlite"))
    result = dict(conn.execute(
        "SELECT status, COUNT(*) FROM migration_plan GROUP BY status"
    ).fetchall())
    assert "pending" in result
    assert result["pending"] > 0
