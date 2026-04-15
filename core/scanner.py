"""core/scanner.py — scanner incremental com delta em 3 niveis.

Contratos publicos:
- `scan(conn, vault_path, embedder=None) -> ScanReport` — walk completo
- `scan_single_file(conn, vault_path, file_path, embedder=None) -> NoteChange` —
  delta de um unico arquivo. Alvo <80ms para uso em hook PostToolUse.

Princípios de design:
- **Pura deteccao de delta**. Nao emite eventos na tabela `events`. Consumers
  (librarian em Epic 03) iteram `report.changes` e decidem quais eventos
  inserir. Separacao detecao/side-effects.
- **3 niveis de delta**: mtime (stat) -> body_hash (read+hash) -> reparse.
  Cada nivel so paga o custo do proximo se necessario.
- **Re-embed condicional**: so dispara em mudanca semantica significativa
  (Δwc>15%, titulo, ou primeiros 500 chars), nao em typos.
- **Transacao unica por scan**. Commit no fim. Falha no meio = rollback total.
"""
from __future__ import annotations

import datetime as _dt
import fnmatch
import logging
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from core.parser import ParsedNote, parse_markdown

__all__ = ["NoteChange", "ScanReport", "scan", "scan_single_file"]

_LOG = logging.getLogger(__name__)

# Fixo: diretorios e padroes que NUNCA sao escaneados. A checagem de
# diretorio usa componentes do path; `*.backup-*` usa fnmatch no basename.
_FIXED_IGNORE_DIRS = frozenset({
    ".obsidian",
    ".trash",
    ".obsidian-master",
    "_templates",
    "node_modules",
    ".git",
})
_FIXED_IGNORE_FILES = frozenset({".DS_Store"})
_FIXED_IGNORE_GLOBS = ("*.backup-*",)


# ---------- dataclasses ----------

@dataclass(frozen=True)
class NoteChange:
    """Um delta detectado em uma nota.

    `kind` e sempre um de: 'created', 'updated', 'deleted', 'skipped'.
    `word_delta` e positivo no create, signed no update (new-old), None em
    delete/skipped. `body_hash_old`/`body_hash_new` permitem que consumers
    (ex: librarian) gerem diffs sem reler o DB.
    """
    path: str
    kind: str
    note_id: int | None
    word_delta: int | None
    reembedded: bool
    body_hash_old: str | None
    body_hash_new: str | None


@dataclass(frozen=True)
class ScanReport:
    """Resultado de um scan completo. `counts` e derivado de `changes`
    (redundancia proposital: consumers frequentes so querem o agregado)."""
    counts: dict[str, int]
    changes: list[NoteChange]
    duration_s: float


# ---------- helpers ----------

def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()


def _normalize_fm_tags(frontmatter_dict: dict) -> list[str]:
    """Tags de frontmatter → mesmo formato que parser da pra inline_tags.

    Aceita tanto `tags: [a, b]` quanto `tags: a` (string unica). Normaliza
    lowercase e tira `#` prefix. Retorna lista deduplicada preservando ordem.
    """
    raw = frontmatter_dict.get("tags", [])
    if raw is None:
        return []
    if isinstance(raw, str):
        raw = [raw]
    seen: set[str] = set()
    out: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            continue
        tag = item.strip().lstrip("#").lower()
        if tag and tag not in seen:
            seen.add(tag)
            out.append(tag)
    return out


def _normalize_fm_aliases(frontmatter_dict: dict) -> list[str]:
    """Aliases do frontmatter. Aceita lista ou string unica."""
    raw = frontmatter_dict.get("aliases", [])
    if raw is None:
        return []
    if isinstance(raw, str):
        raw = [raw]
    out: list[str] = []
    for item in raw:
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
    return out


def _load_ignore_extension(vault: Path) -> list[str]:
    """Le `<vault>/.obsidian-master/ignore.txt` se existir.

    Uma linha por pattern. Comentarios (`#`) e linhas vazias ignorados.
    Retorna lista crua de patterns (glob-style).
    """
    path = vault / ".obsidian-master" / "ignore.txt"
    if not path.is_file():
        return []
    patterns: list[str] = []
    try:
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                patterns.append(line)
    except OSError as exc:
        _LOG.warning("nao consegui ler ignore.txt (%s: %s)", type(exc).__name__, exc)
        return []
    return patterns


