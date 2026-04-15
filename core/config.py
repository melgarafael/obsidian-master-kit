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

# --- Expand: gap detection thresholds (Epic 05 S03) ---

# Similaridade minima pra considerar duas notas "proximas o suficiente"
# pra virar candidato a ponte. Model2Vec static comprime a escala de
# cosine (notas relacionadas em pt-br caem em ~0.15-0.50, nao-relacionadas
# em ~-0.10 a 0.05). Default 0.15 e um floor empirico do Wave 4 Epic 01.
# Rafael calibra na vault real via env OBM_BRIDGE_MIN_COS.
BRIDGE_MIN_COS: float = float(os.getenv("OBM_BRIDGE_MIN_COS", "0.15"))

# MOC considerado raso se tem poucos out-links. Paired com regra de area:
# se a area do MOC tem mais notas do que o out_degree*MOC_SHALLOW_RATIO,
# sugere expansao.
MOC_OUT_DEGREE_SHALLOW: int = int(os.getenv("OBM_MOC_OUT_DEGREE_SHALLOW", "5"))
MOC_SHALLOW_RATIO: float = float(os.getenv("OBM_MOC_SHALLOW_RATIO", "2.0"))

# Detector 3 (reference_missing): precisa de ao menos N vizinhos mutuais
# (via KNN graph) pra considerar cluster com tema em comum. N=3 e o minimo
# pra indicar "tema recorrente nao acidental".
CONCEPT_CLUSTER_MIN_MUTUAL: int = int(os.getenv("OBM_CONCEPT_CLUSTER_MIN_MUTUAL", "3"))
CONCEPT_KNN_K: int = int(os.getenv("OBM_CONCEPT_KNN_K", "5"))

# Hard cap de propostas por run — anti-spam explicito (regra do BRIEF).
SUGGESTIONS_PER_RUN_MAX: int = int(os.getenv("OBM_SUGGESTIONS_PER_RUN_MAX", "20"))

# TTL do cache de sugestoes (em dias). Worker do pulse vai regravar.
SUGGESTIONS_TTL_DAYS: int = int(os.getenv("OBM_SUGGESTIONS_TTL_DAYS", "7"))
