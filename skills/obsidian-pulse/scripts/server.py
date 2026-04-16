"""server.py — FastAPI + HTMX dashboard (Epic 06 S06 / Wave 6).

Bind 127.0.0.1 + middleware que rejeita IPs externos + auth token em
`.obsidian-master/pulse-token.txt` (gerado first run).

Endpoints:
- GET  /                   — dashboard HTML (renderizado pelos templates)
- GET  /api/suggestions    — top-N ranked
- GET  /api/alerts         — alertas ativos
- GET  /api/heatmap        — contagens diarias pra cal-heatmap
- GET  /api/insights       — padroes narrativos (templates, sem LLM)
- POST /api/accept/{id}    — marca suggestion acted_on
- POST /api/dismiss/{id}   — marca suggestion dismissed
- GET  /api/status         — ping/health

Privacy: notas com `sensitive=1` tem title redigido pra "[item em area X]".
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import secrets
import sqlite3
import sys
from typing import Any

_BASE = pathlib.Path(__file__).parent
_RANKING_PATH = _BASE / "ranking.py"
_PRIVACY_PATH = _BASE / "privacy.py"
_TEMPLATES_DIR = _BASE / "templates"


def _load(name: str, path: pathlib.Path):
    existing = sys.modules.get(name)
    if existing is not None:
        return existing
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


def _get_or_create_token(vault: pathlib.Path) -> str:
    token_path = vault / ".obsidian-master" / "pulse-token.txt"
    if token_path.exists():
        return token_path.read_text(encoding="utf-8").strip()
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(32)
    token_path.write_text(token + "\n", encoding="utf-8")
    token_path.chmod(0o600)
    return token


def _redact(text: str | None, sensitive: int) -> str:
    if not text:
        return ""
    if sensitive:
        return "[item sensivel redigido]"
    return text


def build_app(
    vault: pathlib.Path,
    *,
    token: str | None = None,
    trusted_hosts: tuple[str, ...] | None = None,
):
    """Cria a FastAPI app. Retorna `app`. Conexao SQLite por request.

    `trusted_hosts`: override da lista default de clients locais.
    Default e ('127.0.0.1', 'localhost', '::1'). Pass 'testclient' em
    tests via FastAPI TestClient.
    """
    from fastapi import FastAPI, HTTPException, Request, Response
    from fastapi.responses import HTMLResponse, JSONResponse
    from starlette.middleware.base import BaseHTTPMiddleware
    from core.db import connect
    from core.paths import MARKER_REL

    actual_token = token or _get_or_create_token(vault)
    allowed_hosts = trusted_hosts or ("127.0.0.1", "localhost", "::1", "testclient")
    app = FastAPI(title="obsidian-pulse", version="1.0.0")

    class LocalOnlyAuth(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            client_host = request.client.host if request.client else None
            if client_host not in allowed_hosts:
                return JSONResponse(
                    {"error": "pulse e local-only"}, status_code=403
                )
            # Token opcional em endpoints /api/ — GET / (dashboard) e publico local
            if request.url.path.startswith("/api/"):
                header_token = request.headers.get("X-Pulse-Token")
                query_token = request.query_params.get("token")
                supplied = header_token or query_token
                if supplied != actual_token:
                    return JSONResponse(
                        {"error": "token invalido"}, status_code=401
                    )
            return await call_next(request)

    app.add_middleware(LocalOnlyAuth)

    # ---------- endpoints ----------

    @app.get("/api/status")
    async def api_status():
        conn = connect(vault)
        try:
            n = conn.execute(
                "SELECT COUNT(*) FROM notes WHERE deleted_at IS NULL"
            ).fetchone()[0]
            return {"notes_active": int(n), "status": "ok"}
        finally:
            conn.close()

    @app.get("/api/suggestions")
    async def api_suggestions(limit: int = 10, show_sensitive: bool = False):
        conn = connect(vault)
        try:
            ranking = _load("_pulse_ranking", _RANKING_PATH)
            privacy = _load("_pulse_privacy", _PRIVACY_PATH)
            top = ranking.select_top(conn, limit=limit)
            redacted = [
                privacy.redact_entry(conn, s, show_sensitive=show_sensitive)
                for s in top
            ]
            return {"suggestions": redacted, "count": len(redacted)}
        finally:
            conn.close()

    @app.get("/api/alerts")
    async def api_alerts(show_sensitive: bool = False):
        conn = connect(vault)
        try:
            privacy = _load("_pulse_privacy", _PRIVACY_PATH)
            rows = conn.execute(
                """
                SELECT id, kind, target_note_ids, content, reasoning, severity,
                       generated_at
                FROM alerts_cache
                WHERE dismissed = 0 AND expires_at > datetime('now')
                ORDER BY
                  CASE severity WHEN 'warn' THEN 0 ELSE 1 END,
                  generated_at DESC
                LIMIT 10
                """
            ).fetchall()
            alerts = [
                {
                    "id": r[0],
                    "kind": r[1],
                    "target_note_ids": json.loads(r[2]),
                    "content": r[3],
                    "reasoning": r[4],
                    "severity": r[5],
                    "generated_at": r[6],
                }
                for r in rows
            ]
            redacted = [
                privacy.redact_entry(conn, a, show_sensitive=show_sensitive)
                for a in alerts
            ]
            return {"alerts": redacted, "count": len(redacted)}
        finally:
            conn.close()

    @app.get("/api/heatmap")
    async def api_heatmap(days: int = 365):
        conn = connect(vault)
        try:
            import datetime as _dt
            cutoff = (_dt.date.today() - _dt.timedelta(days=days)).isoformat()
            rows = conn.execute(
                """
                SELECT date, COUNT(*) FROM events
                WHERE date >= ?
                  AND event_type IN ('note_created', 'note_updated', 'link_added')
                GROUP BY date
                ORDER BY date ASC
                """,
                (cutoff,),
            ).fetchall()
            return {"days": [{"date": r[0], "count": int(r[1])} for r in rows]}
        finally:
            conn.close()

    @app.get("/api/heatmap/day/{date}")
    async def api_heatmap_day(date: str, show_sensitive: bool = False):
        """Top-3 notas tocadas no dia, respeitando redaction por `sensitive`."""
        conn = connect(vault)
        try:
            rows = conn.execute(
                """
                SELECT n.id, n.title, n.sensitive, COUNT(*)
                FROM events e
                JOIN notes n ON n.id = e.note_id
                WHERE e.date = ?
                  AND e.event_type IN ('note_created', 'note_updated', 'link_added')
                GROUP BY n.id
                ORDER BY COUNT(*) DESC LIMIT 3
                """,
                (date,),
            ).fetchall()
            titles = []
            for _nid, title, sensitive, cnt in rows:
                if sensitive and not show_sensitive:
                    titles.append({"title": "[item sensivel]", "count": int(cnt)})
                else:
                    titles.append({"title": title or "(sem titulo)", "count": int(cnt)})
            return {"date": date, "top_titles": titles}
        finally:
            conn.close()

    @app.get("/api/insights")
    async def api_insights():
        """Narrativas deterministicas (templates, sem LLM)."""
        conn = connect(vault)
        try:
            insights = _generate_insights(conn)
            return {"insights": insights}
        finally:
            conn.close()

    def _execute_action(conn, suggestion_id: int) -> dict:
        """Executa acao real no vault baseada no tipo da sugestao."""
        import datetime as _dt
        from pathlib import Path as _P

        row = conn.execute(
            "SELECT kind, target_note_ids, content FROM suggestions_cache WHERE id=?",
            (suggestion_id,),
        ).fetchone()
        if not row:
            return {"action": "not_found"}

        kind, target_json, content = row
        target_ids = json.loads(target_json) if target_json else []

        if kind == "moc_missing":
            return _create_moc(conn, vault, target_ids)
        elif kind == "bridge":
            return _add_bridge(conn, vault, target_ids)
        elif kind == "reference_missing":
            return _create_reference(conn, vault, target_ids)
        else:
            return {"action": "marked_only", "kind": kind}

    def _create_moc(conn, vault_path, target_ids: list) -> dict:
        """Cria _MOC.md na pasta comum das notas do cluster."""
        import datetime as _dt
        from pathlib import Path as _P
        import os

        if not target_ids:
            return {"action": "no_targets"}

        ph = ",".join("?" * len(target_ids))
        rows = conn.execute(
            f"SELECT id, path, title FROM notes WHERE id IN ({ph})", target_ids
        ).fetchall()
        if not rows:
            return {"action": "no_notes_found"}

        paths = [_P(r[1]) for r in rows]
        try:
            common = _P(os.path.commonpath([str(p.parent) for p in paths]))
        except ValueError:
            common = paths[0].parent

        moc_path = vault_path / common / "_MOC.md"
        if moc_path.exists():
            existing = moc_path.read_text(encoding="utf-8")
            added = 0
            for _, _, title in rows:
                stem = title or "(sem titulo)"
                link = f"- [[{stem}]]"
                if link not in existing:
                    existing = existing.rstrip() + f"\n{link}\n"
                    added += 1
            if added:
                moc_path.write_text(existing, encoding="utf-8")
            return {"action": "moc_updated", "path": str(common / "_MOC.md"), "added": added}

        today = _dt.date.today().isoformat()
        lines = [
            "---", f"created: {today}", f"updated: {today}",
            "type: moc", "status: draft",
            "generated_by: obsidian-pulse", "tags: [generated]",
            "---", "",
            f"# MOC — {common.name}", "",
            f"> Gerado pelo obsidian-pulse. {len(rows)} notas agrupadas por similaridade semantica.", "",
            "## Notas", "",
        ]
        for _, path, title in sorted(rows, key=lambda r: (r[2] or "").lower()):
            stem = _P(path).stem
            lines.append(f"- [[{stem}]]")
        lines.extend(["", "## Relacionado", ""])

        moc_path.parent.mkdir(parents=True, exist_ok=True)
        moc_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return {"action": "moc_created", "path": str(common / "_MOC.md"), "notes_linked": len(rows)}

    def _add_bridge(conn, vault_path, target_ids: list) -> dict:
        """Adiciona wiki-link bidirecional entre 2 notas."""
        from pathlib import Path as _P

        if len(target_ids) < 2:
            return {"action": "insufficient_targets"}

        rows = conn.execute(
            "SELECT id, path, title FROM notes WHERE id IN (?, ?)",
            (target_ids[0], target_ids[1]),
        ).fetchall()
        if len(rows) < 2:
            return {"action": "notes_not_found"}

        by_id = {r[0]: (r[1], r[2]) for r in rows}
        path_a, title_a = by_id[target_ids[0]]
        path_b, title_b = by_id[target_ids[1]]
        stem_a, stem_b = _P(path_a).stem, _P(path_b).stem

        def _append_link(fpath, link_stem):
            fp = vault_path / fpath
            if not fp.exists():
                return False
            text = fp.read_text(encoding="utf-8")
            link_line = f"- [[{link_stem}]]"
            if link_line in text:
                return False
            if "## Relacionado" in text:
                text = text.replace("## Relacionado\n", f"## Relacionado\n{link_line}\n", 1)
            else:
                text = text.rstrip() + f"\n\n## Relacionado\n\n{link_line}\n"
            fp.write_text(text, encoding="utf-8")
            return True

        linked_a = _append_link(path_a, stem_b)
        linked_b = _append_link(path_b, stem_a)
        return {
            "action": "bridge_linked",
            "note_a": stem_a, "linked_a": linked_a,
            "note_b": stem_b, "linked_b": linked_b,
        }

    def _create_reference(conn, vault_path, target_ids: list) -> dict:
        """Cria nota de referencia central linkando cluster."""
        import datetime as _dt
        from pathlib import Path as _P

        if not target_ids:
            return {"action": "no_targets"}

        ph = ",".join("?" * len(target_ids))
        rows = conn.execute(
            f"SELECT id, path, title FROM notes WHERE id IN ({ph})", target_ids
        ).fetchall()
        if not rows:
            return {"action": "no_notes_found"}

        first_path = _P(rows[0][1])
        ref_dir = vault_path / first_path.parent
        titles = [r[2] or _P(r[1]).stem for r in rows]
        slug = titles[0][:40].replace("/", "-").replace(" ", "-").lower()
        ref_path = ref_dir / f"_ref-{slug}.md"

        today = _dt.date.today().isoformat()
        lines = [
            "---", f"created: {today}", f"updated: {today}",
            "type: referencia", "status: draft",
            "generated_by: obsidian-pulse", "tags: [generated, referencia]",
            "---", "",
            f"# Referencia — {titles[0]}", "",
            f"> Nota central gerada pelo pulse. {len(rows)} notas relacionadas por similaridade.", "",
            "## Notas relacionadas", "",
        ]
        for _, path, title in rows:
            lines.append(f"- [[{_P(path).stem}]]")
        lines.extend(["", "## Contexto", "", "_(Adicione aqui o que conecta essas notas.)_", ""])

        ref_path.parent.mkdir(parents=True, exist_ok=True)
        ref_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return {"action": "reference_created", "path": str(ref_path.relative_to(vault_path)), "notes_linked": len(rows)}

    @app.post("/api/accept/{suggestion_id}")
    async def api_accept(suggestion_id: int):
        import datetime as _dt
        conn = connect(vault)
        try:
            result = _execute_action(conn, suggestion_id)
            conn.execute(
                "UPDATE suggestions_cache SET acted_on = 1 WHERE id = ?",
                (suggestion_id,),
            )
            now = _dt.datetime.now(_dt.timezone.utc).isoformat()
            conn.execute(
                "INSERT INTO events (ts, event_type, note_id, date) "
                "VALUES (?, 'suggestion_accepted', NULL, ?)",
                (now, now[:10]),
            )
            conn.commit()
            return {"ok": True, "suggestion_id": suggestion_id, "result": result}
        finally:
            conn.close()

    @app.post("/api/dismiss/{suggestion_id}")
    async def api_dismiss(suggestion_id: int):
        import datetime as _dt
        now = _dt.datetime.now(_dt.timezone.utc).isoformat()
        conn = connect(vault)
        try:
            conn.execute(
                "UPDATE suggestions_cache SET dismissed = 1, dismissed_at = ? "
                "WHERE id = ?",
                (now, suggestion_id),
            )
            conn.execute(
                "INSERT INTO events (ts, event_type, note_id, date) "
                "VALUES (?, 'suggestion_dismissed', NULL, ?)",
                (now, now[:10]),
            )
            conn.commit()
            return {"ok": True, "suggestion_id": suggestion_id}
        finally:
            conn.close()

    @app.get("/", response_class=HTMLResponse)
    async def dashboard():
        html_path = _TEMPLATES_DIR / "dashboard.html"
        if not html_path.exists():
            return HTMLResponse(
                "<h1>obsidian-pulse</h1>"
                "<p>Templates nao instalados. "
                "Use <code>/api/status</code> com header X-Pulse-Token.</p>",
                status_code=200,
            )
        return HTMLResponse(html_path.read_text(encoding="utf-8"))

    # Expoe o token pra o CLI printar na inicializacao
    app.state.pulse_token = actual_token
    return app


def _generate_insights(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Templates deterministicos em pt-br. Sem LLM."""
    import datetime as _dt
    insights = []
    # Insight 1: dia mais produtivo (maior count de events) nos ultimos 30d
    row = conn.execute(
        """
        SELECT date, COUNT(*) FROM events
        WHERE date >= ?
          AND event_type IN ('note_created', 'note_updated')
        GROUP BY date ORDER BY COUNT(*) DESC LIMIT 1
        """,
        ((_dt.date.today() - _dt.timedelta(days=30)).isoformat(),),
    ).fetchone()
    if row and row[1] >= 3:
        insights.append(
            {
                "title": "Dia mais produtivo do mes",
                "body": f"Em {row[0]} voce tocou {row[1]} notas. Foi o pico dos ultimos 30 dias.",
            }
        )
    # Insight 2: area com mais atividade nos ultimos 7d
    row = conn.execute(
        """
        SELECT a.label, COUNT(*)
        FROM events e JOIN areas a ON a.id = e.area_id
        WHERE e.date >= ?
          AND e.event_type IN ('note_created', 'note_updated')
        GROUP BY a.id ORDER BY COUNT(*) DESC LIMIT 1
        """,
        ((_dt.date.today() - _dt.timedelta(days=7)).isoformat(),),
    ).fetchone()
    if row and row[1] >= 3:
        insights.append(
            {
                "title": "Area dominante da semana",
                "body": f"Area '{row[0]}' recebeu {row[1]} toques nos ultimos 7 dias.",
            }
        )
    return insights
