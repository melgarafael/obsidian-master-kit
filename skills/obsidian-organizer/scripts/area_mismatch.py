"""area_mismatch.py — detecta frontmatter.area != pasta (Epic 04 S05 / Wave 5).

Pra cada nota ativa com `frontmatter_json.area` preenchido, compara com
o slug da area esperada pela pasta raiz (via AREA_FOLDER_MAP canonico).
Se diverge, reporta como candidato a correcao.

Falsos positivos sao filtrados:
- Notas na raiz (sem prefixo de area canonico) sao ignoradas
- Notas sem `area` no frontmatter sao ignoradas
"""
from __future__ import annotations

import datetime as _dt
import json
import pathlib
import sqlite3
from typing import Any

from core.config import SUGGESTIONS_TTL_DAYS

__all__ = ["detect_mismatches", "save_suggestions"]


AREA_FOLDER_MAP = {
    "00 - Pessoal": "pessoal",
    "01 - Profissional": "profissional",
    "02 - Pesquisas e Estudos": "pesquisa",
    "03 - Memoria da IA": "ai-memory",
}


def _infer_expected_area(note_path: str) -> str | None:
    """Do path relativo da nota, infere a area esperada pela pasta raiz."""
    parts = pathlib.PurePosixPath(note_path).parts
    if not parts or len(parts) < 2:
        return None
    return AREA_FOLDER_MAP.get(parts[0])


def detect_mismatches(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Retorna lista de notas com area declarada != area esperada pela pasta."""
    rows = conn.execute(
        """
        SELECT id, path, title, frontmatter_json
        FROM notes
        WHERE deleted_at IS NULL
          AND (status IS NULL OR status != 'arquivado')
          AND frontmatter_json IS NOT NULL
        """
    ).fetchall()
    results: list[dict[str, Any]] = []
    for nid, path, title, fm_json in rows:
        try:
            fm = json.loads(fm_json) if fm_json else {}
        except (json.JSONDecodeError, TypeError):
            continue
        declared = fm.get("area")
        if not declared or not isinstance(declared, str):
            continue
        expected = _infer_expected_area(path)
        if expected is None:
            continue
        if declared.lower() == expected.lower():
            continue
        results.append(
            {
                "note_id": nid,
                "path": path,
                "title": title,
                "declared_area": declared,
                "expected_area": expected,
                "reasoning": (
                    f"Nota '{title or pathlib.Path(path).stem}' esta em '{path}' "
                    f"(area esperada: {expected}) mas frontmatter declara "
                    f"area: {declared}. Divergencia precisa de verdict humano."
                ),
            }
        )
    return results


def save_suggestions(conn: sqlite3.Connection, mismatches: list[dict[str, Any]]) -> int:
    if not mismatches:
        return 0
    now = _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0)
    exp = now + _dt.timedelta(days=SUGGESTIONS_TTL_DAYS)
    n = 0
    for m in mismatches:
        # Dedup: nao regravar se ja existe suggestion ativa pra essa nota
        existing = conn.execute(
            """
            SELECT 1 FROM suggestions_cache
            WHERE kind = 'area_mismatch'
              AND dismissed = 0 AND acted_on = 0
              AND target_note_ids = ?
            LIMIT 1
            """,
            (json.dumps([m["note_id"]]),),
        ).fetchone()
        if existing:
            continue
        conn.execute(
            """
            INSERT INTO suggestions_cache
              (generated_at, expires_at, kind, target_note_ids,
               content, reasoning, score, dismissed, acted_on)
            VALUES (?, ?, 'area_mismatch', ?, ?, ?, ?, 0, 0)
            """,
            (
                now.isoformat(),
                exp.isoformat(),
                json.dumps([m["note_id"]]),
                f"Area mismatch: {m['declared_area']} vs {m['expected_area']}",
                m["reasoning"],
                0.4,
            ),
        )
        n += 1
    conn.commit()
    return n
