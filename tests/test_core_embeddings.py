"""Testes unitarios para core.embeddings — Story S04.

Cobre contrato firme da Wave 4:
- embed() sempre retorna L2-normalized float32 shape (N, 256)
- embed_one() retorna (256,) L2-normalized
- embed([]) nao carrega modelo (shape (0, 256) imediato)
- pack/unpack bit-preserving, 256 float32 = 1024 bytes
- singleton de get_default_embedder()
- env var PARAPHRASE_FALLBACK=1 swap para ParaphraseEmbedder
- calibracao pt-br: related cos>0.3, unrelated cos<0.1  (@slow)
- batch 64 em tempo razoavel  (@slow)

Testes marcados `slow` carregam o modelo real (download/cache de ~30MB).
Pra rodar so os rapidos: `pytest -m "not slow"`.
Pra rodar so os lentos:  `pytest -m slow`.
"""

from __future__ import annotations

import time
from typing import Iterator

import numpy as np
import pytest

from core import embeddings as emb_mod
from core.embeddings import (
    CANONICAL_DIM,
    Model2VecEmbedder,
    ParaphraseEmbedder,
    get_default_embedder,
    pack,
    unpack,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_singleton() -> Iterator[None]:
    """Garante isolamento: singleton nunca vaza entre testes."""
    emb_mod._DEFAULT = None
    yield
    emb_mod._DEFAULT = None


@pytest.fixture(scope="module")
def real_embedder() -> Model2VecEmbedder:
    """Uma instancia real do Model2VecEmbedder, reusada em testes slow.

    Carrega o modelo uma vez por modulo pra amortizar o custo.
    """
    return Model2VecEmbedder()


# ---------------------------------------------------------------------------
# pack / unpack — rapidos, sem modelo
# ---------------------------------------------------------------------------


def test_pack_unpack_roundtrip() -> None:
    rng = np.random.default_rng(seed=42)
    v = rng.standard_normal(CANONICAL_DIM).astype(np.float32)
    blob = pack(v)
    restored = unpack(blob)
    assert restored.shape == (CANONICAL_DIM,)
    assert restored.dtype == np.float32
    assert np.array_equal(v, restored), "pack/unpack deveria ser bit-identico"


def test_pack_size_exact() -> None:
    v = np.zeros(CANONICAL_DIM, dtype=np.float32)
    blob = pack(v)
    assert len(blob) == CANONICAL_DIM * 4, "256 float32 = 1024 bytes exatos"
    assert len(blob) == 1024


def test_pack_forces_float32() -> None:
    """pack aceita float64 e converte pra float32 antes de serializar."""
    v = np.ones(CANONICAL_DIM, dtype=np.float64)
    blob = pack(v)
    assert len(blob) == 1024
    restored = unpack(blob)
    assert restored.dtype == np.float32


# ---------------------------------------------------------------------------
# embed([]) — nao deve instanciar modelo
# ---------------------------------------------------------------------------


def test_embed_empty_no_model_call(monkeypatch: pytest.MonkeyPatch) -> None:
    """embed([]) retorna shape (0, 256) sem chamar self._model.encode.

    Usa fake embedder que explode se encode for chamado.
    """

    class _ExplodingModel:
        def encode(self, texts: list[str]) -> np.ndarray:  # noqa: D401
            raise AssertionError("encode nao deveria ser chamado em embed([])")

    # Cria instance sem rodar __init__ (evita load do modelo real).
    inst = Model2VecEmbedder.__new__(Model2VecEmbedder)
    inst._model = _ExplodingModel()  # type: ignore[attr-defined]
    inst.dim = CANONICAL_DIM

    out = inst.embed([])
    assert out.shape == (0, CANONICAL_DIM)
    assert out.dtype == np.float32


# ---------------------------------------------------------------------------
# Singleton + env var
# ---------------------------------------------------------------------------


def test_singleton_default_embedder(monkeypatch: pytest.MonkeyPatch) -> None:
    """get_default_embedder() chamado 2x retorna a mesma instancia."""

    # Substitui Model2VecEmbedder por um dummy pra nao baixar modelo.
    class _DummyEmbedder:
        model_name = "dummy"
        dim = CANONICAL_DIM

        def embed(self, texts: list[str]) -> np.ndarray:
            return np.zeros((len(texts), self.dim), dtype=np.float32)

        def embed_one(self, text: str) -> np.ndarray:
            return np.zeros(self.dim, dtype=np.float32)

    monkeypatch.setattr(emb_mod, "Model2VecEmbedder", _DummyEmbedder)
    monkeypatch.delenv("PARAPHRASE_FALLBACK", raising=False)

    a = get_default_embedder()
    b = get_default_embedder()
    assert a is b, "singleton deveria retornar instancia identica"


def test_env_fallback_selection(monkeypatch: pytest.MonkeyPatch) -> None:
    """PARAPHRASE_FALLBACK=1 -> get_default_embedder() retorna ParaphraseEmbedder.

    Mocka ambas as classes pra evitar downloads de modelo.
    """

    class _FakeParaphrase:
        model_name = "paraphrase-fake"
        dim = CANONICAL_DIM

        def embed(self, texts: list[str]) -> np.ndarray:
            return np.zeros((len(texts), self.dim), dtype=np.float32)

        def embed_one(self, text: str) -> np.ndarray:
            return np.zeros(self.dim, dtype=np.float32)

    class _FakeModel2Vec:
        model_name = "m2v-fake"
        dim = CANONICAL_DIM

        def embed(self, texts: list[str]) -> np.ndarray:
            return np.zeros((len(texts), self.dim), dtype=np.float32)

        def embed_one(self, text: str) -> np.ndarray:
            return np.zeros(self.dim, dtype=np.float32)

    monkeypatch.setattr(emb_mod, "ParaphraseEmbedder", _FakeParaphrase)
    monkeypatch.setattr(emb_mod, "Model2VecEmbedder", _FakeModel2Vec)
    monkeypatch.setenv("PARAPHRASE_FALLBACK", "1")

    inst = get_default_embedder()
    assert isinstance(inst, _FakeParaphrase)


def test_env_default_selects_model2vec(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sem env var, get_default_embedder() retorna Model2VecEmbedder."""

    class _FakeM2V:
        model_name = "m2v-fake"
        dim = CANONICAL_DIM

        def embed(self, texts: list[str]) -> np.ndarray:
            return np.zeros((len(texts), self.dim), dtype=np.float32)

        def embed_one(self, text: str) -> np.ndarray:
            return np.zeros(self.dim, dtype=np.float32)

    monkeypatch.setattr(emb_mod, "Model2VecEmbedder", _FakeM2V)
    monkeypatch.delenv("PARAPHRASE_FALLBACK", raising=False)

    inst = get_default_embedder()
    assert isinstance(inst, _FakeM2V)


# ---------------------------------------------------------------------------
# Contrato de embed com modelo real — slow
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_embed_shape(real_embedder: Model2VecEmbedder) -> None:
    out = real_embedder.embed(["hello", "world"])
    assert out.shape == (2, CANONICAL_DIM)
    assert out.dtype == np.float32


@pytest.mark.slow
def test_embed_one_shape(real_embedder: Model2VecEmbedder) -> None:
    v = real_embedder.embed_one("teste")
    assert v.shape == (CANONICAL_DIM,)
    assert v.dtype == np.float32


@pytest.mark.slow
def test_embed_l2_normalized(real_embedder: Model2VecEmbedder) -> None:
    out = real_embedder.embed(["primeira", "segunda", "terceira frase maior"])
    norms = np.linalg.norm(out, axis=1)
    # Tolerancia 1e-5 — float32 tem ~7 digitos de precisao.
    assert np.allclose(norms, 1.0, atol=1e-5), f"norms fora de 1.0: {norms}"


@pytest.mark.slow
def test_zero_input_no_nan(real_embedder: Model2VecEmbedder) -> None:
    """Input vazio / whitespace nao pode virar NaN/inf.

    Se o tokenizer devolver zero-vector, _l2_normalize clampa norma em 1.0
    e o vetor resultante continua zero (nao NaN).
    """
    out = real_embedder.embed(["", "   ", "\t\n"])
    assert out.shape == (3, CANONICAL_DIM)
    assert not np.isnan(out).any(), "embed de whitespace produziu NaN"
    assert not np.isinf(out).any(), "embed de whitespace produziu inf"


@pytest.mark.slow
def test_calibracao_pt_br_related_vs_unrelated(
    real_embedder: Model2VecEmbedder,
) -> None:
    """Contrato firme: pt-br related cos>0.3, unrelated cos<0.1.

    Se falhar, swap pro fallback via PARAPHRASE_FALLBACK=1 e investigar
    qualidade do modelo multilingual.
    """
    a = real_embedder.embed_one(
        "O hermetismo antigo aborda a natureza do ser e os principios universais"
    )
    b = real_embedder.embed_one(
        "A tabua de esmeralda e um texto hermetico fundamental, como acima assim abaixo"
    )
    c = real_embedder.embed_one(
        "Receita de bolo de chocolate com morango para festa de aniversario"
    )
    # L2-normalized -> cos == dot.
    cos_ab = float(np.dot(a, b))
    cos_ac = float(np.dot(a, c))
    assert cos_ab > 0.3, f"pt-br related cos_ab={cos_ab} <= 0.3 (falha calibracao)"
    assert cos_ac < 0.1, f"pt-br unrelated cos_ac={cos_ac} >= 0.1 (falha calibracao)"


@pytest.mark.slow
def test_batch_performance_reasonable(real_embedder: Model2VecEmbedder) -> None:
    """64 textos curtos em <5s. Bound generoso (CI lento)."""
    texts = [f"frase curta numero {i} para teste de batch" for i in range(64)]
    t0 = time.perf_counter()
    out = real_embedder.embed(texts)
    elapsed = time.perf_counter() - t0
    assert out.shape == (64, CANONICAL_DIM)
    assert elapsed < 5.0, f"batch 64 demorou {elapsed:.2f}s (esperado <5s)"
