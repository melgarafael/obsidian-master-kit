"""Testes unitarios para core.db — Story S01.

Cobre criterios de aceitacao:
- connect cria DB em <vault>/.obsidian-master/db.sqlite
- migrations idempotentes (2x connect nao falha)
- schema_version = 1 apos primeira conexao
- todas as 16 tabelas base presentes + vec_notes condicional
- CHECK constraints e NOT NULL: reasoning, severity, event_type
- foreign keys enforcadas
- indexes criticos presentes
"""

from __future__ import annotations

import pathlib
import sqlite3

import pytest

from core.db import connect

# 16 tabelas base (fora `schema_version` + `vec_notes` condicional).
BASE_TABLES = {
    "areas",
    "notes",
    "notes_embedding_blob",
    "tags",
    "note_tags",
    "aliases",
    "links",
    "events",
    "clusters",
    "cluster_notes",
    "duplicate_candidates",
    "suggestions_cache",
    "alerts_cache",
    "migration_plan",
    "temporal_patterns",
    "schema_version",
}

REQUIRED_INDEXES = {
    "idx_notes_area",
    "idx_notes_updated",
    "idx_notes_mtime",
    "idx_notes_hash",
    "idx_tags_prefix",
    "idx_note_tags_tag",
    "idx_links_from",
    "idx_links_to",
    "idx_links_target",
    "idx_events_ts",
    "idx_events_date_type",
    "idx_events_area_date",
    "idx_events_note",
    "idx_sugg_active",
    "idx_migration_batch",
}


def _table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table', 'virtual')"
    ).fetchall()
    return {r[0] for r in rows}


def _index_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'").fetchall()
    return {r[0] for r in rows}


def _insert_note(conn: sqlite3.Connection, path: str = "/tmp/n.md") -> int:
    cur = conn.execute(
        "INSERT INTO notes (path, indexed_at) VALUES (?, ?)",
        (path, "2024-01-01T00:00:00+00:00"),
    )
    assert cur.lastrowid is not None
    return int(cur.lastrowid)


# ---------------------------------------------------------------------------
# Criterios de aceitacao
# ---------------------------------------------------------------------------


def test_connect_creates_db_file(tmp_path: pathlib.Path) -> None:
    conn = connect(tmp_path)
    try:
        expected = tmp_path / ".obsidian-master" / "db.sqlite"
        assert expected.exists(), "db.sqlite deveria ter sido criado"
    finally:
        conn.close()


def test_connect_is_idempotent(tmp_path: pathlib.Path) -> None:
    conn1 = connect(tmp_path)
    conn1.close()
    # Segunda conexao nao pode falhar nem re-aplicar migration.
    conn2 = connect(tmp_path)
    try:
        row = conn2.execute("SELECT COUNT(*) FROM schema_version").fetchone()
        assert row[0] == 1, "schema_version deve ter exatamente 1 registro"
    finally:
        conn2.close()


def test_schema_version_is_one(tmp_path: pathlib.Path) -> None:
    conn = connect(tmp_path)
    try:
        row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
        assert row[0] == 1
    finally:
        conn.close()


def test_all_base_tables_exist(tmp_path: pathlib.Path) -> None:
    conn = connect(tmp_path)
    try:
        tables = _table_names(conn)
        missing = BASE_TABLES - tables
        assert not missing, f"tabelas ausentes: {sorted(missing)}"
    finally:
        conn.close()


def test_vec_table_conditional(tmp_path: pathlib.Path) -> None:
    """vec_notes existe sse sqlite-vec carregou; notes_embedding_blob sempre."""
    conn = connect(tmp_path)
    try:
        tables = _table_names(conn)
        assert "notes_embedding_blob" in tables, "fallback sempre deve existir"
        if getattr(conn, "vec_loaded", False):
            assert "vec_notes" in tables, "vec_notes deveria existir quando vec_loaded"
        else:
            assert "vec_notes" not in tables, "vec_notes nao deveria existir sem sqlite-vec"
    finally:
        conn.close()


def test_reasoning_not_null_on_suggestions(tmp_path: pathlib.Path) -> None:
    conn = connect(tmp_path)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO suggestions_cache "
                "(generated_at, expires_at, kind, target_note_ids, content, reasoning) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    "2024-01-01T00:00:00+00:00",
                    "2024-01-02T00:00:00+00:00",
                    "rediscover",
                    "[1]",
                    "teste",
                    None,  # reasoning NOT NULL
                ),
            )
    finally:
        conn.close()


def test_severity_check_constraint(tmp_path: pathlib.Path) -> None:
    conn = connect(tmp_path)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO alerts_cache "
                "(generated_at, expires_at, kind, target_note_ids, content, reasoning, severity) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    "2024-01-01T00:00:00+00:00",
                    "2024-01-02T00:00:00+00:00",
                    "stale_area",
                    "[1]",
                    "teste",
                    "area ficou fria",
                    "critical",  # proibido — anti-tom-vigilante
                ),
            )
    finally:
        conn.close()


def test_event_type_check_constraint(tmp_path: pathlib.Path) -> None:
    conn = connect(tmp_path)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO events (event_type, ts, date) VALUES (?, ?, ?)",
                ("foobar", "2024-01-01T00:00:00+00:00", "2024-01-01"),
            )
    finally:
        conn.close()


def test_foreign_keys_enforced(tmp_path: pathlib.Path) -> None:
    """PRAGMA foreign_keys=ON deve rejeitar FK invalida."""
    conn = connect(tmp_path)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO links (from_note_id, to_target) VALUES (?, ?)",
                (999_999, "Nota Inexistente"),
            )
    finally:
        conn.close()


def test_required_indexes_exist(tmp_path: pathlib.Path) -> None:
    conn = connect(tmp_path)
    try:
        indexes = _index_names(conn)
        missing = REQUIRED_INDEXES - indexes
        assert not missing, f"indexes ausentes: {sorted(missing)}"
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Smoke extra: inserir uma nota valida e um link valido deve funcionar
# ---------------------------------------------------------------------------


def test_happy_path_insert_note_and_link(tmp_path: pathlib.Path) -> None:
    conn = connect(tmp_path)
    try:
        note_id = _insert_note(conn)
        conn.execute(
            "INSERT INTO links (from_note_id, to_note_id, to_target) VALUES (?, ?, ?)",
            (note_id, None, "Nota Quebrada"),
        )
        conn.commit()
        row = conn.execute("SELECT COUNT(*) FROM links WHERE from_note_id = ?", (note_id,)).fetchone()
        assert row[0] == 1
    finally:
        conn.close()
