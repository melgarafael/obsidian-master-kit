#!/usr/bin/env python3
"""Librarian engine for obsidian-master-kit vaults.

Scans a vault, validates each `.md` note's frontmatter, auto-fixes determinism-safe
issues (missing `updated`/`status`/`tags` fields, tag normalization), and rewrites
`_INDEX.md` with a fresh snapshot. Reports semantic issues (unknown area, type
mismatch, orphans without MOC links, etc.) as JSON on stdout for the LLM to handle.

Stdlib-only (no yaml dependency): uses a focused frontmatter parser that covers our
specific schema. Malformed frontmatter is reported as an issue, never silently
ignored.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import pathlib
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

# Reuso de submodulos de core/ (Epic 01) sem passar pelo package
# `core/__init__.py` — esse ultimo puxa networkx/model2vec, e o librarian
# historicamente e stdlib-only (pode rodar em vaults v0.1.1 sem as deps
# pesadas instaladas). `core.parser`, `core.db` e `core.scanner` individualmente
# sao stdlib (sqlite_vec/numpy sao opcionais e carregados lazy).
#
# Estrategia: registramos um stub vazio pra `core` no sys.modules antes de
# carregar os submodulos, entao `from core.parser import ...` dentro de
# `core.scanner` resolve via sys.modules sem executar `core/__init__.py`.
import importlib.util as _ilu  # noqa: E402
import types as _types  # noqa: E402

_CORE_DIR = pathlib.Path(__file__).resolve().parents[3] / "core"


def _load_core_module(mod_name: str, filename: str):
    """Carrega core/<filename>.py e registra como `core.<mod_name>` em sys.modules.

    Registra tambem com o shortname legacy (`_obm_core_<mod_name>`) pra
    compat com decoracao @dataclass (que resolve __module__ no exec).
    Idempotente: retorna o modulo ja carregado se existir.
    """
    qualified = f"core.{mod_name}"
    if qualified in sys.modules:
        return sys.modules[qualified]

    # Garante stub `core` no sys.modules pra intercepter `from core.X import ...`
    if "core" not in sys.modules:
        _pkg = _types.ModuleType("core")
        _pkg.__path__ = [str(_CORE_DIR)]  # type: ignore[attr-defined]
        sys.modules["core"] = _pkg

    path = _CORE_DIR / filename
    spec = _ilu.spec_from_file_location(qualified, path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"core/{filename} nao encontrado em {path}")
    module = _ilu.module_from_spec(spec)
    sys.modules[qualified] = module
    # shortname legacy (mantem compat com o wave 1)
    sys.modules[f"_obm_core_{mod_name}"] = module
    spec.loader.exec_module(module)
    # Expor como attr no package stub (pra `from core import X`)
    setattr(sys.modules["core"], mod_name, module)
    return module


_core_parser = _load_core_module("parser", "parser.py")
parse_markdown = _core_parser.parse_markdown

CANONICAL_AREAS = {"pessoal", "profissional", "pesquisa", "ai-memory"}
CANONICAL_TYPES = {
    "nota", "projeto", "pesquisa", "diario", "journaling",
    "contexto", "area", "referencia", "moc", "perfil", "indice",
}
CANONICAL_STATUSES = {"draft", "ativo", "arquivado"}
REQUIRED_FIELDS = ("created", "updated", "area", "type", "status", "tags")

AREA_FOLDER_MAP = {
    "00 - Pessoal": "pessoal",
    "01 - Profissional": "profissional",
    "02 - Pesquisas e Estudos": "pesquisa",
    "03 - Memoria da IA": "ai-memory",
}

MOC_FILENAME = "_MOC.md"
INDEX_FILENAME = "_INDEX.md"
CLAUDE_FILENAME = "CLAUDE.md"
README_FILENAME = "README.md"
MARKER_PATH = pathlib.Path(".obsidian-master/marker.json")

# Files that are "structural" (meta, not content notes) — skip all validation.
STRUCTURAL_FILES = {CLAUDE_FILENAME, INDEX_FILENAME, README_FILENAME}

TAG_IN_BODY_RE = re.compile(r"(?<![\w/])#([a-z0-9][a-z0-9/_-]*)", re.IGNORECASE)


# ---------- frontmatter parser ----------
# Parser foi movido para `core.parser.parse_markdown` (Epic 01). Uso direto
# via `parse_markdown(text)` em `scan_vault`.


# ---------- frontmatter serializer ----------

def _serialize_value(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, list):
        if not v:
            return "[]"
        parts = [_serialize_scalar_in_list(x) for x in v]
        return "[" + ", ".join(parts) + "]"
    return _serialize_scalar_top(v)


def _serialize_scalar_top(v: Any) -> str:
    s = str(v)
    # Dates and simple identifiers don't need quoting.
    if re.match(r"^\d{4}-\d{2}-\d{2}$", s) or re.match(r"^[a-z0-9_\-]+$", s, re.IGNORECASE):
        return s
    # If contains special chars, quote it.
    if any(ch in s for ch in ':#[]{},&*?|<>=!%@`'):
        return '"' + s.replace('"', '\\"') + '"'
    return s


def _serialize_scalar_in_list(v: Any) -> str:
    if isinstance(v, str) and (" " in v or "/" in v or "-" in v):
        # tags like `profissional/projeto` are fine unquoted; aliases with spaces fine too
        return v
    return _serialize_scalar_top(v)


def serialize_frontmatter(data: dict) -> str:
    # Preserve a stable field order so diffs are quiet.
    order = [
        "created", "updated", "area", "type", "status", "tags",
        "aliases", "source", "project", "confidence", "generated_by",
    ]
    out_lines = ["---"]
    seen = set()
    for k in order:
        if k in data:
            out_lines.append(f"{k}: {_serialize_value(data[k])}")
            seen.add(k)
    for k, v in data.items():
        if k in seen:
            continue
        out_lines.append(f"{k}: {_serialize_value(v)}")
    out_lines.append("---")
    return "\n".join(out_lines) + "\n"


# ---------- scanning ----------

@dataclass
class NoteRecord:
    path: pathlib.Path
    rel: pathlib.Path
    frontmatter: dict
    body: str
    mtime: float
    outgoing_links: list[str] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)


def find_vault_root(start: pathlib.Path) -> pathlib.Path:
    start = start.resolve()
    cur = start if start.is_dir() else start.parent
    while True:
        if (cur / MARKER_PATH).exists():
            return cur
        if cur.parent == cur:
            raise SystemExit(
                f"No obsidian-master vault found at or above {start}. "
                "Run /obsidian-master-kit:init first."
            )
        cur = cur.parent


def scan_vault(vault: pathlib.Path) -> list[NoteRecord]:
    records: list[NoteRecord] = []
    for p in vault.rglob("*.md"):
        rel = p.relative_to(vault)
        # Skip the _templates/ folder notes — those are templates, not live notes
        if "_templates" in rel.parts:
            continue
        text = p.read_text(encoding="utf-8")
        note = parse_markdown(text)
        # Adapter `(fm, body, errors)` para manter o shape historico do
        # librarian. `core.parser` nao reporta erros lexicais granulares;
        # quando o frontmatter esta ausente ou inteiramente invalido, sinaliza
        # `no frontmatter` igual a versao antiga.
        errors: list[str] = []
        if not note.frontmatter_dict and note.body == text:
            errors.append("no frontmatter")
        rec = NoteRecord(
            path=p,
            rel=rel,
            frontmatter=dict(note.frontmatter_dict),
            body=note.body,
            mtime=p.stat().st_mtime,
        )
        # Structural files have no schema contract. Record them (so _INDEX.md
        # can still show them) but don't flag frontmatter absence as an issue.
        if p.name not in STRUCTURAL_FILES:
            rec.issues.extend(errors)
        # v0.1.1 tratava embeds como links de saida (o regex antigo capturava
        # o `[[X]]` interno de `![[X]]`). Preserva esse comportamento juntando
        # wikilinks e embed targets — mantem detecao de orfas bit-identica.
        rec.outgoing_links = [w.target for w in note.wikilinks] + list(note.embeds)
        records.append(rec)
    return records


# ---------- auto-fix (safe categories only) ----------

AREA_FROM_PATH_ORDER = tuple(AREA_FOLDER_MAP.items())

def infer_area_from_path(rel: pathlib.Path) -> str | None:
    first = rel.parts[0] if rel.parts else ""
    return AREA_FOLDER_MAP.get(first)


def normalize_tag(tag: str) -> str:
    t = str(tag).strip().lstrip("#")
    t = re.sub(r"\s+", "-", t)
    return t.lower()


def autofix_record(rec: NoteRecord, today: str) -> dict:
    """Apply safe deterministic fixes. Returns a dict describing what changed."""
    changes = {"updated_added": False, "status_added": False,
               "tags_added": False, "tags_normalized": 0}
    fm = rec.frontmatter

    # Skip structural/meta files that don't carry note-schema contracts.
    if rec.rel.name in STRUCTURAL_FILES:
        return changes

    if "updated" not in fm or fm.get("updated") in (None, ""):
        fm["updated"] = today
        changes["updated_added"] = True

    if "status" not in fm or fm.get("status") in (None, ""):
        fm["status"] = "draft"
        changes["status_added"] = True

    if "tags" not in fm or fm.get("tags") in (None, ""):
        fm["tags"] = []
        changes["tags_added"] = True

    if isinstance(fm.get("tags"), list):
        new_tags = []
        for t in fm["tags"]:
            nt = normalize_tag(t)
            if nt != str(t).strip().lstrip("#"):
                changes["tags_normalized"] += 1
            if nt and nt not in new_tags:
                new_tags.append(nt)
        fm["tags"] = new_tags

    return changes


def write_note(rec: NoteRecord) -> None:
    fm_text = serialize_frontmatter(rec.frontmatter) if rec.frontmatter else ""
    rec.path.write_text(fm_text + rec.body if fm_text else rec.body, encoding="utf-8")


# ---------- semantic issue detection ----------

def detect_issues(rec: NoteRecord) -> dict:
    fm = rec.frontmatter
    issues = {
        "missing_fields": [],
        "invalid_area": None,
        "invalid_type": None,
        "invalid_status": None,
        "area_folder_mismatch": None,
        "orphan": False,
    }

    if rec.rel.name in STRUCTURAL_FILES:
        return issues

    for f in REQUIRED_FIELDS:
        if f not in fm or fm.get(f) in (None, ""):
            issues["missing_fields"].append(f)

    area = fm.get("area")
    if area and area not in CANONICAL_AREAS:
        issues["invalid_area"] = area

    type_ = fm.get("type")
    if type_ and type_ not in CANONICAL_TYPES:
        issues["invalid_type"] = type_

    status = fm.get("status")
    if status and status not in CANONICAL_STATUSES:
        issues["invalid_status"] = status

    inferred = infer_area_from_path(rec.rel)
    if area and inferred and area != inferred:
        issues["area_folder_mismatch"] = {"declared": area, "inferred": inferred}

    if not rec.outgoing_links:
        issues["orphan"] = True

    return issues


# ---------- index rewrite ----------

# Ordem canonica das 4 areas — usada tanto pelo caminho filesystem quanto DB.
_CANONICAL_AREAS_ORDERED = ("pessoal", "profissional", "pesquisa", "ai-memory")
_AREA_LABELS = {
    "pessoal": "Pessoal",
    "profissional": "Profissional",
    "pesquisa": "Pesquisas",
    "ai-memory": "Memória da IA",
}
# Inverso de AREA_FOLDER_MAP — slug canonico -> prefixo de path.
_AREA_SLUG_TO_FOLDER = {v: k for k, v in AREA_FOLDER_MAP.items()}


def _format_index(
    today: str,
    counts: dict[str, tuple[int, int]],
    recent: list[tuple[str, str, float]],
    mocs: list[tuple[str, str]],
    orphans: list[tuple[str, str]],
    projects: list[tuple[str, str]],
) -> str:
    """Serializa _INDEX.md a partir dos dados ja agregados.

    Shape dos parametros (estavel entre as 2 implementacoes filesystem/DB):
    - counts: {slug: (note_count, moc_count)}
    - recent: [(rel_no_ext, display_name, mtime), ...] — ja ordenado desc
    - mocs:   [(rel_no_ext, folder_label), ...]        — ja ordenado alfabetico
    - orphans:[(rel_no_ext, display_name), ...]        — ordem de iteracao
    - projects:[(rel_no_ext, display_name), ...]       — ordem de iteracao

    Qualquer mudanca de formato aqui afeta ambos os caminhos igualmente.
    """
    lines: list[str] = []
    lines.append("---")
    lines.append(f"created: {today}")
    lines.append(f"updated: {today}")
    lines.append("type: indice")
    lines.append("generated_by: obsidian-librarian")
    lines.append("---")
    lines.append("")
    lines.append("# _INDEX — Mapa vivo do vault")
    lines.append("")
    lines.append("> Este arquivo é mantido pelo `obsidian-librarian`. **Não edite à mão** — suas mudanças")
    lines.append("> serão sobrescritas na próxima sincronização. Para alterar regras ou doutrina, edite")
    lines.append("> o [[CLAUDE]].")
    lines.append("")
    lines.append(f"Última sincronização: {today}")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Áreas")
    lines.append("")
    lines.append("- [[00 - Pessoal/_MOC|Pessoal]]")
    lines.append("- [[01 - Profissional/_MOC|Profissional]]")
    lines.append("- [[02 - Pesquisas e Estudos/_MOC|Pesquisas e Estudos]]")
    lines.append("- [[03 - Memoria da IA/_MOC|Memória da IA]]")
    lines.append("")
    lines.append("## Contagem por área")
    lines.append("")
    lines.append("| Área | Notas | MOCs |")
    lines.append("|---|---|---|")
    for slug in _CANONICAL_AREAS_ORDERED:
        note_count, moc_count = counts.get(slug, (0, 0))
        lines.append(f"| {_AREA_LABELS[slug]} | {note_count} | {moc_count} |")
    lines.append("")

    lines.append("## Últimas 10 adições")
    lines.append("")
    if recent:
        for rel_no_ext, display_name, mtime in recent:
            lines.append(f"- [[{rel_no_ext}|{display_name}]] "
                         f"— {_dt.datetime.fromtimestamp(mtime).strftime('%Y-%m-%d')}")
    else:
        lines.append("_(Vazio ainda.)_")
    lines.append("")

    lines.append("## MOCs ativos")
    lines.append("")
    if mocs:
        for rel_no_ext, folder_label in mocs:
            lines.append(f"- [[{rel_no_ext}|MOC — {folder_label}]]")
    else:
        lines.append("_(Nenhum MOC encontrado.)_")
    lines.append("")

    lines.append("## Notas órfãs (sem wiki-links de saída)")
    lines.append("")
    if orphans:
        for rel_no_ext, display_name in orphans:
            lines.append(f"- [[{rel_no_ext}|{display_name}]]  ⚠️")
    else:
        lines.append("_(Nenhuma.)_")
    lines.append("")

    lines.append("## Projetos ativos")
    lines.append("")
    if projects:
        for rel_no_ext, display_name in projects:
            lines.append(f"- [[{rel_no_ext}|{display_name}]]")
    else:
        lines.append("_(Nenhum projeto ativo cadastrado.)_")
    lines.append("")

    return "\n".join(lines)


def _build_index_filesystem(
    vault: pathlib.Path, records: list[NoteRecord], today: str,
) -> str:
    """Versao legada: agrega a partir da lista de NoteRecord do scan_vault.

    Usada em vaults v0.1.1 (sem DB). Preserva comportamento bit-identico ao
    pre-wave-3.
    """
    by_area: dict[str, list[NoteRecord]] = {a: [] for a in CANONICAL_AREAS}
    mocs_records: list[NoteRecord] = []
    for r in records:
        if r.path.name == MOC_FILENAME:
            mocs_records.append(r)
        area = r.frontmatter.get("area") or infer_area_from_path(r.rel)
        if area in by_area:
            by_area[area].append(r)

    counts: dict[str, tuple[int, int]] = {}
    for slug in _CANONICAL_AREAS_ORDERED:
        bucket = by_area[slug]
        moc_count = sum(1 for n in bucket if n.path.name == MOC_FILENAME)
        note_count = len(bucket) - moc_count
        counts[slug] = (note_count, moc_count)

    # Sort com tie-breaker alfabetico pra determinismo (parity com DB version,
    # e imune a ordem de rglob variar entre FS/OS).
    relevant = [r for r in records if r.path.name not in STRUCTURAL_FILES]
    recent_records = sorted(relevant, key=lambda r: (-r.mtime, str(r.rel)))[:10]
    recent = [
        (str(r.rel.with_suffix("")), r.path.stem, r.mtime)
        for r in recent_records
    ]

    mocs_sorted = sorted(mocs_records, key=lambda r: str(r.rel))
    mocs = [
        (
            str(m.rel.with_suffix("")),
            str(m.rel.parent) if str(m.rel.parent) != "." else "root",
        )
        for m in mocs_sorted
    ]

    orphan_records = [
        r for r in records
        if not r.outgoing_links
        and r.path.name not in STRUCTURAL_FILES
        and r.path.name != MOC_FILENAME
    ]
    orphans = [
        (str(r.rel.with_suffix("")), r.path.stem)
        for r in sorted(orphan_records, key=lambda r: str(r.rel))
    ]

    project_records = [
        r for r in records
        if r.rel.parts[:2] == ("01 - Profissional", "Projetos")
        and r.path.name != MOC_FILENAME
    ]
    projects = [
        (str(r.rel.with_suffix("")), r.path.stem)
        for r in sorted(project_records, key=lambda r: str(r.rel))
    ]

    return _format_index(today, counts, recent, mocs, orphans, projects)


def _build_index_db(vault: pathlib.Path, conn, today: str) -> str:
    """Versao DB-backed: agrega via queries diretas em notes/areas/links.

    PRIVACIDADE (doutrina Q4, wave 3):
    - Notes com `sensitive=1`: EXCLUIDAS de "Ultimas 10", "Orfas", "Projetos
      ativos" (listagens title-visible). Mantidas em "Contagem por area"
      (agregado, sem titulo vazando).
    - Areas com `sensitive=1`: linha da area zera contagem na tabela (bias:
      esconder informacao quantitativa mas manter a estrutura canonica das 4
      areas, pq o _format_index espera essas 4 linhas). Se wave 4+ decidir
      ocultar a linha inteira, _format_index precisa aceitar areas dinamicas.
    - MOCs: sempre incluidos. Sao estruturais/publicos por design.

    AREA BUCKETING: replica a logica do filesystem version — frontmatter.area
    (se canonico) tem precedencia sobre path inference. Motivo: parity
    bit-identica com vaults que usam slugs nao-canonicos no frontmatter (ex:
    `memoria-ia` em vez de `ai-memory`). O filesystem version dropa essas
    notas do by_area bucket; a DB version precisa fazer igual.

    Performance: 4 queries pequenas, uma unica leitura (sqlite3 autocommit,
    sem begin implicito de write txn). Target <200ms em 2k notas.
    `idx_notes_mtime` cobre o ORDER BY da query de recentes.
    """
    # -- schema introspection: detecta se coluna `sensitive`/`pagerank`
    # existe (v0.1.1 DBs pre-migration 001 podem nao ter). Ausente => 0.
    note_cols = {row[1] for row in conn.execute("PRAGMA table_info(notes)")}
    area_cols = {row[1] for row in conn.execute("PRAGMA table_info(areas)")}
    note_sensitive_expr = "n.sensitive" if "sensitive" in note_cols else "0"
    has_pagerank = "pagerank" in note_cols

    # -- set de areas sensitive (linha zerada na tabela de contagem)
    sensitive_area_folders: set[str] = set()
    if "sensitive" in area_cols:
        for row in conn.execute(
            "SELECT folder FROM areas WHERE sensitive = 1 AND folder IS NOT NULL"
        ):
            if row[0]:
                sensitive_area_folders.add(row[0])

    # -- Carrega todas as notas ativas (path, frontmatter_json). Replicar
    # bucketing filesystem-style (frontmatter.area CANONICAL > path inference)
    # em SQL puro nao daria pra suportar sem duplicar o parser; iterar em
    # Python e aceitavel pro scale alvo (<5k notas). Uma query single-pass.
    all_rows = conn.execute(
        """
        SELECT path, frontmatter_json FROM notes
        WHERE deleted_at IS NULL
          AND path NOT LIKE '%/_templates/%'
        """
    ).fetchall()

    counts: dict[str, tuple[int, int]] = {s: (0, 0) for s in _CANONICAL_AREAS_ORDERED}
    for path, fm_json in all_rows:
        basename = path.rsplit("/", 1)[-1] if "/" in path else path
        # Replica EXATAMENTE a logica filesystem (quirk incluso):
        #   area = frontmatter.get("area") or infer_area_from_path(rel)
        # O `or` do Python faz short-circuit em truthy. Se frontmatter tem
        # `area: memoria-ia` (nao canonico, mas truthy), path inference nao
        # dispara, e a nota nao entra em nenhum bucket canonico. Preservado
        # aqui pra byte-parity; Epic 02 (migrate) deve corrigir o frontmatter
        # dessas notas.
        fm_area: str | None = None
        if fm_json:
            try:
                fm = json.loads(fm_json)
                v = fm.get("area")
                if isinstance(v, str) and v:
                    fm_area = v
            except (json.JSONDecodeError, TypeError):
                pass
        if fm_area:
            area = fm_area  # short-circuit — mesmo que invalido
        else:
            first = path.split("/", 1)[0] if "/" in path else ""
            area = AREA_FOLDER_MAP.get(first)
        if area not in _CANONICAL_AREAS_ORDERED:
            continue  # sem bucket canonico — nao conta (parity com filesystem)
        folder = _AREA_SLUG_TO_FOLDER[area]
        if folder in sensitive_area_folders:
            continue  # area sensitive: contagem suprimida (mantem (0,0))
        note_count, moc_count = counts[area]
        if basename == MOC_FILENAME:
            moc_count += 1
        else:
            note_count += 1
        counts[area] = (note_count, moc_count)

    # -- Ultimas 10 adicoes: mtime DESC, path ASC (tie-breaker deterministico).
    # Exclui structural files (basename match) + sensitive. MOCs podem
    # aparecer (parity com filesystem).
    structural_filter = " AND ".join(
        f"substr(n.path, -{len(name) + 1}) != '/{name}' AND n.path != '{name}'"
        for name in STRUCTURAL_FILES
    )
    recent_rows = conn.execute(
        f"""
        SELECT n.path, n.mtime
        FROM notes n
        WHERE n.deleted_at IS NULL
          AND {note_sensitive_expr} = 0
          AND {structural_filter}
          AND n.path NOT LIKE '%/_templates/%'
          AND n.mtime IS NOT NULL
        ORDER BY n.mtime DESC, n.path ASC
        LIMIT 10
        """
    ).fetchall()
    recent: list[tuple[str, str, float]] = []
    for path, mtime in recent_rows:
        stem = path.rsplit("/", 1)[-1][:-3] if path.endswith(".md") else path.rsplit("/", 1)[-1]
        rel_no_ext = path[:-3] if path.endswith(".md") else path
        recent.append((rel_no_ext, stem, float(mtime)))

    # -- MOCs ativos: basename literal `_MOC.md` (8 chars com `/` prefix) OU
    # pagerank > threshold (se coluna existe). Sempre incluidos (nao filtra
    # sensitive). Sort por path (parity com filesystem).
    moc_suffix_len = len("/" + MOC_FILENAME)  # 8
    if has_pagerank:
        moc_rows = conn.execute(
            f"""
            SELECT n.path
            FROM notes n
            WHERE n.deleted_at IS NULL
              AND n.path NOT LIKE '%/_templates/%'
              AND (
                n.path = '{MOC_FILENAME}'
                OR substr(n.path, -{moc_suffix_len}) = '/{MOC_FILENAME}'
                OR (n.pagerank IS NOT NULL AND n.pagerank > ?)
              )
            ORDER BY n.path
            """,
            (0.02,),
        ).fetchall()
    else:
        moc_rows = conn.execute(
            f"""
            SELECT n.path
            FROM notes n
            WHERE n.deleted_at IS NULL
              AND n.path NOT LIKE '%/_templates/%'
              AND (
                n.path = '{MOC_FILENAME}'
                OR substr(n.path, -{moc_suffix_len}) = '/{MOC_FILENAME}'
              )
            ORDER BY n.path
            """
        ).fetchall()
    mocs: list[tuple[str, str]] = []
    for (path,) in moc_rows:
        rel_no_ext = path[:-3] if path.endswith(".md") else path
        if "/" in path:
            folder_label = path.rsplit("/", 1)[0]
        else:
            folder_label = "root"
        mocs.append((rel_no_ext, folder_label))

    # -- Orfas: sem link de saida, nao-structural, nao-MOC, nao-sensitive,
    # nao-templates. LEFT JOIN + IS NULL = "no matching outgoing link row".
    # Sort por path (parity e determinismo).
    orphan_rows = conn.execute(
        f"""
        SELECT n.path
        FROM notes n
        LEFT JOIN links l ON l.from_note_id = n.id
        WHERE l.id IS NULL
          AND n.deleted_at IS NULL
          AND {note_sensitive_expr} = 0
          AND n.path NOT LIKE '%/_templates/%'
          AND {structural_filter}
          AND substr(n.path, -{moc_suffix_len}) != '/{MOC_FILENAME}'
          AND n.path != '{MOC_FILENAME}'
        ORDER BY n.path
        """
    ).fetchall()
    orphans: list[tuple[str, str]] = []
    for (path,) in orphan_rows:
        stem = path.rsplit("/", 1)[-1][:-3] if path.endswith(".md") else path.rsplit("/", 1)[-1]
        rel_no_ext = path[:-3] if path.endswith(".md") else path
        orphans.append((rel_no_ext, stem))

    # -- Projetos ativos: prefixo `01 - Profissional/Projetos/`, nao-MOC,
    # nao-sensitive. Se a area 01 - Profissional for sensitive, skip all.
    projects: list[tuple[str, str]] = []
    if "01 - Profissional" not in sensitive_area_folders:
        project_rows = conn.execute(
            f"""
            SELECT n.path
            FROM notes n
            WHERE n.deleted_at IS NULL
              AND {note_sensitive_expr} = 0
              AND n.path LIKE '01 - Profissional/Projetos/%'
              AND substr(n.path, -{moc_suffix_len}) != '/{MOC_FILENAME}'
              AND n.path != '{MOC_FILENAME}'
            ORDER BY n.path
            """
        ).fetchall()
        for (path,) in project_rows:
            stem = path.rsplit("/", 1)[-1][:-3] if path.endswith(".md") else path.rsplit("/", 1)[-1]
            rel_no_ext = path[:-3] if path.endswith(".md") else path
            projects.append((rel_no_ext, stem))

    return _format_index(today, counts, recent, mocs, orphans, projects)


def build_index(
    vault: pathlib.Path,
    records: list[NoteRecord],
    today: str,
    *,
    conn: object | None = None,
) -> str:
    """Dispatch top-level: DB se disponivel, filesystem senao (v0.1.1 vault).

    O caller passa `conn` quando o DB foi aberto com sucesso mais cedo na
    run. Em qualquer falha do caminho DB (exception na query, schema
    missing), cai de volta pra filesystem — _INDEX.md NUNCA fica vazio por
    conta de DB flakeness.
    """
    if conn is not None:
        try:
            return _build_index_db(vault, conn, today)
        except Exception:
            # DB defect nao pode derrubar geracao do index. Filesystem sempre
            # funciona pq records ja foi computado. Erro vai ser visivel no
            # caller via report["db_error"] se acontecer durante emissao de
            # events; aqui silenciamos pq a saida filesystem eh fallback
            # legitimo.
            pass
    return _build_index_filesystem(vault, records, today)


# ---------- events (S02) ----------

# Dedup window: skip scan_run events inserted within the last N seconds.
# Justificativa: hook PostToolUse pode racear com /sync manual disparando 2 scans
# redundantes quase-simultaneos. 60s cobre esse caso sem mascarar atividade
# legitima.
#
# IMPORTANTE: dedup aplica SO a scan_run. Outros event types tem unicidade
# natural dentro de um unico scan (note_* = 1 por nota por scan, link_* = 1 por
# edge-diff por scan), entao dedup (event_type, note_id) colapsaria erroneamente
# multiplos link_added/removed de uma mesma nota em 1 so evento.
_DEDUP_WINDOW_S = 60


def _insert_event(
    conn,
    *,
    event_type: str,
    note_id: int | None = None,
    area_id: int | None = None,
    word_delta: int | None = None,
    metadata: dict | None = None,
    emitted_counts: Counter | None = None,
) -> bool:
    """Insert row em events. Retorna True se inseriu, False se skip por dedup.

    Dedup: aplica APENAS a scan_run (race hook x manual /sync). Para note_*/
    link_*/etc a unicidade e natural (scanner itera cada nota 1x, snapshot-diff
    e edge-granular), entao emitimos sem checar.

    CAUTION: NAO usamos `datetime('now', '-60 seconds')` como cutoff pq o
    SQLite retorna com separador espaco (`2026-04-15 22:00:00`) e nosso ts
    e ISO-8601 com T (`2026-04-15T22:00:00+00:00`). Comparacao lexical de
    `T` (0x54) > espaco (0x20) quebraria o dedup mascarando tudo como
    "recente". Computamos o cutoff em Python com o mesmo formato.
    """
    now_dt = _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0)
    if event_type == "scan_run":
        cutoff_ts = (now_dt - _dt.timedelta(seconds=_DEDUP_WINDOW_S)).isoformat()
        existing = conn.execute(
            "SELECT 1 FROM events WHERE event_type='scan_run' AND ts > ? LIMIT 1",
            (cutoff_ts,),
        ).fetchone()
        if existing is not None:
            return False

    ts = now_dt.isoformat()
    date = ts[:10]
    meta_json = json.dumps(metadata, ensure_ascii=False) if metadata else None
    conn.execute(
        "INSERT INTO events (note_id, area_id, event_type, ts, date, word_delta, "
        "metadata_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (note_id, area_id, event_type, ts, date, word_delta, meta_json),
    )
    if emitted_counts is not None:
        emitted_counts[event_type] += 1
    return True


def _snapshot_links(conn) -> set[tuple[int, str]]:
    """Snapshot do set (from_note_id, to_target) pra diff pre/post-scan."""
    return {
        (int(row[0]), row[1])
        for row in conn.execute("SELECT from_note_id, to_target FROM links")
    }


def _note_area_and_path(conn, note_id: int) -> tuple[int | None, str | None]:
    row = conn.execute(
        "SELECT area_id, path FROM notes WHERE id=?", (note_id,)
    ).fetchone()
    if row is None:
        return None, None
    return (int(row[0]) if row[0] is not None else None), row[1]


def _emit_scan_events(
    conn,
    scan_report,
    links_before: set[tuple[int, str]],
    *,
    triggered_by: str,
) -> dict[str, int]:
    """Emite scan_run + note_* + link_* events. Retorna contagem por tipo.

    Commit fica por conta do caller (uma unica transacao pro bloco inteiro).
    """
    emitted: Counter[str] = Counter()

    # scan_run — sempre 1 por invocacao (dedup pode pular em hook racey)
    _insert_event(
        conn, event_type="scan_run", metadata={"triggered_by": triggered_by},
        emitted_counts=emitted,
    )

    # note_* events
    for change in scan_report.changes:
        if change.kind == "skipped" or change.note_id is None:
            continue
        area_id, _path = _note_area_and_path(conn, change.note_id)
        if change.kind == "created":
            _insert_event(
                conn, event_type="note_created", note_id=change.note_id,
                area_id=area_id, word_delta=change.word_delta,
                emitted_counts=emitted,
            )
        elif change.kind == "updated":
            _insert_event(
                conn, event_type="note_updated", note_id=change.note_id,
                area_id=area_id, word_delta=change.word_delta,
                emitted_counts=emitted,
            )
        elif change.kind == "deleted":
            _insert_event(
                conn, event_type="note_deleted", note_id=change.note_id,
                area_id=area_id, emitted_counts=emitted,
            )

    # link_* events — diff snapshot pre/post
    links_after = _snapshot_links(conn)
    added = links_after - links_before
    removed = links_before - links_after
    for from_note_id, to_target in added:
        area_id, from_path = _note_area_and_path(conn, from_note_id)
        _insert_event(
            conn, event_type="link_added", note_id=from_note_id,
            area_id=area_id,
            metadata={"from_note": from_path, "to_target": to_target},
            emitted_counts=emitted,
        )
    for from_note_id, to_target in removed:
        area_id, from_path = _note_area_and_path(conn, from_note_id)
        _insert_event(
            conn, event_type="link_removed", note_id=from_note_id,
            area_id=area_id,
            metadata={"from_note": from_path, "to_target": to_target},
            emitted_counts=emitted,
        )

    conn.commit()
    return dict(emitted)


def _open_db_if_available(vault: pathlib.Path) -> tuple[object | None, str | None]:
    """Tenta abrir `core.db.connect(vault)`. Retorna (conn, reason_if_failed).

    Retorna `(None, "<motivo>")` em TODOS os casos de falha (db nao existe,
    import error, schema nao aplicavel, etc). Nunca crasheia — script tem
    que funcionar em vaults v0.1.1 sem DB.
    """
    db_path = vault / ".obsidian-master" / "db.sqlite"
    if not db_path.exists():
        return None, "db file not present (v0.1.1 vault)"
    try:
        _core_db = _load_core_module("db", "db.py")
        conn = _core_db.connect(vault)
        return conn, None
    except Exception as exc:  # pragma: no cover — depende do ambiente
        return None, f"{type(exc).__name__}: {exc}"


# ---------- main ----------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Scan an obsidian-master-kit vault, auto-fix safe frontmatter issues, "
                    "rewrite _INDEX.md, and emit a JSON report of semantic issues.",
    )
    parser.add_argument("--vault", default=".", help="Vault root (auto-detected if inside)")
    parser.add_argument("--no-apply", action="store_true",
                        help="Don't write fixes or rewrite _INDEX.md; just report.")
    parser.add_argument("--quiet", action="store_true", help="Suppress non-JSON output.")
    parser.add_argument("--init", action="store_true",
                        help="Mark this as the first scan after vault init. Emitted "
                             "scan_run event carries triggered_by='init'.")

    args = parser.parse_args(argv)

    start = pathlib.Path(args.vault).expanduser().resolve()
    vault = find_vault_root(start)

    today = _dt.date.today().isoformat()
    now_iso = _dt.datetime.now().isoformat(timespec="seconds")

    # --- triggered_by detection (S02) ---
    # Precedencia: --init flag > UPDATE_INDEX_TRIGGER env > "manual" default.
    # Hook (wave S05) passa env var; manual /sync nao passa nada; --init
    # so e passado pelo init skill na primeira execucao.
    if args.init:
        triggered_by = "init"
    else:
        triggered_by = os.environ.get("UPDATE_INDEX_TRIGGER", "manual")

    records = scan_vault(vault)

    fixes_summary = Counter()
    for rec in records:
        # protected: true — indexar apenas, nunca modificar o arquivo.
        if rec.frontmatter.get("protected") is True:
            continue
        changes = autofix_record(rec, today)
        for k, v in changes.items():
            if isinstance(v, bool) and v:
                fixes_summary[k] += 1
            elif isinstance(v, int):
                fixes_summary[k] += v
        if not args.no_apply and any(
            (isinstance(v, bool) and v) or (isinstance(v, int) and v > 0)
            for v in changes.values()
        ):
            write_note(rec)
            # Refresh mtime apos autofix pra que "Ultimas 10 adicoes" no
            # filesystem path reflita o mesmo snapshot que o DB path (que
            # re-escaneia depois do autofix). Sem isso, as duas versoes
            # divergem em vaults onde autofix mexeu no disco.
            rec.mtime = rec.path.stat().st_mtime

    # Detect semantic issues after autofix
    report = {
        "updated_index": False,
        "notes_scanned": len(records),
        "orphans": [],
        "missing_frontmatter_fields": [],
        "invalid_frontmatter": [],
        "unknown_area": [],
        "unknown_type": [],
        "unknown_status": [],
        "area_folder_mismatch": [],
        "auto_fixed": dict(fixes_summary),
        "last_sync": now_iso,
        "db_available": False,
        "events_emitted": {},
        "scan_duration_s": None,
    }

    for rec in records:
        # protected: true — indexar apenas, nao reportar issues.
        if rec.frontmatter.get("protected") is True:
            continue
        if rec.issues:
            report["invalid_frontmatter"].append(
                {"file": str(rec.rel), "errors": rec.issues}
            )
        issues = detect_issues(rec)
        if issues["missing_fields"]:
            report["missing_frontmatter_fields"].append(
                {"file": str(rec.rel), "missing": issues["missing_fields"]}
            )
        if issues["invalid_area"]:
            report["unknown_area"].append(
                {"file": str(rec.rel), "area": issues["invalid_area"]}
            )
        if issues["invalid_type"]:
            report["unknown_type"].append(
                {"file": str(rec.rel), "type": issues["invalid_type"]}
            )
        if issues["invalid_status"]:
            report["unknown_status"].append(
                {"file": str(rec.rel), "status": issues["invalid_status"]}
            )
        if issues["area_folder_mismatch"]:
            report["area_folder_mismatch"].append(
                {"file": str(rec.rel), **issues["area_folder_mismatch"]}
            )
        if issues["orphan"]:
            report["orphans"].append(str(rec.rel))

    # --- DB-backed scan + events (S02) ---
    # Precisa rodar apos autofix (pra que mtimes/body_hash refletem o estado
    # final das notas) e ANTES do rewrite de _INDEX.md (pra nao poluir o
    # scan com a propria saida do librarian). Em vaults v0.1.1 sem DB, ou
    # em `--no-apply`, fica None e pula o bloco inteiro.
    conn = None
    db_reason = None
    if not args.no_apply:
        conn, db_reason = _open_db_if_available(vault)
    # conn_for_index: usado em build_index so se scan+events rodaram sem
    # exception. Se quebrou no meio, cai no filesystem fallback (seguro).
    conn_for_index: object | None = None
    if conn is not None:
        report["db_available"] = True
        try:
            _core_scanner = _load_core_module("scanner", "scanner.py")
            links_before = _snapshot_links(conn)
            scan_report = _core_scanner.scan(conn, vault)
            report["scan_duration_s"] = round(scan_report.duration_s, 4)
            emitted = _emit_scan_events(
                conn, scan_report, links_before, triggered_by=triggered_by,
            )
            report["events_emitted"] = emitted
            # Sucesso — conn eh confiavel pra build_index usar (S03).
            conn_for_index = conn
        except Exception as exc:
            # Nao abortamos o script — DB pode ter qualquer bug transient.
            # Reporta o motivo, mas continua pro path de _INDEX.md (fallback
            # filesystem via conn_for_index=None).
            report["db_error"] = f"{type(exc).__name__}: {exc}"
    elif db_reason is not None:
        report["db_unavailable_reason"] = db_reason

    try:
        if not args.no_apply:
            t0 = _dt.datetime.now()
            index_text = build_index(vault, records, today, conn=conn_for_index)
            report["index_build_ms"] = int(
                (_dt.datetime.now() - t0).total_seconds() * 1000
            )
            (vault / INDEX_FILENAME).write_text(index_text, encoding="utf-8")
            (vault / ".obsidian-master" / "last-sync.json").write_text(
                json.dumps({"last_sync": now_iso, "notes_scanned": len(records),
                            "fixes": dict(fixes_summary)}, indent=2) + "\n",
                encoding="utf-8",
            )
            report["updated_index"] = True
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

    sys.stdout.write(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
