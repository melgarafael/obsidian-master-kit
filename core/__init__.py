"""core/ — foundation compartilhado entre skills do obsidian-master-kit.

Contratos expostos:
- `connect(vault_path)` → sqlite3.Connection pronta (schema aplicado)
- `ensure_schema(conn)` → idempotent migrations runner
"""

from .db import connect, ensure_schema

__all__ = ["connect", "ensure_schema"]
