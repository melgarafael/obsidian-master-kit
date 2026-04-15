"""core/embeddings.py — wrapper canonico de embeddings para o obsidian-master-kit.

Story S04 (Wave 4 / Epic 01).

Contrato firme
--------------
Todos os embedders expostos aqui retornam vetores **L2-normalized**.
Motivacao: com norma unitaria, `cos(a, b) == dot(a, b)`, o que deixa a
similaridade (tanto via numpy quanto via sqlite-vec) consistente e barata.
Consumidores (scanner, organizer, pulse, e a propria camada `vec_notes` do
sqlite-vec) assumem esse invariante.

Dimensao canonica
-----------------
256 dimensoes via Matryoshka Representation Learning (MRL) — o modelo upstream
`static-similarity-mrl-multilingual-v1` e treinado pra que os primeiros K dims
permanecam uteis. Truncamos via `v[:, :256]` e renormalizamos.

Selecao
-------
- Default: `Model2VecEmbedder` (rapido, CPU-only, sem download pesado).
- Fallback opcional: `ParaphraseEmbedder` (sentence-transformers), ativado
  via env var `PARAPHRASE_FALLBACK=1`. Util quando o modelo Model2Vec
  apresenta qualidade ruim em algum nicho — swap sem mexer no schema, ja
  que ambos sao truncados pra 256 + L2-norm.

O caller nao precisa saber qual embedder esta ativo; basta usar
`get_default_embedder()` e consumir `.embed(...)` / `.embed_one(...)`.
"""

from __future__ import annotations

import os
from typing import Protocol

import numpy as np

# Nome canonico registrado no DB (nao muda com bump de pip do model2vec).
CANONICAL_MODEL_NAME = "model2vec-mrl-256"
FALLBACK_MODEL_NAME = "paraphrase-mrl-256-trunc"

# Dim canonica. Qualquer mudanca aqui quebra o schema (notes_embedding_blob
# espera 1024 bytes = 256 float32). Coordenar migration antes de mexer.
CANONICAL_DIM = 256

_UPSTREAM_MODEL2VEC = "sentence-transformers/static-similarity-mrl-multilingual-v1"
_UPSTREAM_PARAPHRASE = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

# Singleton cache — so instanciado via get_default_embedder().
_DEFAULT: "Embedder | None" = None


class Embedder(Protocol):
    """Contrato minimo para qualquer embedder consumido pelo kit.

    Implementadores devem:
    1. Expor `model_name` estavel (usado como chave no DB).
    2. Expor `dim` igual ao shape das saidas.
    3. Retornar ndarrays `float32` L2-normalized de `embed` e `embed_one`.
    """

    model_name: str
    dim: int

    def embed(self, texts: list[str]) -> np.ndarray: ...
    def embed_one(self, text: str) -> np.ndarray: ...


def _l2_normalize(vectors: np.ndarray) -> np.ndarray:
    """L2-normaliza por linha. Norma zero -> vetor zero preservado (sem NaN).

    Retorna float32 sempre (contrato do schema).
    """
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    # Clamp: se norma for zero (input vazio / tokenizer devolveu zeros),
    # divide por 1.0 — vetor continua zero em vez de virar NaN.
    norms = np.where(norms == 0, 1.0, norms)
    return (vectors / norms).astype(np.float32)


