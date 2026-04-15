"""generate.py — Note generation restrita ao vault (Epic 05 S04 / Wave 4).

Materializa uma sugestao aprovada (`suggestions_cache.id`) em um .md novo
de `status: draft` assinado com `generated_by: obsidian-expand`. O
conteudo sai de um LLM (Claude CLI por subprocess — decisao do plano
Fase 1 da orquestracao) com prompt duramente restritivo:

1. Fonte unica: APENAS as 3-5 notas mais relevantes do vault (via KNN
   a partir dos targets da sugestao).
2. Instrucao explicita: "Se nao ha informacao suficiente no vault,
   diga isso explicitamente. NAO invente fatos."
3. Instrucao explicita: "Cite toda afirmacao que venha das notas-fonte
   via wikilink `[[titulo-da-nota]]`".

Para testar sem queimar API (e pra dar ao usuario o `--dry-run`):
`invoke_llm` e fachada isolada que pode ser mockada em testes (via
monkeypatch). Em producao, sub-processa `claude -p` com o prompt em
stdin.

Orquestracao:
- `build_prompt(suggestion, sources) -> str` — prompt determinista
- `invoke_llm(prompt) -> str` — subprocess claude, isolavel em tests
- `generate_note(conn, suggestion_id, *, dry_run=False) -> dict`

Retorno de generate_note:
  - dry_run: {prompt, source_paths, target_dir, target_filename, would_write_to}
  - materializa: {written_path, source_paths, suggestion_id}
  - erro:      {error: str}
"""
from __future__ import annotations

import datetime as _dt
import importlib.util
import json
import pathlib
import re
import sqlite3
import subprocess
import sys
from typing import Any

__all__ = ["build_prompt", "invoke_llm", "generate_note"]


_KNN_PATH = pathlib.Path(__file__).parent / "knn.py"
_DEFAULT_SOURCE_K = 4
# Chars maximos de body por nota-fonte pra caber em prompt razoavel.
_MAX_BODY_CHARS_PER_SOURCE = 3000


