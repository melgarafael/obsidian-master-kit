"""Canonical configuration constants for obsidian-master-kit core.

Epic 01 defines the baseline; Agente 02 estende em Epics 05/06 com
thresholds de ML (BRIDGE_MIN_COS, DUPLICATE_MIN_COS, etc) sem
reescrever o que esta aqui.

Convencao: env vars prefixo OBM_ (obsidian-master) pra nao colidir.
"""
from __future__ import annotations
import os

# --- Embeddings (Wave 4) ---

EMBEDDING_UPSTREAM_MODEL = os.getenv(
    "OBM_EMBEDDING_MODEL",
    "sentence-transformers/static-similarity-mrl-multilingual-v1",
)
EMBEDDING_DIM: int = 256

# --- Graph (Wave 5) ---

PAGERANK_ALPHA: float = 0.85
PAGERANK_MAX_ITER: int = 100

# --- Vault paths (relativos a raiz do vault) ---

DB_PATH_REL: str = ".obsidian-master/db.sqlite"
BLACKLIST_PATH_REL: str = ".obsidian-master/blacklist.json"
IGNORE_PATH_REL: str = ".obsidian-master/ignore.txt"

# --- Scanner re-embed gate (Wave 3) ---

REEMBED_WORD_COUNT_DELTA_THRESHOLD: float = 0.15
REEMBED_BODY_PREFIX_CHARS: int = 500