def _is_ignored(
    rel_path: Path,
    extra_patterns: Iterable[str] = (),
) -> bool:
    """True se o path relativo bate com qualquer pattern de ignore.

    Regras:
    - Qualquer componente do path que bate com `_FIXED_IGNORE_DIRS` → ignora.
    - Basename em `_FIXED_IGNORE_FILES` → ignora.
    - Basename bate com um dos globs fixos → ignora.
    - Extra: para cada pattern de ignore.txt, tentar fnmatch no path relativo
      POSIX E em cada componente (cobre tanto "pasta/" quanto "*.bak").
    """
    parts = rel_path.parts
    # dir components
    for segment in parts[:-1]:
        if segment in _FIXED_IGNORE_DIRS:
            return True
    # basename fixo
    basename = parts[-1] if parts else ""
    if basename in _FIXED_IGNORE_FILES:
        return True
    for glob in _FIXED_IGNORE_GLOBS:
        if fnmatch.fnmatch(basename, glob):
            return True
    # extensoes do usuario
    rel_posix = rel_path.as_posix()
    for pattern in extra_patterns:
        p = pattern.rstrip("/")
        # match no path relativo inteiro
        if fnmatch.fnmatch(rel_posix, p):
            return True
        # match em qualquer segmento (cobre "pasta" significando "qualquer
        # pasta com esse nome em qualquer profundidade")
        for segment in parts:
            if fnmatch.fnmatch(segment, p):
                return True
    return False


def _infer_title(rel_path: Path, frontmatter_dict: dict) -> str:
    """Titulo: frontmatter.title > filename stem."""
    title = frontmatter_dict.get("title")
    if isinstance(title, str) and title.strip():
        return title.strip()
    return rel_path.stem


def _resolve_area_id(conn: sqlite3.Connection, rel_path: Path) -> int | None:
    """Tenta mapear o primeiro componente do path para `areas.folder`.

    Epic 02 (migrate skill) popula `areas`; ate la isso geralmente retorna
    NULL, o que e esperado.
    """
    parts = rel_path.parts
    if len(parts) < 2:
        return None
    folder = parts[0]
    row = conn.execute("SELECT id FROM areas WHERE folder = ?", (folder,)).fetchone()
    return int(row[0]) if row is not None else None


def _should_reembed(
    *,
    body_hash_changed: bool,
    old_word_count: int | None,
    new_word_count: int,
    old_title: str | None,
    new_title: str,
    old_body_prefix: str | None,
    new_body_prefix: str,
    embedder_model: str | None,
    stored_model: str | None,
) -> bool:
    """Gatilhos de re-embed.

    Re-embed SO SE:
    - body_hash mudou E (Δwc>15% OU titulo OU primeiros 500 chars), OU
    - embedding_model swap (model_name difere de stored_model).

    Swap de modelo e checado SEPARADAMENTE: mesmo sem mudanca de body, se o
    modelo mudou, precisamos re-gerar.
    """
    if embedder_model is None:
        return False
    if stored_model is not None and stored_model != embedder_model:
        return True
    if not body_hash_changed:
        return False
    # condicao 1: titulo mudou (nota foi renomeada semanticamente)
    if old_title != new_title:
        return True
    # condicao 2: primeiros 500 chars (so considera se AMBOS lados existem —
    # v1 passa None pra old_body_prefix, entao esse gate fica neutro)
    if old_body_prefix is not None and old_body_prefix != new_body_prefix:
        return True
    # condicao 3: delta de word_count > 15%
    if old_word_count is None or old_word_count == 0:
        # primeira vez com word_count → trate como mudanca relevante se body
        # tem qualquer conteudo
        return new_word_count > 0
    delta = abs(new_word_count - old_word_count) / old_word_count
    return delta > 0.15


