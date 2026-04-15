"""moc_audit.py — MOC detection (Epic 04 S04 / Wave 4).

Pra cada cluster com `note_count >= MOC_AUDIT_MIN_CLUSTER_NOTES` do
ultimo run, verifica se alguma nota do cluster e MOC
(type='moc' OR path termina em `_MOC.md`).

Se nao, grava suggestion `kind='moc_missing'` em `suggestions_cache`
com `reasoning` humano-legivel e target_note_ids=[ids do cluster ate cap].

Opcionalmente, `--create-suggestions` gera stub `.md` em pasta
apropriada com wikilinks pras notas do cluster, `status: draft` e
`generated_by: obsidian-organizer`.
"""
from __future__ import annotations

import datetime as _dt
import json
import pathlib
import sqlite3
from typing import Any

from core.config import (
    MOC_AUDIT_MIN_CLUSTER_NOTES,
    SUGGESTIONS_TTL_DAYS,
)

__all__ = ["audit_mocs", "create_moc_stub"]


_AREA_FOLDER_MAP = {
    "pessoal": "00 - Pessoal",
    "profissional": "01 - Profissional",
    "pesquisa": "02 - Pesquisas e Estudos",
    "ai-memory": "03 - Memoria da IA",
}


def _latest_run_id(conn: sqlite3.Connection) -> str | None:
    row = conn.execute(
        "SELECT run_id FROM clusters ORDER BY created_at DESC LIMIT 1"
    ).fetchone()
    return row[0] if row else None


def _cluster_has_moc(conn: sqlite3.Connection, cluster_id: int) -> bool:
    row = conn.execute(
        """
        SELECT 1 FROM cluster_notes cn
        JOIN notes n ON n.id = cn.note_id
        WHERE cn.cluster_id = ?
          AND (n.type = 'moc' OR n.path LIKE '%\\_MOC.md' ESCAPE '\\')
        LIMIT 1
        """,
        (cluster_id,),
    ).fetchone()
    return row is not None


def _cluster_notes(
    conn: sqlite3.Connection, cluster_id: int
) -> list[tuple[int, str, str | None]]:
    return [
        (r[0], r[1], r[2])
        for r in conn.execute(
            """
            SELECT n.id, n.path, n.title FROM cluster_notes cn
            JOIN notes n ON n.id = cn.note_id
            WHERE cn.cluster_id = ? AND n.deleted_at IS NULL
            """,
            (cluster_id,),
        ).fetchall()
    ]


def _already_suggested(conn: sqlite3.Connection, cluster_id: int) -> bool:
    """Checa se ja existe suggestion moc_missing ativa pra esse cluster.

    Usamos marker no content '[cluster_id=N]' pra rastrear.
    """
    row = conn.execute(
        """
        SELECT 1 FROM suggestions_cache
        WHERE kind = 'moc_missing'
          AND dismissed = 0
          AND acted_on = 0
          AND content LIKE ?
        LIMIT 1
        """,
        (f"%[cluster_id={cluster_id}]%",),
    ).fetchone()
    return row is not None


def audit_mocs(
    conn: sqlite3.Connection,
    *,
    run_id: str | None = None,
    min_notes: int | None = None,
) -> list[dict[str, Any]]:
    """Retorna lista de sugestoes 'moc_missing' geradas. Nao escreve ainda."""
    threshold = MOC_AUDIT_MIN_CLUSTER_NOTES if min_notes is None else min_notes
    rid = run_id or _latest_run_id(conn)
    if rid is None:
        return []
    rows = conn.execute(
        """
        SELECT id, label, note_count, proposed_area_id
        FROM clusters WHERE run_id = ? AND note_count >= ?
        ORDER BY note_count DESC
        """,
        (rid, threshold),
    ).fetchall()
    results: list[dict[str, Any]] = []
    for cid, label, ncount, area_id in rows:
        if _cluster_has_moc(conn, cid):
            continue
        if _already_suggested(conn, cid):
            continue
        cnotes = _cluster_notes(conn, cid)
        if not cnotes:
            continue
        titles = [t or pathlib.Path(p).stem for _, p, t in cnotes[:5]]
        titles_preview = ", ".join(f"[[{t}]]" for t in titles)
        if len(cnotes) > 5:
            titles_preview += ", ..."
        reasoning = (
            f"Cluster '{label}' tem {ncount} notas mas nenhuma e MOC. "
            f"Notas incluem: {titles_preview}."
        )
        content = f"MOC faltando pro cluster '{label}' [cluster_id={cid}]."
        results.append(
            {
                "cluster_id": cid,
                "cluster_label": label,
                "note_count": ncount,
                "note_ids": [nid for nid, _, _ in cnotes],
                "content": content,
                "reasoning": reasoning,
                "proposed_area_id": area_id,
            }
        )
    return results


def save_suggestions(conn: sqlite3.Connection, proposals: list[dict[str, Any]]) -> int:
    if not proposals:
        return 0
    now = _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0)
    exp = now + _dt.timedelta(days=SUGGESTIONS_TTL_DAYS)
    n = 0
    for p in proposals:
        conn.execute(
            """
            INSERT INTO suggestions_cache
              (generated_at, expires_at, kind, target_note_ids,
               content, reasoning, score, dismissed, acted_on)
            VALUES (?, ?, 'moc_missing', ?, ?, ?, ?, 0, 0)
            """,
            (
                now.isoformat(),
                exp.isoformat(),
                json.dumps(p["note_ids"][:20]),
                p["content"],
                p["reasoning"],
                min(1.0, p["note_count"] / 50.0),
            ),
        )
        n += 1
    conn.commit()
    return n


def create_moc_stub(
    vault: pathlib.Path,
    proposal: dict[str, Any],
    conn: sqlite3.Connection,
) -> pathlib.Path:
    """Cria `.md` stub de MOC pra cluster. Retorna path absoluto do arquivo."""
    area_id = proposal.get("proposed_area_id")
    folder_rel = None
    if area_id:
        row = conn.execute(
            "SELECT folder FROM areas WHERE id = ?", (area_id,)
        ).fetchone()
        if row and row[0]:
            folder_rel = row[0]
    if folder_rel is None:
        folder_rel = "."  # raiz do vault como fallback
    target_dir = vault / folder_rel
    target_dir.mkdir(parents=True, exist_ok=True)
    label = proposal.get("cluster_label") or f"cluster-{proposal['cluster_id']}"
    stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    # Slug simples do label
    slug = "".join(c if c.isalnum() else "-" for c in label.lower())[:40]
    filename = f"moc-{slug}-{stamp}.md"
    today = _dt.date.today().isoformat()
    # Lookup titles
    titles = []
    for nid in proposal["note_ids"]:
        row = conn.execute(
            "SELECT title, path FROM notes WHERE id = ?", (nid,)
        ).fetchone()
        if row:
            titles.append(row[0] or pathlib.Path(row[1]).stem)
    body_lines = [
        "---",
        f"created: {today}",
        f"updated: {today}",
        "type: moc",
        "status: draft",
        "generated_by: obsidian-organizer",
        f"source: cluster-{proposal['cluster_id']}",
        "tags: [draft, generated, moc]",
        "aliases: []",
        "---",
        "",
        f"# MOC: {label}",
        "",
        f"_Gerado automaticamente a partir de cluster com {len(titles)} notas._",
        "",
        "## Notas",
        "",
    ]
    for t in titles:
        body_lines.append(f"- [[{t}]]")
    target_path = target_dir / filename
    target_path.write_text("\n".join(body_lines) + "\n", encoding="utf-8")
    return target_path
