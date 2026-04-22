"""Read/write YAML frontmatter em notas markdown."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Tuple

import yaml

_FRONTMATTER_RE = re.compile(
    r"\A---\s*\n(.*?)^---\s*\n?(.*)\Z", re.DOTALL | re.MULTILINE
)


def parse_frontmatter(text: str) -> Tuple[dict, str]:
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    raw, body = m.group(1), m.group(2)
    meta = yaml.safe_load(raw) or {}
    if not isinstance(meta, dict):
        return {}, text
    return meta, body


def read_frontmatter(path: Path) -> Tuple[dict, str]:
    return parse_frontmatter(Path(path).read_text(encoding="utf-8"))


def serialize_frontmatter(meta: dict, body: str) -> str:
    if not meta:
        return body
    dumped = yaml.safe_dump(
        meta, allow_unicode=True, sort_keys=False, default_flow_style=False,
    ).rstrip("\n")
    return f"---\n{dumped}\n---\n\n{body.lstrip()}"


def write_frontmatter(path: Path, meta: dict, body: str) -> None:
    Path(path).write_text(serialize_frontmatter(meta, body), encoding="utf-8")