def _serialize_vec(vec: Any, vec_loaded: bool) -> bytes:
    """Serializa vetor para BLOB. Usa sqlite_vec.serialize_float32 se disponivel."""
    import numpy as np

    arr = np.asarray(vec, dtype=np.float32)
    if vec_loaded:
        try:
            import sqlite_vec  # type: ignore[import-not-found]
            return sqlite_vec.serialize_float32(arr.tolist())
        except Exception:
            # fallback: bytes puros de float32 — vec0 tambem aceita isso
            return arr.tobytes()
    return arr.tobytes()


def _write_embedding(
    conn: sqlite3.Connection,
    note_id: int,
    vec: Any,
    vec_loaded: bool,
) -> None:
    """Upsert em vec_notes OU notes_embedding_blob conforme conn.vec_loaded."""
    blob = _serialize_vec(vec, vec_loaded)
    if vec_loaded:
        conn.execute(
            "INSERT OR REPLACE INTO vec_notes (note_id, embedding) VALUES (?, ?)",
            (note_id, blob),
        )
    else:
        conn.execute(
            "INSERT OR REPLACE INTO notes_embedding_blob (note_id, vec) VALUES (?, ?)",
            (note_id, blob),
        )


def _resolve_link_target(
    conn: sqlite3.Connection,
    target: str,
    path_to_id: dict[str, int],
    title_lookup: dict[str, int],
) -> int | None:
    """Resolve `to_target` a `to_note_id`.

    Ordem: (1) path exato (com ou sem `.md`), (2) titulo case-insensitive.
    Primeiro hit vence; sem match retorna None (broken link preservado).
    """
    # tenta path exato
    candidates = [target, f"{target}.md"]
    for c in candidates:
        if c in path_to_id:
            return path_to_id[c]
    # titulo case-insensitive
    tid = title_lookup.get(target.lower())
    if tid is not None:
        return tid
    # alguns wikilinks vem com path tipo "Pasta/Foo" — tenta so a parte final
    # como titulo
    tail = target.rsplit("/", 1)[-1]
    if tail != target:
        tid = title_lookup.get(tail.lower())
        if tid is not None:
            return tid
    return None


# ---------- DB upsert primitives ----------

