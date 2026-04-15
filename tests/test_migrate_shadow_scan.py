"""Tests for skill obsidian-migrate, Wave 2 (shadow-scan)."""
import json
import pathlib
import shutil
import sys

import pytest

# Import migrate via path manipulation since it lives under skills/
_SKILL_SCRIPTS = (
    pathlib.Path(__file__).parent.parent / "skills" / "obsidian-migrate" / "scripts"
)
sys.path.insert(0, str(_SKILL_SCRIPTS))
import migrate  # noqa: E402


def _make_vault(root: pathlib.Path, n_notes: int = 10) -> None:
    """Cria um vault de teste com n_notes .md files em 2 pastas."""
    root.mkdir(exist_ok=True)
    (root / "00 - Pessoal").mkdir()
    (root / "02 - Pesquisas").mkdir()
    for i in range(n_notes):
        folder = "00 - Pessoal" if i % 2 == 0 else "02 - Pesquisas"
        (root / folder / f"nota-{i}.md").write_text(
            f"---\ntitle: Nota {i}\narea: pessoal\n---\nbody da nota {i}\n"
        )


def test_shadow_scan_creates_backup(tmp_path):
    vault = tmp_path / "vault"
    _make_vault(vault, n_notes=5)
    code = migrate.main(["shadow-scan", "--vault", str(vault), "--no-embed"])
    assert code == 0
    backups = list(tmp_path.glob("vault.backup-*"))
    assert len(backups) == 1
    # Backup contains the same files
    assert (backups[0] / "00 - Pessoal" / "nota-0.md").exists()


def test_shadow_scan_creates_db(tmp_path):
    vault = tmp_path / "vault"
    _make_vault(vault, n_notes=5)
    migrate.main(["shadow-scan", "--vault", str(vault), "--no-embed"])
    db = vault / ".obsidian-master" / "db.sqlite"
    assert db.exists()
    import sqlite3
    conn = sqlite3.connect(str(db))
    n = conn.execute(
        "SELECT COUNT(*) FROM notes WHERE deleted_at IS NULL"
    ).fetchone()[0]
    assert n == 5


def test_shadow_scan_emits_scan_run_event(tmp_path):
    vault = tmp_path / "vault"
    _make_vault(vault, n_notes=3)
    migrate.main(["shadow-scan", "--vault", str(vault), "--no-embed"])
    import sqlite3
    conn = sqlite3.connect(str(vault / ".obsidian-master" / "db.sqlite"))
    rows = conn.execute(
        "SELECT metadata_json FROM events WHERE event_type='scan_run'"
    ).fetchall()
    assert len(rows) == 1
    meta = json.loads(rows[0][0])
    assert meta["mode"] == "shadow"
    assert "backup_path" in meta
    assert "counts" in meta


def test_shadow_scan_aborts_if_disk_full(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    _make_vault(vault, n_notes=3)
    # Mock disk_usage pra retornar pouco espaco livre
    FakeUsage = type("FakeUsage", (), {"free": 100, "total": 1000, "used": 900})

    def fake_disk_usage(_path):
        return FakeUsage()

    monkeypatch.setattr(migrate.shutil, "disk_usage", fake_disk_usage)
    code = migrate.main(["shadow-scan", "--vault", str(vault), "--no-embed"])
    assert code == 1


def test_shadow_scan_skips_backup_when_recent_exists(tmp_path):
    vault = tmp_path / "vault"
    _make_vault(vault, n_notes=3)
    # Pre-cria um backup recente (mtime = agora por default)
    existing = tmp_path / "vault.backup-20991231-235959"
    shutil.copytree(vault, existing)
    migrate.main(["shadow-scan", "--vault", str(vault), "--no-embed"])
    backups = list(tmp_path.glob("vault.backup-*"))
    # Deveria continuar sendo exatamente 1 (skip do backup)
    assert len(backups) == 1
    assert backups[0].name == existing.name


def test_shadow_scan_force_backup_overrides(tmp_path):
    vault = tmp_path / "vault"
    _make_vault(vault, n_notes=3)
    existing = tmp_path / "vault.backup-20991231-235959"
    shutil.copytree(vault, existing)
    migrate.main([
        "shadow-scan", "--vault", str(vault),
        "--no-embed", "--force-backup",
    ])
    backups = list(tmp_path.glob("vault.backup-*"))
    assert len(backups) == 2


def test_shadow_scan_aborts_on_already_migrated(tmp_path, capsys):
    vault = tmp_path / "vault"
    _make_vault(vault, n_notes=1)
    (vault / ".obsidian-master").mkdir()
    (vault / ".obsidian-master" / "marker.json").write_text(
        '{"kit_version":"0.1.0"}'
    )
    code = migrate.main(["shadow-scan", "--vault", str(vault), "--no-embed"])
    assert code == 1
    err = capsys.readouterr().err
    assert "ja migrado" in err.lower() or "marker" in err.lower()


def test_shadow_scan_50_notes_under_10s(tmp_path):
    """Performance: 50 notas <10s com --no-embed."""
    import time
    vault = tmp_path / "vault"
    _make_vault(vault, n_notes=50)
    t0 = time.perf_counter()
    code = migrate.main(["shadow-scan", "--vault", str(vault), "--no-embed"])
    dt = time.perf_counter() - t0
    assert code == 0
    assert dt < 10.0, f"too slow: {dt:.2f}s"
