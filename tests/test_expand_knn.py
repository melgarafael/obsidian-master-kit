"""Testes para KNN engine (Epic 05 S02 / Wave 2).

Divisao:
- Fast (default): mecanica — exclusoes, filtros, ordenacao, fallback.
  Usa `_DeterministicEmbedder` (hash-based, L2-normalized, mas sem
  semantica real).
- Slow (`-m slow`): vizinhos semanticamente relacionados usando
  Model2Vec real; benchmark de latencia.
"""
from __future__ import annotations

import importlib.util
import pathlib
import time

import numpy as np
import pytest

from core import cli as core_cli
from core.db import connect
from core.scanner import scan

_KNN_PATH = (
    pathlib.Path(__file__).resolve().parent.parent
    / "skills"
    / "obsidian-expand"
    / "scripts"
    / "knn.py"
)


def _load_knn():
    spec = importlib.util.spec_from_file_location("expand_knn", _KNN_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def knn_mod():
    return _load_knn()


# ---------- test doubles ----------


class _DeterministicEmbedder:
    """Gera vetor reproducivel por texto (hash-seeded) L2-normalized.

    Util pra testar mecanica de KNN sem carregar Model2Vec real: textos
    identicos -> vetor identico; textos diferentes -> vetores com
    distancia nao-trivial.
    """

    model_name = "fake-deterministic-v1"
    dim = 256

    def embed(self, texts):
        out = []
        for txt in texts:
            seed = hash(txt) & 0xFFFFFFFF
            rng = np.random.default_rng(seed)
            vec = rng.standard_normal(self.dim).astype(np.float32)
            norm = np.linalg.norm(vec) or 1.0
            out.append(vec / norm)
        if not out:
            return np.zeros((0, self.dim), dtype=np.float32)
        return np.stack(out)


@pytest.fixture
def vault_com_notas(tmp_path):
    """Cria vault com 10 notas textualmente distintas e rodou um scan."""
    notas = [
        ("01 - Profissional/projeto-alpha.md", "# Projeto Alpha\n\nTexto A sobre gestao de produto."),
        ("01 - Profissional/projeto-beta.md", "# Projeto Beta\n\nTexto B sobre arquitetura de software."),
        ("02 - Pesquisas e Estudos/hermetismo.md", "# Hermetismo\n\nPrincipios herm sobre natureza do ser."),
        ("02 - Pesquisas e Estudos/alquimia.md", "# Alquimia\n\nArte hermetica da transmutacao."),
        ("02 - Pesquisas e Estudos/cabala.md", "# Cabala\n\nTradicao esoterica judaica com Arvore da Vida."),
        ("00 - Pessoal/journaling-a.md", "# Journal A\n\nReflexoes do dia com varios pensamentos."),
        ("00 - Pessoal/journaling-b.md", "# Journal B\n\nMais pensamentos em outro dia qualquer."),
        ("03 - Memoria da IA/contexto-1.md", "# Contexto 1\n\nMemoria da IA sobre usuario."),
        ("03 - Memoria da IA/contexto-2.md", "# Contexto 2\n\nOutra memoria com preferencias."),
        ("01 - Profissional/arquivada.md", "---\nstatus: arquivado\n---\n# Arquivada\n\nNao deve aparecer."),
    ]
    for rel, body in notas:
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")

    core_cli.main(["init-db", "--vault", str(tmp_path)])
    conn = connect(tmp_path)
    scan(conn, tmp_path, embedder=_DeterministicEmbedder())
    return tmp_path, conn


# ---------- 1. degenerates ----------


def test_knn_k_zero_retorna_vazio(knn_mod, vault_com_notas):
    _, conn = vault_com_notas
    note_id = conn.execute("SELECT id FROM notes LIMIT 1").fetchone()[0]
    assert knn_mod.knn(conn, note_id, k=0) == []


def test_knn_note_sem_embedding_retorna_vazio(knn_mod, tmp_path):
    core_cli.main(["init-db", "--vault", str(tmp_path)])
    conn = connect(tmp_path)
    try:
        conn.execute(
            "INSERT INTO notes (path, title, deleted_at) VALUES (?, ?, NULL)",
            ("dummy.md", "dummy"),
        )
        conn.commit()
        nid = conn.execute("SELECT id FROM notes WHERE path='dummy.md'").fetchone()[0]
        assert knn_mod.knn(conn, nid, k=5) == []
    finally:
        conn.close()


def test_knn_vault_vazio_retorna_vazio(knn_mod, tmp_path):
    core_cli.main(["init-db", "--vault", str(tmp_path)])
    conn = connect(tmp_path)
    try:
        # Nenhuma nota — knn com id arbitrario retorna []
        assert knn_mod.knn(conn, 1, k=5) == []
    finally:
        conn.close()


# ---------- 2. exclusoes ----------


def test_knn_nao_inclui_propria_nota(knn_mod, vault_com_notas):
    _, conn = vault_com_notas
    note_id = conn.execute(
        "SELECT id FROM notes WHERE path='01 - Profissional/projeto-alpha.md'"
    ).fetchone()[0]
    results = knn_mod.knn(conn, note_id, k=20)
    assert all(nid != note_id for nid, _ in results)


def test_knn_exclui_arquivadas(knn_mod, vault_com_notas):
    _, conn = vault_com_notas
    arq_id = conn.execute(
        "SELECT id FROM notes WHERE path='01 - Profissional/arquivada.md'"
    ).fetchone()[0]
    # Query a partir de outra nota qualquer
    seed = conn.execute(
        "SELECT id FROM notes WHERE path='02 - Pesquisas e Estudos/hermetismo.md'"
    ).fetchone()[0]
    results = knn_mod.knn(conn, seed, k=50)
    assert all(nid != arq_id for nid, _ in results), (
        "nota com status=arquivado nao pode aparecer em knn"
    )


def test_knn_exclui_deleted_at(knn_mod, vault_com_notas):
    _, conn = vault_com_notas
    # Soft-delete uma nota
    deleted_path = "00 - Pessoal/journaling-a.md"
    conn.execute(
        "UPDATE notes SET deleted_at = datetime('now') WHERE path = ?",
        (deleted_path,),
    )
    conn.commit()
    deleted_id = conn.execute(
        "SELECT id FROM notes WHERE path = ?", (deleted_path,)
    ).fetchone()[0]
    seed = conn.execute(
        "SELECT id FROM notes WHERE path='00 - Pessoal/journaling-b.md'"
    ).fetchone()[0]
    results = knn_mod.knn(conn, seed, k=50)
    assert all(nid != deleted_id for nid, _ in results)


# ---------- 3. tamanho + ordenacao ----------


def test_knn_retorna_no_maximo_k(knn_mod, vault_com_notas):
    _, conn = vault_com_notas
    seed = conn.execute("SELECT id FROM notes LIMIT 1").fetchone()[0]
    results = knn_mod.knn(conn, seed, k=3)
    assert len(results) <= 3


def test_knn_retorna_menos_que_k_em_vault_pequeno(knn_mod, vault_com_notas):
    _, conn = vault_com_notas
    # Vault tem 10 notas (1 arquivada). k=100 pede mais que existe.
    seed = conn.execute(
        "SELECT id FROM notes WHERE path='02 - Pesquisas e Estudos/hermetismo.md'"
    ).fetchone()[0]
    results = knn_mod.knn(conn, seed, k=100)
    # Deve retornar no maximo 8 (10 total - 1 query - 1 arquivada)
    assert len(results) <= 8
    assert len(results) >= 1


def test_knn_distances_ordenadas_asc(knn_mod, vault_com_notas):
    _, conn = vault_com_notas
    seed = conn.execute("SELECT id FROM notes LIMIT 1").fetchone()[0]
    results = knn_mod.knn(conn, seed, k=20)
    distances = [d for _, d in results]
    assert distances == sorted(distances), "distances devem ser asc"


def test_knn_retorna_tipos_corretos(knn_mod, vault_com_notas):
    _, conn = vault_com_notas
    seed = conn.execute("SELECT id FROM notes LIMIT 1").fetchone()[0]
    results = knn_mod.knn(conn, seed, k=5)
    for nid, dist in results:
        assert isinstance(nid, int)
        assert isinstance(dist, float)
        assert dist >= 0.0  # L2 distance em unit vectors in [0, 2]


# ---------- 4. fallback path (sem sqlite-vec) ----------


def test_knn_fallback_produz_ranking_equivalente(knn_mod, vault_com_notas, monkeypatch):
    """Path vec0 e path blob-scan devem produzir rankings equivalentes.

    Testamos forcando vec_loaded=False no segundo run e comparando IDs
    (distances podem diferir em epsilon numerico, mas ordem relativa deve
    casar).
    """
    _, conn = vault_com_notas
    seed = conn.execute(
        "SELECT id FROM notes WHERE path='02 - Pesquisas e Estudos/hermetismo.md'"
    ).fetchone()[0]
    results_vec0 = knn_mod.knn(conn, seed, k=5)

    # Popula notes_embedding_blob com as mesmas vecs do vec_notes pra permitir
    # fallback funcionar (scanner ja faz um ou outro, nao ambos).
    rows = conn.execute("SELECT note_id, embedding FROM vec_notes").fetchall()
    for note_id, blob in rows:
        conn.execute(
            "INSERT OR REPLACE INTO notes_embedding_blob (note_id, vec) "
            "VALUES (?, ?)",
            (note_id, blob),
        )
    conn.commit()

    # Forca fallback
    conn.vec_loaded = False
    results_fallback = knn_mod.knn(conn, seed, k=5)

    ids_vec0 = [nid for nid, _ in results_vec0]
    ids_fallback = [nid for nid, _ in results_fallback]
    assert ids_vec0 == ids_fallback, (
        f"vec0 path {ids_vec0} != fallback path {ids_fallback} "
        "— rankings devem ser equivalentes em unit vectors"
    )


# ---------- 5. slow: semantica real + benchmark ----------


@pytest.mark.slow
def test_knn_vizinhos_sao_semanticamente_relacionados(knn_mod, tmp_path):
    """Com Model2Vec real, 2 notas sobre tema X devem ficar mais proximas
    entre si do que de uma nota sobre tema Y completamente diferente.

    Nao testamos threshold absoluto (static embeddings comprimem escala —
    ver Epic 01 Wave 4 calibracao). Testamos so RANKING relativo.
    """
    notas = [
        ("02 - Pesquisas e Estudos/hermetismo-1.md",
         "Hermetismo antigo aborda natureza do ser e principios universais do cosmos."),
        ("02 - Pesquisas e Estudos/hermetismo-2.md",
         "Tabua de esmeralda texto hermetico fundamental, como acima assim abaixo."),
        ("02 - Pesquisas e Estudos/alquimia.md",
         "Alquimia espiritual tradicional obra em negro branco vermelho transmutacao interior."),
        ("00 - Pessoal/receita.md",
         "Receita de bolo de chocolate com morango pra festa de aniversario, 2 ovos, farinha."),
        ("00 - Pessoal/compras.md",
         "Lista de compras para o mercado esta semana: arroz, feijao, oleo, sabao."),
    ]
    for rel, body in notas:
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")

    from core.embeddings import get_default_embedder

    core_cli.main(["init-db", "--vault", str(tmp_path)])
    conn = connect(tmp_path)
    scan(conn, tmp_path, embedder=get_default_embedder())

    hermetismo_id = conn.execute(
        "SELECT id FROM notes WHERE path='02 - Pesquisas e Estudos/hermetismo-1.md'"
    ).fetchone()[0]
    results = knn_mod.knn(conn, hermetismo_id, k=4)
    paths = [
        conn.execute("SELECT path FROM notes WHERE id=?", (nid,)).fetchone()[0]
        for nid, _ in results
    ]
    # Top-1 ou top-2 vizinhos devem ser esotericos (hermetismo-2 ou alquimia)
    top2 = paths[:2]
    assert any("hermetismo-2" in p or "alquimia" in p for p in top2), (
        f"esperava nota esoterica em top-2, obteve {top2}"
    )
    # Top-1 NAO deve ser receita/compras
    assert "receita" not in paths[0]
    assert "compras" not in paths[0]


@pytest.mark.slow
def test_knn_performance_vault_1k_menor_que_200ms(knn_mod, tmp_path):
    """Benchmark conservador: k=20 em vault de 1000 notas < 200ms.

    Target do story e 100ms em 5k; benchmark aqui e proxy mais leve pra CI.
    """
    core_cli.main(["init-db", "--vault", str(tmp_path)])
    # Gera 1000 notas fake
    for i in range(1000):
        (tmp_path / f"nota-{i:04d}.md").write_text(
            f"# Nota {i}\n\nConteudo unico numero {i} com variacao lexical.",
            encoding="utf-8",
        )
    conn = connect(tmp_path)
    scan(conn, tmp_path, embedder=_DeterministicEmbedder())
    seed = conn.execute("SELECT id FROM notes LIMIT 1").fetchone()[0]

    t0 = time.perf_counter()
    results = knn_mod.knn(conn, seed, k=20)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    assert len(results) == 20
    assert elapsed_ms < 200.0, f"knn demorou {elapsed_ms:.1f}ms (alvo < 200ms)"
