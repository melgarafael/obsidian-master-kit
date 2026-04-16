"""anomaly.py — Anomaly detection z-score (Epic 06 S04 / Wave 4).

Quatro detectores conforme BRIEF §3.5:

1. Streak quebrado: area com streak >= 14 dias falhou 2+ dias consecutivos
2. Keyword emergente: freq(token, 14d) > mu(90d) + 3*sigma
3. Area abandonada: time_since_last > p95 historico da area + cadencia regular
4. Producao anormal: diario > 3x media 30d (log only, nao alerta)

Output em `alerts_cache` com severity IN ('info', 'warn'). Max 1 warn
por dia (enforcement no save).

Tom obrigatorio: pergunta aberta. Nunca "voce esta em X".
"""
from __future__ import annotations

import datetime as _dt
import math
import re
import sqlite3
from collections import Counter
from typing import Any

from core.config import SUGGESTIONS_TTL_DAYS

__all__ = ["detect_anomalies", "save_alerts"]


_STREAK_MIN_DAYS = 14
_STREAK_BREAK_DAYS = 2
_KEYWORD_RECENT_DAYS = 14
_KEYWORD_BASELINE_DAYS = 90
_KEYWORD_Z_THRESHOLD = 3.0
_MIN_TOKEN_LEN = 4
_STOPWORDS = {
    "para", "como", "esse", "essa", "isso", "isto", "uma", "uns", "das", "dos",
    "esta", "este", "pelos", "pelas", "pela", "pelo", "sobre", "entre", "tudo",
    "todo", "toda", "minha", "meu", "suas", "seus", "deles", "delas", "havia",
    "hoje", "assim", "ainda", "muito", "muita", "sempre", "nunca", "agora",
    "tambem", "porque", "enquanto", "quando", "onde", "qual", "sendo",
}


def _daily_event_counts_by_area(
    conn: sqlite3.Connection, days_back: int
) -> dict[int, dict[str, int]]:
    """area_id -> {YYYY-MM-DD: count} para note_created|updated|link_added."""
    cutoff = (_dt.date.today() - _dt.timedelta(days=days_back)).isoformat()
    rows = conn.execute(
        """
        SELECT e.area_id, e.date, COUNT(*)
        FROM events e
        WHERE e.area_id IS NOT NULL
          AND e.date >= ?
          AND e.event_type IN ('note_created', 'note_updated', 'link_added')
        GROUP BY e.area_id, e.date
        """,
        (cutoff,),
    ).fetchall()
    out: dict[int, dict[str, int]] = {}
    for area_id, date_str, cnt in rows:
        out.setdefault(area_id, {})[date_str] = int(cnt)
    return out


def _area_slug(conn: sqlite3.Connection, area_id: int) -> str:
    row = conn.execute(
        "SELECT slug, label FROM areas WHERE id = ?", (area_id,)
    ).fetchone()
    if row is None:
        return f"area-{area_id}"
    return row[1] or row[0] or f"area-{area_id}"


def _compute_streak(area_days: dict[str, int]) -> int:
    """Dias consecutivos com atividade ate hoje. 0 se hoje sem atividade."""
    today = _dt.date.today()
    streak = 0
    for i in range(365):  # cap pratico
        d = today - _dt.timedelta(days=i)
        if area_days.get(d.isoformat(), 0) > 0:
            streak += 1
        else:
            break
    return streak


def _gap_days_since_last(area_days: dict[str, int]) -> int:
    """Dias desde o ultimo dia com atividade."""
    today = _dt.date.today()
    for i in range(365):
        d = today - _dt.timedelta(days=i)
        if area_days.get(d.isoformat(), 0) > 0:
            return i
    return 999  # fallback: area inativa ha tempo