def _load_knn_module():
    name = "_expand_knn"
    existing = sys.modules.get(name)
    if existing is not None:
        return existing
    spec = importlib.util.spec_from_file_location(name, _KNN_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------- prompt construction ----------


_PROMPT_TEMPLATE = """Voce esta gerando uma nota de Obsidian em portugues-br.

REGRAS DURAS (nao negociaveis):
1. Use APENAS o conteudo das notas-fonte abaixo como material de apoio.
2. NAO invente fatos. NAO cite fontes externas ao vault.
3. Se nao ha informacao suficiente no vault pra responder a tarefa, escreva
   explicitamente "Nao ha informacao suficiente no vault pra essa ponte" e
   liste o que seria necessario pesquisar externamente — sem preencher.
4. Toda afirmacao substantiva deve vir acompanhada de referencia wikilink
   [[titulo-da-nota-fonte]].
5. Saida e markdown puro — sem bloco de codigo envolvendo a resposta, sem
   explicacao meta antes ou depois, so a nota final.

---

TAREFA: {task}

RAZAO DA SUGESTAO (para contexto, NAO e texto a reproduzir):
{reasoning}

---

NOTAS-FONTE (conteudo bruto do vault):

{sources_block}

---

Escreva a nota agora."""


def _format_source_block(sources: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for s in sources:
        body = s.get("body", "")
        if len(body) > _MAX_BODY_CHARS_PER_SOURCE:
            body = body[:_MAX_BODY_CHARS_PER_SOURCE] + "\n[...conteudo truncado...]"
        parts.append(
            f"### [[{s['title']}]]\n"
            f"_path: {s['path']}_\n\n"
            f"{body.strip()}\n"
        )
    return "\n---\n".join(parts)


def build_prompt(suggestion: dict[str, Any], sources: list[dict[str, Any]]) -> str:
    """Monta prompt determinista dado a sugestao + lista de notas-fonte."""
    kind = suggestion.get("kind", "")
    content = suggestion.get("content", "")
    reasoning = suggestion.get("reasoning", "")
    # Task string depende do kind — sao os 3 tipos gerados por gaps.py
    if kind == "bridge":
        task = (
            "Escreva uma nota-ponte de ~300-500 palavras que conecte os "
            "conceitos cobertos pelas notas-fonte abaixo. Explique a relacao "
            "entre eles USANDO SOMENTE o que as notas dizem. Termine com uma "
            "secao 'Ver tambem' listando wikilinks pras fontes."
        )
    elif kind == "moc_expand":
        task = (
            "Amplie este MOC adicionando uma lista de wikilinks pra notas da "
            "area que parecem orfas do indice, organizadas por subtema. Nao "
            "gere explicacao — apenas a estrutura do MOC estendido."
        )
    elif kind == "reference_missing":
        task = (
            "Escreva uma nota de referencia que sintetize o conceito central "
            "discutido nas notas-fonte. Estrutura: (1) definicao curta, "
            "(2) 3-5 pontos principais apoiados por wikilinks, "
            "(3) 'Ver tambem' com todas as fontes."
        )
    else:
        task = f"({kind}) {content}"
    return _PROMPT_TEMPLATE.format(
        task=task,
        reasoning=reasoning,
        sources_block=_format_source_block(sources),
    )


# ---------- LLM invocation (isolavel em tests) ----------


def invoke_llm(prompt: str, *, timeout: int = 120) -> str:
    """Invoca Claude via CLI subprocess. Retorna resposta crua (stdout).

    Levanta `RuntimeError` se Claude CLI nao encontrado ou nao completar
    com exit 0.
    """
    try:
        result = subprocess.run(
            ["claude", "-p", prompt],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            "CLI 'claude' nao encontrado no PATH. Instale Claude Code."
        ) from exc
    if result.returncode != 0:
        raise RuntimeError(
            f"Claude CLI retornou exit {result.returncode}: {result.stderr.strip()[:200]}"
        )
    return result.stdout.strip()


# ---------- main orchestration ----------


def _slugify(name: str) -> str:
    """Slug simples pra filename — stdlib only."""
    s = re.sub(r"[^\w\s-]", "", name, flags=re.UNICODE).strip().lower()
    s = re.sub(r"[\s]+", "-", s)
    return s[:80] if s else "nota-gerada"


def _fetch_suggestion(conn: sqlite3.Connection, suggestion_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT id, kind, target_note_ids, content, reasoning, score, dismissed, acted_on "
        "FROM suggestions_cache WHERE id = ?",
        (suggestion_id,),
    ).fetchone()
    if row is None:
        return None
    return {
        "id": row[0],
        "kind": row[1],
        "target_note_ids": json.loads(row[2]),
        "content": row[3],
        "reasoning": row[4],
        "score": row[5],
        "dismissed": bool(row[6]),
        "acted_on": bool(row[7]),
    }


def _fetch_source_notes(
    conn: sqlite3.Connection,
    target_ids: list[int],
    vault: pathlib.Path,
    *,
    k: int = _DEFAULT_SOURCE_K,
) -> list[dict[str, Any]]:
    """Retorna sources: targets + seus vizinhos KNN ate k total.

    Prioriza os targets explicitos da sugestao. Completa com vizinhos do
    primeiro target via KNN ate atingir `k` notas distintas.
    """
    knn_mod = _load_knn_module()
    ordered_ids: list[int] = []
    for tid in target_ids:
        if tid not in ordered_ids:
            ordered_ids.append(tid)
    if ordered_ids and len(ordered_ids) < k:
        seed = ordered_ids[0]
        neighbors = knn_mod.knn(conn, seed, k=k * 2)
        for nid, _ in neighbors:
            if nid in ordered_ids:
                continue
            ordered_ids.append(nid)
            if len(ordered_ids) >= k:
                break
    ordered_ids = ordered_ids[:k]
    sources: list[dict[str, Any]] = []
    for nid in ordered_ids:
        row = conn.execute(
            "SELECT id, path, title FROM notes WHERE id = ?",
            (nid,),
        ).fetchone()
        if row is None:
            continue
        abs_path = vault / row[1]
        try:
            body = abs_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            body = ""
        sources.append(
            {
                "id": row[0],
                "path": row[1],
                "title": row[2] or pathlib.Path(row[1]).stem,
                "body": body,
            }
        )
    return sources


def _target_dir_and_filename(
    vault: pathlib.Path,
    sources: list[dict[str, Any]],
    suggestion: dict[str, Any],
) -> tuple[pathlib.Path, str]:
    """Escolhe pasta destino + filename.

    - Pasta: pasta da primeira fonte (mantem contexto de area).
    - Filename: derivado do kind + ids + timestamp pra evitar colisao.
    """
    if sources:
        first_path = vault / sources[0]["path"]
        target_dir = first_path.parent
    else:
        target_dir = vault
    kind = suggestion.get("kind", "gerada")
    ids_part = "-".join(str(i) for i in suggestion.get("target_note_ids", [])[:3])
    stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    filename = _slugify(f"{kind}-{ids_part}-{stamp}") + ".md"
    return target_dir, filename


def _build_frontmatter(
    suggestion: dict[str, Any],
    sources: list[dict[str, Any]],
    vault: pathlib.Path,
    target_dir: pathlib.Path,
) -> str:
    today = _dt.date.today().isoformat()
    area = _infer_area_from_dir(target_dir, vault)
    lines = [
        "---",
        f"created: {today}",
        f"updated: {today}",
        f"area: {area}",
        f"type: {'moc' if suggestion.get('kind') == 'moc_expand' else 'nota'}",
        "status: draft",
        "generated_by: obsidian-expand",
        f"source: suggestion-{suggestion['id']}",
        "tags: [draft, generated]",
        "aliases: []",
        "---",
    ]
    return "\n".join(lines) + "\n\n"


_AREA_FOLDER_MAP = {
    "00 - Pessoal": "pessoal",
    "01 - Profissional": "profissional",
    "02 - Pesquisas e Estudos": "pesquisa",
    "03 - Memoria da IA": "ai-memory",
}


def _infer_area_from_dir(target_dir: pathlib.Path, vault: pathlib.Path) -> str:
    try:
        rel = target_dir.relative_to(vault)
    except ValueError:
        return "sem-area"
    if not rel.parts:
        return "sem-area"
    first = rel.parts[0]
    return _AREA_FOLDER_MAP.get(first, first)


def generate_note(
    conn: sqlite3.Connection,
    suggestion_id: int,
    vault: pathlib.Path,
    *,
    dry_run: bool = False,
    llm_invoker=invoke_llm,
    source_k: int = _DEFAULT_SOURCE_K,
) -> dict[str, Any]:
    """Materializa sugestao em .md. `llm_invoker` parametrizavel pra testes."""
    suggestion = _fetch_suggestion(conn, suggestion_id)
    if suggestion is None:
        return {"error": f"suggestion_id {suggestion_id} nao encontrada"}
    if suggestion["dismissed"]:
        return {"error": f"suggestion {suggestion_id} foi descartada (dismissed)"}
    sources = _fetch_source_notes(
        conn, suggestion["target_note_ids"], vault, k=source_k
    )
    if not sources:
        return {
            "error": (
                f"suggestion {suggestion_id} nao tem notas-fonte validas no vault"
            )
        }
    prompt = build_prompt(suggestion, sources)
    target_dir, filename = _target_dir_and_filename(vault, sources, suggestion)
    target_path = target_dir / filename
    source_paths = [s["path"] for s in sources]

    if dry_run:
        return {
            "dry_run": True,
            "suggestion_id": suggestion_id,
            "prompt": prompt,
            "source_paths": source_paths,
            "target_dir": str(target_dir),
            "target_filename": filename,
            "would_write_to": str(target_path),
        }

    body = llm_invoker(prompt)
    # Sanity: garante wikilink pra pelo menos uma fonte
    if not any(f"[[{s['title']}]]" in body for s in sources):
        # Nao bloqueia, mas prefixa warning visivel no draft
        body = (
            "<!-- AVISO: resposta do LLM nao incluiu wikilink "
            "pras notas-fonte explicitas; revisar -->\n\n" + body
        )
    frontmatter = _build_frontmatter(suggestion, sources, vault, target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path.write_text(frontmatter + body + "\n", encoding="utf-8")
    # Marca suggestion como acted_on
    conn.execute(
        "UPDATE suggestions_cache SET acted_on = 1 WHERE id = ?",
        (suggestion_id,),
    )
    conn.commit()
    return {
        "dry_run": False,
        "suggestion_id": suggestion_id,
        "written_path": str(target_path),
        "source_paths": source_paths,
    }
