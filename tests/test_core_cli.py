"""Testes unitarios para core.cli — Story S06 (Wave 6).

Pattern: chamar `cli.main(argv=[...])` diretamente (sem subprocess). capsys
captura stdout, monkeypatch cobre input() e cwd. tmp_path e o vault.
"""
from __future__ import annotations

import pathlib

import pytest

from core import cli


# ---------- 1. init-db cria db.sqlite + marker ----------


def test_init_db_cria_db(tmp_path, capsys):
    rc = cli.main(["init-db", "--vault", str(tmp_path)])
    assert rc == 0
    db = tmp_path / ".obsidian-master" / "db.sqlite"
    marker = tmp_path / ".obsidian-master" / "marker.json"
    assert db.exists(), "db.sqlite deveria ter sido criado"
    assert marker.exists(), "marker.json deveria ter sido criado"
    out = capsys.readouterr().out
    assert "OK" in out
    assert str(tmp_path) in out


# ---------- 2. init-db idempotente ----------


def test_init_db_idempotente(tmp_path):
    rc1 = cli.main(["init-db", "--vault", str(tmp_path)])
    rc2 = cli.main(["init-db", "--vault", str(tmp_path)])
    assert rc1 == 0 and rc2 == 0
    db = tmp_path / ".obsidian-master" / "db.sqlite"
    assert db.exists()


# ---------- 3. scan popula notes ----------


def test_scan_populates_notes(tmp_path, capsys):
    (tmp_path / "a.md").write_text("# A\n[[B]]\n", encoding="utf-8")
    (tmp_path / "b.md").write_text("# B\ncontent\n", encoding="utf-8")
    (tmp_path / "c.md").write_text(
        "---\ntitle: C\n---\nbody aqui\n", encoding="utf-8"
    )
    cli.main(["init-db", "--vault", str(tmp_path)])
    capsys.readouterr()  # drop init output
    rc = cli.main(["scan", "--vault", str(tmp_path), "--no-embed"])
    assert rc == 0
    out = capsys.readouterr().out.lower()
    assert "scan ok" in out
    # 3 notas novas
    assert "criadas:" in out
    assert "3" in out

    # verifica via DB direto tambem
    from core.db import connect

    conn = connect(tmp_path)
    n = conn.execute("SELECT COUNT(*) FROM notes WHERE deleted_at IS NULL").fetchone()[0]
    assert n == 3


# ---------- 4. rebuild-db pede confirmacao ----------


def test_rebuild_db_requires_confirmation(tmp_path, monkeypatch):
    cli.main(["init-db", "--vault", str(tmp_path)])
    db = tmp_path / ".obsidian-master" / "db.sqlite"
    assert db.exists()
    # usuario responde 'n'
    monkeypatch.setattr("builtins.input", lambda _prompt: "n")
    rc = cli.main(["rebuild-db", "--vault", str(tmp_path)])
    assert rc == 1
    # DB intocado
    assert db.exists()


# ---------- 5. rebuild-db --yes pula prompt ----------


def test_rebuild_db_with_yes_flag(tmp_path):
    cli.main(["init-db", "--vault", str(tmp_path)])
    db = tmp_path / ".obsidian-master" / "db.sqlite"
    # cria uma nota fake direto pra confirmar que e apagado
    (tmp_path / "x.md").write_text("# X\n", encoding="utf-8")
    cli.main(["scan", "--vault", str(tmp_path), "--no-embed"])

    from core.db import connect

    conn = connect(tmp_path)
    n_before = conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
    assert n_before >= 1
    conn.close()

    rc = cli.main(["rebuild-db", "--vault", str(tmp_path), "--yes"])
    assert rc == 0
    assert db.exists()  # foi recriado
    conn2 = connect(tmp_path)
    n_after = conn2.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
    assert n_after == 0, "rebuild-db deveria ter apagado as notas"


# ---------- 6. status em vault sem DB ----------


def test_status_uninit_vault_error_clear(tmp_path, capsys):
    # cria so o marker, sem DB (scenario meio artificial, mas cobre o caminho
    # de erro do status quando o DB foi apagado na mao)
    marker = tmp_path / ".obsidian-master" / "marker.json"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("{}", encoding="utf-8")
    rc = cli.main(["status", "--vault", str(tmp_path)])
    assert rc == 1
    err = capsys.readouterr().err.lower()
    assert "db nao existe" in err or "init-db" in err


# ---------- 7. status em vault populado ----------


def test_status_populated_vault(tmp_path, capsys):
    (tmp_path / "nota1.md").write_text("# Nota 1\n", encoding="utf-8")
    (tmp_path / "nota2.md").write_text("# Nota 2\n", encoding="utf-8")
    cli.main(["init-db", "--vault", str(tmp_path)])
    cli.main(["scan", "--vault", str(tmp_path), "--no-embed"])
    capsys.readouterr()  # drop previous output
    rc = cli.main(["status", "--vault", str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Notas ativas:" in out
    assert "2" in out
    assert "Tamanho DB:" in out


# ---------- 8. version sem vault ----------


def test_version_sem_vault(tmp_path, monkeypatch, capsys):
    # cwd num dir sem marker em nenhum ancestral; tmp_path nao tem marker
    monkeypatch.chdir(tmp_path)
    rc = cli.main(["version"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "obsidian-master-kit" in out
    # ou tem schema N/A ou achou algum vault por acidente (improvavel dentro de tmp)
    assert "nenhum vault" in out.lower() or "schema v" in out.lower()


# ---------- 9. help em pt-br ----------


def test_help_em_pt_br(capsys):
    with pytest.raises(SystemExit):
        cli.main(["--help"])
    out = capsys.readouterr().out
    # descricao em pt-br deve mencionar subcomandos
    assert "Todos os subcomandos" in out or "subcomando" in out.lower()


# ---------- 10. resolve_vault via marker em ancestor ----------


def test_resolve_vault_by_marker(tmp_path, monkeypatch):
    (tmp_path / ".obsidian-master").mkdir()
    (tmp_path / ".obsidian-master" / "marker.json").write_text("{}", encoding="utf-8")
    deep = tmp_path / "sub" / "deeper"
    deep.mkdir(parents=True)
    monkeypatch.chdir(deep)
    resolved = cli._resolve_vault(None)
    # realpath compare — tmp_path no macOS vem via /var/folders/... com symlink
    assert pathlib.Path(resolved).resolve() == tmp_path.resolve()


# ---------- 11. resolve_vault sem marker e sem --vault → SystemExit ----------


def test_resolve_vault_sem_marker_erro(tmp_path, monkeypatch):
    # garantir que nao ha marker em nenhum ancestral de tmp_path e que cwd=tmp_path
    monkeypatch.chdir(tmp_path)
    # se houver um marker em ancestral real do tmp_path (improvavel), o teste
    # falha — mas tmp_path normalmente fica em /tmp ou /var/folders, nenhum dos
    # quais tem .obsidian-master/marker.json. Skipamos se encontrarmos um.
    cur = tmp_path.resolve()
    while True:
        if (cur / ".obsidian-master" / "marker.json").exists():
            pytest.skip(
                f"Ancestral {cur} ja tem marker.json — ambiente nao aplica"
            )
        if cur == cur.parent:
            break
        cur = cur.parent

    with pytest.raises(SystemExit) as exc_info:
        cli._resolve_vault(None)
    msg = str(exc_info.value)
    assert "nao encontrei vault" in msg.lower() or "--vault" in msg
