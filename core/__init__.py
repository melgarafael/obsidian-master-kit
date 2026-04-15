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

__all__ = [
    "Embedder",
    "Model2VecEmbedder",
    "connect",
    "ensure_schema",
    "get_default_embedder",
    "pack",
    "unpack",
]