def _upsert_note_row(
    conn: sqlite3.Connection,
    *,
    rel_path: str,
    title: str,
    area_id: int | None,
    mtime: float,
    parsed: ParsedNote,
    existing_row: dict | None,
    now_iso: str,
) -> tuple[int, str]:
    """Insere ou atualiza a linha em `notes`. Retorna (note_id, kind).

    kind e 'created' quando nao havia linha OU havia linha soft-deleted que
    foi ressuscitada. Caso contrario e 'updated'.
    """
    fm_raw = parsed.frontmatter_raw_json
    word_count = parsed.word_count
    char_count = len(parsed.body)
    body_hash = parsed.body_hash
    fm = parsed.frontmatter_dict

    # Campos opcionais do frontmatter (preserva convencao v1). Se campo nao
    # existe ou nao e string, guarda None.
    def _fm_str(key: str) -> str | None:
        v = fm.get(key)
        return v.strip() if isinstance(v, str) and v.strip() else None

    type_ = _fm_str("type")
    status = _fm_str("status")
    created = _fm_str("created")
    updated = _fm_str("updated")
    source = _fm_str("source")
    project = _fm_str("project")
    generated_by = _fm_str("generated_by")
    sensitive = 1 if fm.get("sensitive") in (True, 1, "true", "True") else 0
    confidence = fm.get("confidence")
    if not isinstance(confidence, (int, float)):
        confidence = None

    if existing_row is None:
        cur = conn.execute(
            """
            INSERT INTO notes (
                path, title, area_id, type, status, created, updated,
                mtime, word_count, char_count, body_hash, frontmatter_json,
                confidence, source, project, generated_by, sensitive,
                indexed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                rel_path, title, area_id, type_, status, created, updated,
                mtime, word_count, char_count, body_hash, fm_raw,
                confidence, source, project, generated_by, sensitive,
                now_iso,
            ),
        )
        return int(cur.lastrowid), "created"

    # update path: soft-delete resurrect conta como created (semanticamente o
    # arquivo reapareceu no vault)
    was_deleted = existing_row.get("deleted_at") is not None
    conn.execute(
        """
        UPDATE notes SET
            title=?, area_id=?, type=?, status=?, created=?, updated=?,
            mtime=?, word_count=?, char_count=?, body_hash=?,
            frontmatter_json=?, confidence=?, source=?, project=?,
            generated_by=?, sensitive=?, indexed_at=?, deleted_at=NULL
        WHERE id=?
        """,
        (
            title, area_id, type_, status, created, updated,
            mtime, word_count, char_count, body_hash, fm_raw,
            confidence, source, project, generated_by, sensitive,
            now_iso, existing_row["id"],
        ),
    )
    return int(existing_row["id"]), ("created" if was_deleted else "updated")


def _replace_tags(conn: sqlite3.Connection, note_id: int, tags: set[str]) -> None:
    conn.execute("DELETE FROM note_tags WHERE note_id=?", (note_id,))
    for tag in tags:
        if not tag:
            continue
        conn.execute("INSERT OR IGNORE INTO tags(tag) VALUES (?)", (tag,))
        row = conn.execute("SELECT id FROM tags WHERE tag=?", (tag,)).fetchone()
        if row is None:
            continue
        conn.execute(
            "INSERT OR IGNORE INTO note_tags(note_id, tag_id) VALUES (?, ?)",
            (note_id, int(row[0])),
        )


def _replace_aliases(conn: sqlite3.Connection, note_id: int, aliases: list[str]) -> None:
    conn.execute("DELETE FROM aliases WHERE note_id=?", (note_id,))
    for alias in aliases:
        if not alias:
            continue
        conn.execute(
            "INSERT OR IGNORE INTO aliases(note_id, alias) VALUES (?, ?)",
            (note_id, alias),
        )


def _replace_links(
    conn: sqlite3.Connection,
    note_id: int,
    parsed: ParsedNote,
    path_to_id: dict[str, int],
    title_lookup: dict[str, int],
) -> None:
    conn.execute("DELETE FROM links WHERE from_note_id=?", (note_id,))
    for wl in parsed.wikilinks:
        to_id = _resolve_link_target(conn, wl.target, path_to_id, title_lookup)
        conn.execute(
            """
            INSERT INTO links (from_note_id, to_note_id, to_target, link_type)
            VALUES (?, ?, ?, 'wikilink')
            """,
            (note_id, to_id, wl.target),
        )
    for target in parsed.embeds:
        to_id = _resolve_link_target(conn, target, path_to_id, title_lookup)
        conn.execute(
            """
            INSERT INTO links (from_note_id, to_note_id, to_target, link_type)
            VALUES (?, ?, ?, 'embed')
            """,
            (note_id, to_id, target),
        )


# ---------- scanning core ----------

@dataclass
class _ScanContext:
    """Estado compartilhado entre scan() e scan_single_file().

    Carregar `path_to_id` e `title_lookup` de uma vez e mais barato que fazer
    N queries individuais pra resolver links.
    """
    conn: sqlite3.Connection
    vault: Path
    embedder: Any | None
    ignore_extra: list[str]
    path_to_id: dict[str, int] = field(default_factory=dict)
    title_lookup: dict[str, int] = field(default_factory=dict)
    vec_loaded: bool = False

    @classmethod
    def build(
        cls,
        conn: sqlite3.Connection,
        vault: Path,
        embedder: Any | None,
    ) -> "_ScanContext":
        vault = Path(vault).resolve()
        ignore_extra = _load_ignore_extension(vault)
        ctx = cls(
            conn=conn,
            vault=vault,
            embedder=embedder,
            ignore_extra=ignore_extra,
            vec_loaded=bool(getattr(conn, "vec_loaded", False)),
        )
        ctx._load_lookups()
        return ctx

    def _load_lookups(self) -> None:
        self.path_to_id.clear()
        self.title_lookup.clear()
        for row in self.conn.execute(
            "SELECT id, path, title FROM notes WHERE deleted_at IS NULL"
        ):
            self.path_to_id[row[1]] = int(row[0])
            if row[2]:
                self.title_lookup[row[2].lower()] = int(row[0])


def _fetch_existing(conn: sqlite3.Connection, rel_path: str) -> dict | None:
    """Row em dict pra notes.path=rel_path. Inclui soft-deleted."""
    row = conn.execute(
        """
        SELECT id, path, title, mtime, body_hash, word_count, embedding_model,
               deleted_at
        FROM notes WHERE path=?
        """,
        (rel_path,),
    ).fetchone()
    if row is None:
        return None
    return {
        "id": int(row[0]),
        "path": row[1],
        "title": row[2],
        "mtime": row[3],
        "body_hash": row[4],
        "word_count": row[5],
        "embedding_model": row[6],
        "deleted_at": row[7],
    }


def _process_file(
    ctx: _ScanContext,
    rel_path: Path,
    full_path: Path,
) -> NoteChange:
    """Processa um arquivo e retorna um NoteChange. NAO comita.

    Implementa os 3 niveis de delta. Qualquer erro de I/O vira 'skipped'.
    """
    rel_str = rel_path.as_posix()
    try:
        stat = full_path.stat()
    except OSError as exc:
        _LOG.warning("stat falhou em %s (%s)", rel_str, exc)
        return NoteChange(
            path=rel_str, kind="skipped", note_id=None, word_delta=None,
            reembedded=False, body_hash_old=None, body_hash_new=None,
        )
    mtime = stat.st_mtime
    existing = _fetch_existing(ctx.conn, rel_str)
    now_iso = _now_iso()

    # -------- Nivel 1: mtime hit --------
    if (
        existing is not None
        and existing["deleted_at"] is None
        and existing["mtime"] is not None
        and abs(existing["mtime"] - mtime) < 1e-6
    ):
        return NoteChange(
            path=rel_str, kind="skipped",
            note_id=existing["id"], word_delta=None, reembedded=False,
            body_hash_old=existing["body_hash"], body_hash_new=existing["body_hash"],
        )

    # -------- Le o arquivo (Niveis 2 e 3) --------
    try:
        text = full_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        _LOG.warning("read_text falhou em %s (%s)", rel_str, exc)
        return NoteChange(
            path=rel_str, kind="skipped",
            note_id=existing["id"] if existing else None,
            word_delta=None, reembedded=False,
            body_hash_old=existing["body_hash"] if existing else None,
            body_hash_new=None,
        )

    parsed = parse_markdown(text)

    # -------- Nivel 2: hash hit --------
    if (
        existing is not None
        and existing["deleted_at"] is None
        and existing["body_hash"] == parsed.body_hash
    ):
        # conteudo identico — so refresh do mtime
        ctx.conn.execute(
            "UPDATE notes SET mtime=?, indexed_at=? WHERE id=?",
            (mtime, now_iso, existing["id"]),
        )
        return NoteChange(
            path=rel_str, kind="skipped",
            note_id=existing["id"], word_delta=None, reembedded=False,
            body_hash_old=existing["body_hash"], body_hash_new=parsed.body_hash,
        )

    # -------- Nivel 3: reparse + upsert completo --------
    title = _infer_title(rel_path, parsed.frontmatter_dict)
    area_id = _resolve_area_id(ctx.conn, rel_path)

    note_id, kind = _upsert_note_row(
        ctx.conn,
        rel_path=rel_str,
        title=title,
        area_id=area_id,
        mtime=mtime,
        parsed=parsed,
        existing_row=existing,
        now_iso=now_iso,
    )

    # tags: union de frontmatter + inline. Dedup via set (ordem nao importa
    # pois storage e N:N).
    tags: set[str] = set(parsed.inline_tags)
    tags.update(_normalize_fm_tags(parsed.frontmatter_dict))
    _replace_tags(ctx.conn, note_id, tags)
    _replace_aliases(ctx.conn, note_id, _normalize_fm_aliases(parsed.frontmatter_dict))

    # links: atualizar path_to_id com a nota atual antes de resolver
    # (auto-referencia e links que apontam pra esta nota no mesmo scan)
    ctx.path_to_id[rel_str] = note_id
    if title:
        ctx.title_lookup[title.lower()] = note_id
    _replace_links(ctx.conn, note_id, parsed, ctx.path_to_id, ctx.title_lookup)

    # -------- Re-embed condicional --------
    # DEVIATION: o plano lista "primeiros 500 chars do body diferem" como
    # um dos gatilhos semanticos. Pra checar isso precisariamos armazenar
    # o prefix antigo (coluna nova) ou re-ler o body antigo (nao temos).
    # Optamos por OMITIR esse gatilho em v1 — os outros dois (Δwc>15% OU
    # titulo) cobrem os casos semanticos relevantes e pegam os testes
    # especificados. "Typo que nao muda wc nem titulo" fica com embedding
    # stale — aceitavel na pratica ate Epic 02 adicionar cache de prefix.
    reembedded = False
    embedder_model = getattr(ctx.embedder, "model_name", None) if ctx.embedder else None
    body_hash_changed = existing is None or existing["body_hash"] != parsed.body_hash

    should = _should_reembed(
        body_hash_changed=body_hash_changed,
        old_word_count=existing["word_count"] if existing else None,
        new_word_count=parsed.word_count,
        old_title=existing["title"] if existing else None,
        new_title=title,
        old_body_prefix=None,  # v1: nao persistido
        new_body_prefix="",    # v1: comparacao neutralizada
        embedder_model=embedder_model,
        stored_model=existing["embedding_model"] if existing else None,
    )

    if should and ctx.embedder is not None:
        try:
            vecs = ctx.embedder.embed([parsed.body])
            vec = vecs[0]
            _write_embedding(ctx.conn, note_id, vec, ctx.vec_loaded)
            ctx.conn.execute(
                """
                UPDATE notes SET
                    embedding_model=?, embedding_dim=?, embedding_generated_at=?
                WHERE id=?
                """,
                (embedder_model, getattr(ctx.embedder, "dim", None), now_iso, note_id),
            )
            reembedded = True
        except Exception as exc:
            _LOG.warning("embedder.embed falhou em %s (%s)", rel_str, exc)

    word_delta: int | None
    if existing is None or existing["deleted_at"] is not None:
        word_delta = parsed.word_count
    else:
        old_wc = existing["word_count"] or 0
        word_delta = parsed.word_count - old_wc

    return NoteChange(
        path=rel_str, kind=kind, note_id=note_id, word_delta=word_delta,
        reembedded=reembedded,
        body_hash_old=(existing["body_hash"] if existing else None),
        body_hash_new=parsed.body_hash,
    )


def _walk_markdown(vault: Path, ignore_extra: list[str]):
    """Yield (rel_path, full_path) pra cada .md nao-ignorado."""
    for entry in vault.rglob("*.md"):
        if not entry.is_file():
            continue
        try:
            rel = entry.relative_to(vault)
        except ValueError:
            continue
        if _is_ignored(rel, ignore_extra):
            continue
        yield rel, entry


def _reresolve_broken_links(ctx: _ScanContext) -> None:
    """Segundo pass pra tentar resolver links com to_note_id=NULL.

    Pragmatico: durante o walk, ordem de processamento pode fazer nota A
    linkar B antes de B ser upsertada. path_to_id/title_lookup agora tem
    tudo → re-atacamos os quebrados.
    """
    rows = ctx.conn.execute(
        "SELECT id, to_target FROM links WHERE to_note_id IS NULL"
    ).fetchall()
    for link_id, target in rows:
        resolved = _resolve_link_target(
            ctx.conn, target, ctx.path_to_id, ctx.title_lookup
        )
        if resolved is not None:
            ctx.conn.execute(
                "UPDATE links SET to_note_id=? WHERE id=?",
                (resolved, int(link_id)),
            )


def _detect_deletions(
    ctx: _ScanContext,
    seen_paths: set[str],
) -> list[NoteChange]:
    """Marca deleted_at em notas cujo arquivo sumiu."""
    changes: list[NoteChange] = []
    now_iso = _now_iso()
    rows = ctx.conn.execute(
        "SELECT id, path, word_count, body_hash FROM notes WHERE deleted_at IS NULL"
    ).fetchall()
    for row in rows:
        note_id, path, word_count, body_hash = row
        if path in seen_paths:
            continue
        full = ctx.vault / path
        if full.exists():
            # nao foi visto no walk mas existe → provavelmente ignorado agora;
            # nao marca deletado (seria falso positivo).
            continue
        ctx.conn.execute(
            "UPDATE notes SET deleted_at=? WHERE id=?", (now_iso, int(note_id)),
        )
        changes.append(NoteChange(
            path=path, kind="deleted", note_id=int(note_id),
            word_delta=None, reembedded=False,
            body_hash_old=body_hash, body_hash_new=None,
        ))
    return changes


# ---------- public API ----------

def scan(
    conn: sqlite3.Connection,
    vault_path: Path,
    embedder: Any | None = None,
) -> ScanReport:
    """Walk completo do vault. Uma transacao, commit no fim.

    Retorna ScanReport com counts agregados e lista completa de NoteChange.
    Consumers iteram `report.changes` pra decidir side-effects (ex: inserir
    events na tabela `events`).
    """
    t0 = time.perf_counter()
    ctx = _ScanContext.build(conn, vault_path, embedder)

    changes: list[NoteChange] = []
    seen: set[str] = set()

    try:
        for rel, full in _walk_markdown(ctx.vault, ctx.ignore_extra):
            seen.add(rel.as_posix())
            change = _process_file(ctx, rel, full)
            changes.append(change)

        # deletions pos-walk
        changes.extend(_detect_deletions(ctx, seen))

        # re-resolve links quebrados agora que path_to_id/title_lookup tem
        # todas as notas do walk. Cobre o caso de uma nota A linkar uma
        # nota B ainda nao processada no momento do upsert de A.
        _reresolve_broken_links(ctx)

        conn.commit()
    except Exception:
        conn.rollback()
        raise

    counts = {"created": 0, "updated": 0, "deleted": 0, "skipped": 0}
    for ch in changes:
        counts[ch.kind] = counts.get(ch.kind, 0) + 1

    return ScanReport(
        counts=counts,
        changes=changes,
        duration_s=time.perf_counter() - t0,
    )


def scan_single_file(
    conn: sqlite3.Connection,
    vault_path: Path,
    file_path: Path,
    embedder: Any | None = None,
) -> NoteChange:
    """Delta de um arquivo unico. Alvo <80ms pra hook PostToolUse.

    - Aceita `file_path` absoluto ou relativo ao vault.
    - Se o arquivo esta ignorado: retorna NoteChange(kind='skipped').
    - Se o arquivo nao existe mas existe row no DB: marca deleted_at.
    - Caso contrario: roda niveis 1-3 para esse arquivo.
    """
    vault = Path(vault_path).resolve()
    fp = Path(file_path)
    if not fp.is_absolute():
        fp = (vault / fp).resolve()
    else:
        fp = fp.resolve()

    try:
        rel = fp.relative_to(vault)
    except ValueError:
        # arquivo fora do vault — nao temos o que fazer
        return NoteChange(
            path=str(fp), kind="skipped", note_id=None, word_delta=None,
            reembedded=False, body_hash_old=None, body_hash_new=None,
        )

    ignore_extra = _load_ignore_extension(vault)
    if _is_ignored(rel, ignore_extra):
        return NoteChange(
            path=rel.as_posix(), kind="skipped", note_id=None, word_delta=None,
            reembedded=False, body_hash_old=None, body_hash_new=None,
        )

    ctx = _ScanContext.build(conn, vault, embedder)
    rel_str = rel.as_posix()

    try:
        if not fp.exists():
            existing = _fetch_existing(conn, rel_str)
            if existing is None or existing["deleted_at"] is not None:
                change = NoteChange(
                    path=rel_str, kind="skipped",
                    note_id=existing["id"] if existing else None,
                    word_delta=None, reembedded=False,
                    body_hash_old=existing["body_hash"] if existing else None,
                    body_hash_new=None,
                )
            else:
                conn.execute(
                    "UPDATE notes SET deleted_at=? WHERE id=?",
                    (_now_iso(), existing["id"]),
                )
                change = NoteChange(
                    path=rel_str, kind="deleted", note_id=existing["id"],
                    word_delta=None, reembedded=False,
                    body_hash_old=existing["body_hash"], body_hash_new=None,
                )
        else:
            change = _process_file(ctx, rel, fp)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return change