class Model2VecEmbedder:
    """Model2Vec static embeddings, truncado pra 256 dims via MRL + L2-norm.

    Requer `model2vec>=0.8.1`. Se a lib nao estiver instalada ou a versao
    for incompativel, o construtor levanta `ImportError` com instrucoes.

    Instancia nao faz cache global — isso e responsabilidade de
    `get_default_embedder()`. Cada `Model2VecEmbedder()` novo carrega o
    modelo (disco local apos primeiro download).
    """

    model_name: str = CANONICAL_MODEL_NAME
    dim: int = CANONICAL_DIM

    def __init__(self, upstream_id: str | None = None, dim: int = CANONICAL_DIM) -> None:
        try:
            from model2vec import StaticModel  # lazy import
        except ImportError as exc:
            raise ImportError(
                "model2vec nao instalado ou incompativel. "
                "Requer >=0.8.1. Instale com: pip install 'model2vec>=0.8.1'"
            ) from exc

        self._model = StaticModel.from_pretrained(upstream_id or _UPSTREAM_MODEL2VEC)
        self.dim = dim

    def embed(self, texts: list[str]) -> np.ndarray:
        """Retorna ndarray shape (N, dim), dtype float32, L2-normalized.

        Input vazio `[]` retorna `(0, dim)` sem chamar o modelo (evita
        bootstrap desnecessario).
        """
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        raw = np.asarray(self._model.encode(texts))
        # MRL slice: os primeiros `dim` componentes ja sao utilizaveis por
        # construcao do modelo mrl-multilingual.
        truncated = raw[:, : self.dim]
        return _l2_normalize(truncated)

    def embed_one(self, text: str) -> np.ndarray:
        """Retorna ndarray shape (dim,), dtype float32, L2-normalized."""
        return self.embed([text])[0]


class ParaphraseEmbedder:
    """Fallback via sentence-transformers `paraphrase-multilingual-MiniLM-L12-v2`.

    Saida original tem 384 dims; truncamos pra 256 via slice simples (crude
    — nao e MRL-treinado) e renormalizamos. Proposito: manter compatibilidade
    de schema com o embedder canonico (mesmo shape de blob).

    Ativado por `PARAPHRASE_FALLBACK=1`. Instalar com:
    `pip install 'obsidian-master-kit[fallback]'`.
    """

    model_name: str = FALLBACK_MODEL_NAME
    dim: int = CANONICAL_DIM

    def __init__(self, dim: int = CANONICAL_DIM) -> None:
        try:
            from sentence_transformers import SentenceTransformer  # lazy import
        except ImportError as exc:
            raise ImportError(
                "sentence-transformers nao instalado. "
                "Instale o extra fallback: pip install 'obsidian-master-kit[fallback]'"
            ) from exc

        self._model = SentenceTransformer(_UPSTREAM_PARAPHRASE)
        self.dim = dim

    def embed(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        raw = np.asarray(
            self._model.encode(texts, normalize_embeddings=False)
        )
        truncated = raw[:, : self.dim]
        return _l2_normalize(truncated)

    def embed_one(self, text: str) -> np.ndarray:
        return self.embed([text])[0]


def pack(vec: np.ndarray) -> bytes:
    """Empacota vetor pra blob binario. 256 float32 = 1024 bytes.

    Bit-preserving: `unpack(pack(v))` retorna array identico via
    `np.array_equal`. Usado pra persistir em `notes_embedding_blob`.
    """
    return np.asarray(vec, dtype=np.float32).tobytes()


def unpack(blob: bytes, dim: int = CANONICAL_DIM) -> np.ndarray:
    """Desempacota blob binario em ndarray float32 shape (dim,)."""
    return np.frombuffer(blob, dtype=np.float32).reshape(dim)


def get_default_embedder() -> Embedder:
    """Retorna embedder default, cacheado em singleton de modulo.

    Selecao:
    - `PARAPHRASE_FALLBACK=1` -> `ParaphraseEmbedder`
    - caso contrario -> `Model2VecEmbedder`

    Chamadas subsequentes retornam a mesma instancia (evita re-load do
    modelo). Pra trocar em runtime (testes), fazer `monkeypatch` em
    `core.embeddings._DEFAULT`.
    """
    global _DEFAULT
    if _DEFAULT is not None:
        return _DEFAULT
    if os.environ.get("PARAPHRASE_FALLBACK") == "1":
        _DEFAULT = ParaphraseEmbedder()
    else:
        _DEFAULT = Model2VecEmbedder()
    return _DEFAULT


__all__ = [
    "CANONICAL_DIM",
    "CANONICAL_MODEL_NAME",
    "FALLBACK_MODEL_NAME",
    "Embedder",
    "Model2VecEmbedder",
    "ParaphraseEmbedder",
    "get_default_embedder",
    "pack",
    "unpack",
]
