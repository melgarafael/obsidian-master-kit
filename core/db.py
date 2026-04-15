"""core.db — conexao SQLite + migrations idempotentes.

Contratos:
- `connect(vault_path: Path) -> sqlite3.Connection`
- `ensure_schema(conn: sqlite3.Connection) -> None` (idempotent)

Atributo customizado na conexao: `conn.vec_loaded: bool`.
"""

from __future__ import annotations

import datetime as _dt
import logging
import pathlib
import re
import sqlite3
from typing import Iterable

__all__ = ["connect", "ensure_schema"]

_LOG = logging.getLogger(__name__)

_MIGRATIONS_DIR = pathlib.Path(__file__).parent / "migrations"
_MIGRATION_FILENAME_RE = re.compile(r"^(\d+)_.*\.sql$")

_VEC_TABLE_SQL = (
    "CREATE VIRTUAL TABLE IF NOT EXISTS vec_notes "
    "USING vec0(note_id integer primary key, embedding float[256])"
)


class _ObsidianMasterConnection(sqlite3.Connection):
    """Subclasse de sqlite3.Connection que permite atributos customizados.

    CPython's `sqlite3.Connection` bloqueia `setattr` em atributos novos por
    nao ter `__dict__`. Como o plano especifica `conn.vec_loaded`, usamos
    uma subclasse que reabre `__dict__`.
    """


def _now_iso() -> str:
    """Timestamp ISO-8601 em UTC, segundos de precisao."""
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()


def _load_sqlite_vec(conn: sqlite3.Connection) -> bool:
    """Tenta carregar a extensao sqlite-vec. Retorna True se sucesso.

    Em caso de qualquer falha (import error, extension nao suportada pelo
    sqlite3 do sistema, erro na load), loga warning e retorna False. O schema
    faz fallback via `notes_embedding_blob`.
    """
    try:
        import sqlite_vec  # type: ignore[import-not-found]

        conn.enable_load_extension(True)
        try:
            sqlite_vec.load(conn)
        finally:
            conn.enable_load_extension(False)
        return True
    except Exception as exc:  # pragma: no cover — caminho depende do ambiente
        _LOG.warning(
            "sqlite-vec nao carregou (%s: %s). Usando notes_embedding_blob como fallback.",
            type(exc).__name__,
            exc,
        )
        return False


def _apply_pragmas(conn: sqlite3.Connection) -> None:
    """Aplica PRAGMAs antes de carregar a extensao."""
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")


def _ensure_schema_version_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_version ("
        "version INTEGER PRIMARY KEY, "
        "applied_at TEXT NOT NULL"
        ")"
    )


def _current_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COALESCE(MAX(version), 0) FROM schema_version").fetchone()
    return int(row[0]) if row is not None else 0


def _discover_migrations(migrations_dir: pathlib.Path) -> list[tuple[int, pathlib.Path]]:
    """Escaneia diretorio por arquivos NNN_*.sql, ordenados por versao."""
    found: list[tuple[int, pathlib.Path]] = []
    if not migrations_dir.is_dir():
        return found
    for entry in migrations_dir.iterdir():
        if not entry.is_file():
            continue
        match = _MIGRATION_FILENAME_RE.match(entry.name)
        if not match:
            continue
        version = int(match.group(1))
        found.append((version, entry))
    found.sort(key=lambda item: item[0])
    return found


def _run_pending_migrations(
    conn: sqlite3.Connection,
    migrations: Iterable[tuple[int, pathlib.Path]],
) -> None:
    """Roda cada migration com version > current, cada uma em sua transacao."""
    current = _current_version(conn)
    for version, sql_path in migrations:
        if version <= current:
            continue
        sql = sql_path.read_text(encoding="utf-8")
        try:
            with conn:  # BEGIN/COMMIT automatico; rollback em excecao
                conn.executescript(sql)
                conn.execute(
                    "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                    (version, _now_iso()),
                )
        except sqlite3.Error:
            _LOG.exception("Falha aplicando migration %s (%s)", version, sql_path.name)
            raise
        _LOG.info("Migration %03d aplicada (%s)", version, sql_path.name)
        current = version


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Aplica todas as migrations pendentes. Idempotente.

    Cria a tabela virtual `vec_notes` (vec0) ao final se `conn.vec_loaded` for True.
    """
    _ensure_schema_version_table(conn)
    migrations = _discover_migrations(_MIGRATIONS_DIR)
    _run_pending_migrations(conn, migrations)

    if getattr(conn, "vec_loaded", False):
        try:
            conn.execute(_VEC_TABLE_SQL)
            conn.commit()
        except sqlite3.Error:
            _LOG.exception("Falha ao criar vec_notes mesmo com sqlite-vec carregado")
            raise


def connect(vault_path: pathlib.Path) -> sqlite3.Connection:
    """Abre (ou cria) o DB do vault e garante schema aplicado.

    - Cria `<vault>/.obsidian-master/` se nao existir.
    - Aplica PRAGMAs `foreign_keys=ON`, `journal_mode=WAL`, `synchronous=NORMAL`
      ANTES de carregar qualquer extensao.
    - Tenta carregar sqlite-vec; expoe resultado em `conn.vec_loaded`.
    - Roda `ensure_schema(conn)`.
    """
    vault_path = pathlib.Path(vault_path)
    kit_dir = vault_path / ".obsidian-master"
    kit_dir.mkdir(parents=True, exist_ok=True)
    db_path = kit_dir / "db.sqlite"

    conn = sqlite3.connect(str(db_path), factory=_ObsidianMasterConnection)
    _apply_pragmas(conn)

    vec_loaded = _load_sqlite_vec(conn)
    conn.vec_loaded = vec_loaded  # type: ignore[attr-defined]

    ensure_schema(conn)
    return conn
