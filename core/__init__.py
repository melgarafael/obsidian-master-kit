"""core/ — foundation compartilhado entre skills do obsidian-master-kit.

Contratos expostos:
- `connect(vault_path)` → sqlite3.Connection pronta (schema aplicado)
- `ensure_schema(conn)` → idempotent migrations runner
- `Embedder` / `Model2VecEmbedder` / `get_default_embedder` / `pack` / `unpack`
  → wrapper canonico de embeddings (256d, L2-normalized)
"""

from .db import connect, ensure_schema
from .embeddings import (
    Embedder,
    Model2VecEmbedder,
    get_default_embedder,
    pack,
    unpack,
)
from .features import ParsedNote, parse_markdown, should_reembed
from .graph import find_mocs, update_graph_metrics

__all__ = [
    "Embedder",
    "Model2VecEmbedder",
    "ParsedNote",
    "connect",
    "ensure_schema",
    "find_mocs",
    "get_default_embedder",
    "pack",
    "parse_markdown",
    "should_reembed",
    "unpack",
    "update_graph_metrics",
]
