"""Testa que obsidian-librarian nao edita notas com protected: true.

Estrategia: vault temporario com marker, nota com protected=true e campos
faltando (updated, status, tags) que o autofix normalmente injetaria.
Rodamos main() diretamente e verificamos que o arquivo nao foi tocado
(conteudo byte-identico) e que nenhum issue foi reportado para ela.
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

# Carrega update_index via sys.path (mesmo padrao dos outros tests do kit).
LIBRARIAN_DIR = (
    pathlib.Path(__file__).parent.parent
    / "skills" / "obsidian-librarian" / "scripts"
)
sys.path.insert(0, str(LIBRARIAN_DIR))

import update_index  # noqa: E402


def _make_vault(tmp_path: pathlib.Path) -> pathlib.Path:
    """Cria vault minimo com marker + estrutura obrigatoria."""
    vault = tmp_path / "vault"
    vault.mkdir()
    marker_dir = vault / ".obsidian-master"
    marker_dir.mkdir()
    (marker_dir / "marker.json").write_text(
        json.dumps({"version": "0.1.1"}), encoding="utf-8"
    )
    # last-sync.json nao existe ainda; main() cria na primeira execucao.
    return vault


def _run_librarian(vault: pathlib.Path, capsys) -> dict:
    """Invoca main() e retorna o JSON emitido em stdout."""
    rc = update_index.main(["--vault", str(vault)])
    assert rc == 0
    captured = capsys.readouterr()
    return json.loads(captured.out)


# ---------- testes ----------


def test_protected_note_not_modified(tmp_path: pathlib.Path, capsys) -> None:
    """Nota com protected=true nao deve ser reescrita pelo autofix."""
    vault = _make_vault(tmp_path)

    # Frontmatter incompleto (sem updated/status/tags) + protected=true.
    # Se o autofix rodar, vai injetar esses campos e o conteudo vai mudar.
    note_content = (
        "---\n"
        "created: 2026-01-01\n"
        "area: pessoal\n"
        "type: nota\n"
        "protected: true\n"
        "---\n\n"
        "Conteudo protegido.\n"
    )
    note_path = vault / "00 - Pessoal" / "nota-protegida.md"
    note_path.parent.mkdir(parents=True)
    note_path.write_text(note_content, encoding="utf-8")

    mtime_before = note_path.stat().st_mtime

    _run_librarian(vault, capsys)

    # Conteudo byte-identico
    assert note_path.read_text(encoding="utf-8") == note_content
    # mtime nao mudou (nenhuma escrita ocorreu)
    assert note_path.stat().st_mtime == mtime_before


def test_protected_note_not_flagged_as_issue(tmp_path: pathlib.Path, capsys) -> None:
    """Nota com protected=true nao deve aparecer em nenhuma lista de issues."""
    vault = _make_vault(tmp_path)

    # Frontmatter com campos faltando — sem protected geraria missing_fields.
    note_content = (
        "---\n"
        "created: 2026-01-01\n"
        "protected: true\n"
        "---\n\n"
        "Nota protegida incompleta.\n"
    )
    note_path = vault / "00 - Pessoal" / "nota-incompleta-protegida.md"
    note_path.parent.mkdir(parents=True)
    note_path.write_text(note_content, encoding="utf-8")

    report = _run_librarian(vault, capsys)

    rel = str(pathlib.Path("00 - Pessoal") / "nota-incompleta-protegida.md")

    # Nao deve aparecer em nenhuma lista de issues
    issue_lists = [
        "missing_frontmatter_fields",
        "invalid_frontmatter",
        "unknown_area",
        "unknown_type",
        "unknown_status",
        "area_folder_mismatch",
        "orphans",
    ]
    for key in issue_lists:
        entries = report.get(key, [])
        if isinstance(entries, list) and entries and isinstance(entries[0], dict):
            files = [e.get("file", "") for e in entries]
        else:
            files = entries  # orphans e uma lista plana de strings
        assert rel not in files, (
            f"Nota protegida apareceu em report['{key}']: {entries}"
        )


def test_protected_note_still_indexed(tmp_path: pathlib.Path, capsys) -> None:
    """Nota com protected=true deve aparecer em notes_scanned (indexada)."""
    vault = _make_vault(tmp_path)

    note_content = (
        "---\n"
        "created: 2026-01-01\n"
        "area: pessoal\n"
        "type: nota\n"
        "status: ativo\n"
        "tags: []\n"
        "protected: true\n"
        "---\n\n"
        "[[outro-link]] — tem link de saida.\n"
    )
    note_path = vault / "00 - Pessoal" / "nota-indexada-protegida.md"
    note_path.parent.mkdir(parents=True)
    note_path.write_text(note_content, encoding="utf-8")

    report = _run_librarian(vault, capsys)

    # _INDEX.md foi gerado e contabilizou a nota
    assert report["notes_scanned"] >= 1
    index_path = vault / "_INDEX.md"
    assert index_path.exists(), "_INDEX.md deve ser criado"
    # A nota protegida aparece no indice (conteudo da pasta pessoal)
    index_text = index_path.read_text(encoding="utf-8")
    assert "Pessoal" in index_text


def test_unprotected_note_still_autofixed(tmp_path: pathlib.Path, capsys) -> None:
    """Nota sem protected deve continuar recebendo autofix normalmente."""
    vault = _make_vault(tmp_path)

    note_content = (
        "---\n"
        "created: 2026-01-01\n"
        "area: pessoal\n"
        "type: nota\n"
        "---\n\n"
        "Nota sem protecao.\n"
    )
    note_path = vault / "00 - Pessoal" / "nota-normal.md"
    note_path.parent.mkdir(parents=True)
    note_path.write_text(note_content, encoding="utf-8")

    _run_librarian(vault, capsys)

    after = note_path.read_text(encoding="utf-8")
    # autofix injeta `updated` e `status`
    assert "updated:" in after
    assert "status:" in after
