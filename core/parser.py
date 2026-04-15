"""core/parser.py — parser de notas Markdown do vault.

Contrato publico: `parse_markdown(text) -> ParsedNote`.

Extrai frontmatter (YAML-subset stdlib, sem PyYAML), wiki-links, embeds,
inline tags, word count e body hash. Reuso deliberado do parser de
frontmatter do `skills/obsidian-librarian/scripts/update_index.py` — aquele
codigo ja e battle-tested no vault real. A duplicacao temporaria sera
eliminada no Epic 03, quando o librarian passa a importar de core.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any


# ---------- regexes ----------

FRONTMATTER_RE = re.compile(
    r"\A---\s*\n(.*?)^---\s*$\n?(.*)\Z", re.DOTALL | re.MULTILINE
)

# Wiki-link com alias opcional: [[Target]] ou [[Target|Alias]].
# Deliberadamente mais estrito que o regex do librarian (que captura tudo
# entre [[ e ]]), pra poder separar target e alias em grupos distintos.
WIKILINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")

# Embed: ![[Target]] (imagens, notas embedadas). Precisa ser processado
# ANTES de wikilinks, senao o `[[X]]` interno do embed e capturado duas vezes.
EMBED_RE = re.compile(r"!\[\[([^\]]+)\]\]")

# Inline tag no corpo: #a ou #a/b. Exige que o `#` nao venha colado num
# char alfanumerico (evita capturar `foo#bar` ou URLs tipo `/path#frag`).
TAG_IN_BODY_RE = re.compile(r"(?<![\w/])#([a-z0-9][a-z0-9/_-]*)", re.IGNORECASE)


# ---------- dataclasses ----------

@dataclass(frozen=True)
class WikiLink:
    """Wiki-link parseado. `alias` e None quando o link e `[[X]]` simples."""
    target: str
    alias: str | None


@dataclass(frozen=True)
class ParsedNote:
    """Resultado de `parse_markdown`. Campos ja normalizados, prontos pro DB."""
    frontmatter_dict: dict
    frontmatter_raw_json: str  # source-of-truth JSON pra coluna notes.frontmatter_json
    body: str                  # corpo sem frontmatter
    wikilinks: list[WikiLink]  # [[X]] e [[X|Y]], NAO inclui embeds
    embeds: list[str]          # targets de ![[X]]
    inline_tags: list[str]     # tags #a do corpo, normalizadas e deduplicadas
    word_count: int
    body_hash: str             # SHA256 hex do body UTF-8


# ---------- frontmatter parser (copiado verbatim do librarian) ----------
# Mantido identico ao `update_index.py` pra garantir que os dois producem
# exatamente o mesmo dict. Epic 03 deleta a copia do librarian e importa daqui.

def _parse_scalar(raw: str) -> Any:
    raw = raw.strip()
    if raw == "" or raw == "~" or raw.lower() == "null":
        return None
    if (raw.startswith('"') and raw.endswith('"')) or (
        raw.startswith("'") and raw.endswith("'")
    ):
        return raw[1:-1]
    if re.match(r"^\d{4}-\d{2}-\d{2}$", raw):
        return raw  # ISO date kept as string
    if re.match(r"^-?\d+$", raw):
        return int(raw)
    if re.match(r"^-?\d*\.\d+$", raw):
        return float(raw)
    if raw.lower() in ("true", "false"):
        return raw.lower() == "true"
    return raw


def _parse_inline_list(raw: str) -> list[Any]:
    inner = raw.strip()
    if not (inner.startswith("[") and inner.endswith("]")):
        return [_parse_scalar(raw)]
    inner = inner[1:-1].strip()
    if not inner:
        return []
    items = []
    depth = 0
    cur: list[str] = []
    for ch in inner:
        if ch == "," and depth == 0:
            items.append("".join(cur).strip())
            cur = []
        else:
            if ch in "[{":
                depth += 1
            elif ch in "]}":
                depth -= 1
            cur.append(ch)
    if cur:
        items.append("".join(cur).strip())
    return [_parse_scalar(x) for x in items]


def parse_frontmatter(text: str) -> tuple[dict, str, list[str]]:
    """Return (frontmatter_dict, body, errors).

    Subset YAML coberto: `key: value`, `key: [inline, list]`, e listas
    multi-linha `key:\\n  - a\\n  - b`. Malformed frontmatter retorna dict
    vazio + lista de erros — caller decide o que fazer.
    """
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {}, text, ["no frontmatter"]
    fm_raw, body = m.group(1), m.group(2)
    errors: list[str] = []
    data: dict[str, Any] = {}

    lines = fm_raw.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.rstrip()
        if not stripped.strip() or stripped.lstrip().startswith("#"):
            i += 1
            continue
        if ":" not in stripped:
            errors.append(f"malformed line: {stripped!r}")
            i += 1
            continue
        key, _, rest = stripped.partition(":")
        key = key.strip()
        rest = rest.strip()

        if rest == "":
            items: list[Any] = []
            j = i + 1
            while j < len(lines):
                nxt = lines[j]
                if nxt.strip().startswith("- "):
                    items.append(_parse_scalar(nxt.strip()[2:]))
                    j += 1
                elif nxt.strip() == "":
                    j += 1
                else:
                    break
            data[key] = items
            i = j
            continue

        if rest.startswith("["):
            data[key] = _parse_inline_list(rest)
        else:
            data[key] = _parse_scalar(rest)
        i += 1

    return data, body, errors


# ---------- extraction helpers ----------

def _extract_embeds(body: str) -> tuple[list[str], str]:
    """Extrai embeds e retorna tambem o body com embeds mascarados.

    O mascaramento substitui `![[X]]` por espacos do mesmo tamanho, pra que
    offsets e o regex de wikilinks nao capturem o `[[X]]` interno. Usar
    espacos (em vez de string vazia) preserva word_count se o usuario
    depender dele — mas como word_count e calculado sobre o body ORIGINAL,
    isso e so um detalhe defensivo.
    """
    embeds: list[str] = []
    masked_parts: list[str] = []
    last = 0
    for m in EMBED_RE.finditer(body):
        embeds.append(m.group(1).strip())
        masked_parts.append(body[last:m.start()])
        masked_parts.append(" " * (m.end() - m.start()))
        last = m.end()
    masked_parts.append(body[last:])
    return embeds, "".join(masked_parts)


def _extract_wikilinks(masked_body: str) -> list[WikiLink]:
    links: list[WikiLink] = []
    for m in WIKILINK_RE.finditer(masked_body):
        target = m.group(1).strip()
        alias_raw = m.group(2)
        alias = alias_raw.strip() if alias_raw is not None else None
        links.append(WikiLink(target=target, alias=alias))
    return links


def _extract_inline_tags(body: str) -> list[str]:
    """Deduplica preservando ordem de primeira aparicao. Normaliza lowercase."""
    seen: set[str] = set()
    out: list[str] = []
    for m in TAG_IN_BODY_RE.finditer(body):
        tag = m.group(1).lstrip("#").lower()
        if tag and tag not in seen:
            seen.add(tag)
            out.append(tag)
    return out


# ---------- public API ----------

def parse_markdown(text: str) -> ParsedNote:
    """Parseia uma nota Markdown e retorna ParsedNote pronta pro DB.

    Nao crasha em frontmatter malformado — retorna dict vazio e segue.
    `body_hash` e do body apenas (sem frontmatter): duas notas com bodies
    identicos mas frontmatters diferentes produzem o mesmo hash. Isso e
    intencional: scanner detecta mudanca de conteudo independente de fm.
    """
    fm_dict, body, errors = parse_frontmatter(text)
    if errors and not fm_dict:
        # Frontmatter ausente ou totalmente malformado: usa dict vazio pra
        # manter raw_json canonico.
        frontmatter_raw_json = "{}"
    else:
        frontmatter_raw_json = json.dumps(fm_dict, ensure_ascii=False, sort_keys=True)

    embeds, masked = _extract_embeds(body)
    wikilinks = _extract_wikilinks(masked)
    inline_tags = _extract_inline_tags(body)
    word_count = len(body.split())
    body_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()

    return ParsedNote(
        frontmatter_dict=fm_dict,
        frontmatter_raw_json=frontmatter_raw_json,
        body=body,
        wikilinks=wikilinks,
        embeds=embeds,
        inline_tags=inline_tags,
        word_count=word_count,
        body_hash=body_hash,
    )
