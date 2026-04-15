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
import pathlib
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

# Reuso do parser canonico de Epic 01 (`core.parser.parse_markdown`).
# Carregamos o submodulo direto via importlib, sem passar pelo package
# `core/__init__.py` — esse ultimo puxa networkx/model2vec/sqlite-vec, e o
# librarian historicamente e stdlib-only (pode rodar em vaults v0.1.1 sem
# as deps pesadas instaladas). `core.parser` depende so de stdlib, entao
# esse import isolado e seguro.
import importlib.util as _ilu  # noqa: E402

_CORE_PARSER_PATH = pathlib.Path(__file__).resolve().parents[3] / "core" / "parser.py"
_spec = _ilu.spec_from_file_location("_obm_core_parser", _CORE_PARSER_PATH)
if _spec is None or _spec.loader is None:
    raise SystemExit(f"core/parser.py nao encontrado em {_CORE_PARSER_PATH}")
_core_parser = _ilu.module_from_spec(_spec)
# Registra no sys.modules antes do exec: @dataclass precisa resolver
# cls.__module__ em sys.modules durante a decoracao.
sys.modules["_obm_core_parser"] = _core_parser
_spec.loader.exec_module(_core_parser)
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

def build_index(vault: pathlib.Path, records: list[NoteRecord], today: str) -> str:
    by_area: dict[str, list[NoteRecord]] = {a: [] for a in CANONICAL_AREAS}
    mocs: list[NoteRecord] = []
    for r in records:
        if r.path.name == MOC_FILENAME:
            mocs.append(r)
        area = r.frontmatter.get("area") or infer_area_from_path(r.rel)
        if area in by_area:
            by_area[area].append(r)

    # Last 10 modified (excluding structural meta files)
    relevant = [r for r in records if r.path.name not in STRUCTURAL_FILES]
    recent = sorted(relevant, key=lambda r: r.mtime, reverse=True)[:10]

    # Orphans (ignore structural files and MOCs — those are expected to vary)
    orphans = [
        r for r in records
        if not r.outgoing_links
        and r.path.name not in STRUCTURAL_FILES
        and r.path.name != MOC_FILENAME
    ]

    # Project files
    projects = [
        r for r in records
        if r.rel.parts[:2] == ("01 - Profissional", "Projetos")
        and r.path.name != MOC_FILENAME
    ]

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
    for area in ("pessoal", "profissional", "pesquisa", "ai-memory"):
        notes = by_area[area]
        moc_count = sum(1 for n in notes if n.path.name == MOC_FILENAME)
        note_count = len(notes) - moc_count
        label = {"pessoal": "Pessoal", "profissional": "Profissional",
                 "pesquisa": "Pesquisas", "ai-memory": "Memória da IA"}[area]
        lines.append(f"| {label} | {note_count} | {moc_count} |")
    lines.append("")

    lines.append("## Últimas 10 adições")
    lines.append("")
    if recent:
        for r in recent:
            display_name = r.path.stem
            lines.append(f"- [[{r.rel.with_suffix('')}|{display_name}]] "
                         f"— {_dt.datetime.fromtimestamp(r.mtime).strftime('%Y-%m-%d')}")
    else:
        lines.append("_(Vazio ainda.)_")
    lines.append("")

    lines.append("## MOCs ativos")
    lines.append("")
    if mocs:
        for m in sorted(mocs, key=lambda r: str(r.rel)):
            rel_no_ext = m.rel.with_suffix("")
            label = str(m.rel.parent) if str(m.rel.parent) != "." else "root"
            lines.append(f"- [[{rel_no_ext}|MOC — {label}]]")
    else:
        lines.append("_(Nenhum MOC encontrado.)_")
    lines.append("")

    lines.append("## Notas órfãs (sem wiki-links de saída)")
    lines.append("")
    if orphans:
        for o in orphans:
            lines.append(f"- [[{o.rel.with_suffix('')}|{o.path.stem}]]  ⚠️")
    else:
        lines.append("_(Nenhuma.)_")
    lines.append("")

    lines.append("## Projetos ativos")
    lines.append("")
    if projects:
        for p in projects:
            rel_no_ext = p.rel.with_suffix("")
            lines.append(f"- [[{rel_no_ext}|{p.path.stem}]]")
    else:
        lines.append("_(Nenhum projeto ativo cadastrado.)_")
    lines.append("")

    return "\n".join(lines)


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

    args = parser.parse_args(argv)

    start = pathlib.Path(args.vault).expanduser().resolve()
    vault = find_vault_root(start)

    today = _dt.date.today().isoformat()
    now_iso = _dt.datetime.now().isoformat(timespec="seconds")

    records = scan_vault(vault)

    fixes_summary = Counter()
    for rec in records:
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
    }

    for rec in records:
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

    if not args.no_apply:
        index_text = build_index(vault, records, today)
        (vault / INDEX_FILENAME).write_text(index_text, encoding="utf-8")
        (vault / ".obsidian-master" / "last-sync.json").write_text(
            json.dumps({"last_sync": now_iso, "notes_scanned": len(records),
                        "fixes": dict(fixes_summary)}, indent=2) + "\n",
            encoding="utf-8",
        )
        report["updated_index"] = True

    sys.stdout.write(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