def detect_broken_streaks(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Areas que tiveram streak >= 14 dias mas quebraram ha 2+ dias."""
    counts = _daily_event_counts_by_area(conn, days_back=60)
    results: list[dict[str, Any]] = []
    today = _dt.date.today()
    for area_id, days in counts.items():
        gap = _gap_days_since_last(days)
        if gap < _STREAK_BREAK_DAYS:
            continue  # ainda ativa ou gap pequeno
        # Procura o maior streak antes do gap
        start_check = today - _dt.timedelta(days=gap)
        consec = 0
        for i in range(30):
            d = start_check - _dt.timedelta(days=i)
            if days.get(d.isoformat(), 0) > 0:
                consec += 1
            else:
                break
        if consec >= _STREAK_MIN_DAYS:
            slug = _area_slug(conn, area_id)
            results.append(
                {
                    "kind": "streak_broken",
                    "area_id": area_id,
                    "severity": "warn",
                    "content": f"Streak de {consec}d em {slug} quebrou",
                    "reasoning": (
                        f"Area {slug} teve {consec} dias consecutivos de atividade "
                        f"mas esta sem toque ha {gap} dia(s). Quer olhar?"
                    ),
                }
            )
    return results


def detect_abandoned_areas(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Areas cuja cadencia era regular e agora ha gap > p95 historico."""
    counts = _daily_event_counts_by_area(conn, days_back=365)
    results: list[dict[str, Any]] = []
    for area_id, days in counts.items():
        active_dates = sorted(d for d, c in days.items() if c > 0)
        if len(active_dates) < 10:
            continue
        # Gaps entre dias ativos consecutivos
        gaps: list[int] = []
        for i in range(1, len(active_dates)):
            d1 = _dt.date.fromisoformat(active_dates[i - 1])
            d2 = _dt.date.fromisoformat(active_dates[i])
            gaps.append((d2 - d1).days)
        if not gaps:
            continue
        mean_gap = sum(gaps) / len(gaps)
        if mean_gap <= 0:
            continue
        var = sum((g - mean_gap) ** 2 for g in gaps) / len(gaps)
        std = math.sqrt(var)
        cv = std / mean_gap if mean_gap else 99.0
        if cv >= 0.5:
            continue  # cadencia nao era regular, nao acionamos
        # p95 aproximado (gap com 95% das amostras abaixo)
        sorted_gaps = sorted(gaps)
        p95 = sorted_gaps[min(len(sorted_gaps) - 1, int(len(sorted_gaps) * 0.95))]
        current_gap = _gap_days_since_last(days)
        if current_gap > p95:
            slug = _area_slug(conn, area_id)
            results.append(
                {
                    "kind": "area_abandoned",
                    "area_id": area_id,
                    "severity": "info",
                    "content": f"{slug}: pausa maior que o historico",
                    "reasoning": (
                        f"Area {slug}: ultima atividade ha {current_gap} dias. "
                        f"Seu p95 historico e {p95} dias (cadencia regular "
                        f"CV={cv:.2f}). Maior pausa em ate um ano."
                    ),
                }
            )
    return results


def _tokenize(text: str) -> list[str]:
    text = text.lower()
    tokens = re.findall(r"[a-zA-ZÀ-ÿ]{%d,}" % _MIN_TOKEN_LEN, text)
    return [t for t in tokens if t not in _STOPWORDS]


def detect_emergent_keywords(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Tokens cuja freq em ultimos 14d > mu(90d) + 3*sigma."""
    today = _dt.date.today()
    recent_cutoff = (today - _dt.timedelta(days=_KEYWORD_RECENT_DAYS)).isoformat()
    baseline_cutoff = (today - _dt.timedelta(days=_KEYWORD_BASELINE_DAYS)).isoformat()
    # Carrega titulos+frontmatter de notas ativas tocadas nos periodos
    recent_rows = conn.execute(
        """
        SELECT DISTINCT n.id, n.title FROM events e
        JOIN notes n ON n.id = e.note_id
        WHERE e.date >= ? AND n.deleted_at IS NULL
        """,
        (recent_cutoff,),
    ).fetchall()
    baseline_rows = conn.execute(
        """
        SELECT DISTINCT n.id, n.title FROM events e
        JOIN notes n ON n.id = e.note_id
        WHERE e.date >= ? AND e.date < ? AND n.deleted_at IS NULL
        """,
        (baseline_cutoff, recent_cutoff),
    ).fetchall()
    recent_tokens: Counter = Counter()
    for _, title in recent_rows:
        recent_tokens.update(_tokenize(title or ""))
    # Baseline: freq diaria media
    baseline_tokens: Counter = Counter()
    for _, title in baseline_rows:
        baseline_tokens.update(_tokenize(title or ""))
    baseline_days = max(_KEYWORD_BASELINE_DAYS - _KEYWORD_RECENT_DAYS, 1)
    baseline_daily_mean = {t: c / baseline_days for t, c in baseline_tokens.items()}
    # Se token apareceu >= 3x em 14d e significativamente acima da baseline
    results: list[dict[str, Any]] = []
    for tok, recent_cnt in recent_tokens.most_common(20):
        if recent_cnt < 3:
            continue
        mean = baseline_daily_mean.get(tok, 0.0)
        # Assume Poisson-like: std ~= sqrt(mean)
        std = math.sqrt(max(mean, 0.01))
        recent_rate = recent_cnt / _KEYWORD_RECENT_DAYS
        z = (recent_rate - mean) / std if std > 0 else recent_rate / 0.01
        if z >= _KEYWORD_Z_THRESHOLD:
            results.append(
                {
                    "kind": "keyword_emergent",
                    "area_id": None,
                    "severity": "info",
                    "content": f"'{tok}' subiu no vocabulario recente",
                    "reasoning": (
                        f"Token '{tok}' aparece {recent_cnt}x em {_KEYWORD_RECENT_DAYS}d "
                        f"(z={z:.1f}, baseline diaria {mean:.2f}). Quer olhar?"
                    ),
                }
            )
    return results[:3]  # max 3 keywords emergentes por run


def detect_anomalies(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Orquestra os 3 detectores ativos (producao anormal e log-only)."""
    out: list[dict[str, Any]] = []
    out.extend(detect_broken_streaks(conn))
    out.extend(detect_abandoned_areas(conn))
    out.extend(detect_emergent_keywords(conn))
    return out


def save_alerts(
    conn: sqlite3.Connection, anomalies: list[dict[str, Any]]
) -> int:
    """Grava em alerts_cache. Enforce max 1 warn por dia (hoje)."""
    if not anomalies:
        return 0
    today = _dt.date.today().isoformat()
    existing_warns_today = conn.execute(
        "SELECT COUNT(*) FROM alerts_cache "
        "WHERE severity='warn' AND substr(generated_at, 1, 10) = ? "
        "AND dismissed = 0",
        (today,),
    ).fetchone()[0]
    now = _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0)
    exp = now + _dt.timedelta(days=SUGGESTIONS_TTL_DAYS)
    gen_iso = now.isoformat()
    exp_iso = exp.isoformat()
    count = 0
    for a in anomalies:
        if a["severity"] == "warn" and existing_warns_today >= 1:
            # Rebaixa pra info pra respeitar "max 1 warn/dia"
            a = {**a, "severity": "info"}
        import json as _json
        target_ids = _json.dumps([a["area_id"]] if a.get("area_id") is not None else [])
        # Dedup: mesmo kind + mesmos targets + mesmo dia
        existing = conn.execute(
            "SELECT 1 FROM alerts_cache "
            "WHERE kind = ? AND dismissed = 0 "
            "AND substr(generated_at, 1, 10) = ? "
            "AND target_note_ids = ?",
            (a["kind"], today, target_ids),
        ).fetchone()
        if existing:
            continue
        conn.execute(
            """
            INSERT INTO alerts_cache
              (generated_at, expires_at, kind, target_note_ids, content,
               reasoning, severity, dismissed)
            VALUES (?, ?, ?, ?, ?, ?, ?, 0)
            """,
            (
                gen_iso,
                exp_iso,
                a["kind"],
                target_ids,
                a["content"],
                a["reasoning"],
                a["severity"],
            ),
        )
        count += 1
        if a["severity"] == "warn":
            existing_warns_today += 1
    conn.commit()
    return count
