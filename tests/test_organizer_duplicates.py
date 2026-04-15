"""Testes para duplicates.py (Epic 04 S03 / Wave 3)."""
from __future__ import annotations

import importlib.util
import pathlib
import sys

import numpy as np
import pytest

from core import cli as core_cli
from core.db import connect
from core.scanner import scan

_PATH = (
    pathlib.Path(__file__).resolve().parent.parent
    / "skills" / "obsidian-organizer" / "scripts" / "duplicates.py"
)


def _load():
    name = "organizer_duplicates_tests"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, _PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class _NearDuplicateEmbedder:
    """Notas com prefixo comum 'DUP_' ficam quase-identicas (cos >= 0.95).
    Outras sao distintas.
    """

    model_name = "fake-dup-v1"
    dim = 256

    def __init__(self):
        self._base = None

    def _shared(self):
        if self._base is None:
            rng = np.random.default_rng(12345)
            v = rng.standard_normal(self.dim).astype(np.float32)
            v /= np.linalg.norm(v) or 1.0
            self._base = v
        return self._base

    def embed(self, texts):
        out = []
        for t in texts:
            if "DUP_" in t:
                base = self._shared()
                rng = np.random.default_rng(hash(t) & 0xFFFF)
                v = base + rng.standard_normal(self.dim).astype(np.float32) * 0.02
            else:
                rng = np.random.default_rng(hash(t) & 0xFFFFFFFF)
                v = rng.standard_normal(self.dim).astype(np.float32)
            v /= np.linalg.norm(v) or 1.0
            out.append(v)
        if not out:
            return np.zeros((0, self.dim), dtype=np.float32)
        return np.stack(out)


@pytest.fixture(scope="module")
def dup():
    return _load()


@pytest.fixture
def vault_com_duplicatas(tmp_path):
    notas = [
        ("cabala-DUP_a.md", "# Cabala\nDUP_ conteudo sobre arvore da vida."),
        ("qabalah-DUP_b.md", "# Qabalah\nDUP_ mesma arvore da vida em escrita latina."),
        ("hermetismo.md", "# Hermetismo\nassunto distinto."),
        ("cozinha.md", "# Cozinha\noutro assunto."),
    ]
    for rel, body in notas:
        (tmp_path / rel).write_text(body, encoding="utf-8")
    core_cli.main(["init-db", "--vault", str(tmp_path)])
    conn = connect(tmp_path)
    scan(conn, tmp_path, embedder=_NearDuplicateEmbedder())
    return tmp_path, conn


# ---------- detect_duplicates ----------


def test_detect_duplicates_encontra_par_similar(dup, vault_com_duplicatas):
    _, conn = vault_com_duplicatas
    pairs = dup.detect_duplicates(conn, min_cos=0.7)
    assert len(pairs) >= 1
    pair = pairs[0]
    assert "note_a_id" in pair and "note_b_id" in pair
    assert pair["cos"] >= 0.7
    assert pair["note_a_id"] < pair["note_b_id"]  # dedup ordenado


def test_detect_duplicates_respeita_min_cos(dup, vault_com_duplicatas):
    _, conn = vault_com_duplicatas
    # Com threshold altissimo, nada
    pairs = dup.detect_duplicates(conn, min_cos=0.99999)
    # Ambos DUP_ sao near-identical (~0.99+), pode ainda pegar 1 ou 0
    assert all(p["cos"] >= 0.99999 for p in pairs)


def test_detect_duplicates_ignora_sufixo_numerico(dup, tmp_path):
    """Notas com titulos 'projeto-01', 'projeto-02' nao sao duplicatas."""
    for i in range(2):
        (tmp_path / f"projeto-{i:02d}.md").write_text(
            f"# projeto-{i:02d}\nDUP_ texto", encoding="utf-8"
        )
    core_cli.main(["init-db", "--vault", str(tmp_path)])
    conn = connect(tmp_path)
    scan(conn, tmp_path, embedder=_NearDuplicateEmbedder())
    pairs = dup.detect_duplicates(conn, min_cos=0.5)
    assert pairs == [], (
        "titulos com sufixo numerico comum nao devem virar duplicata"
    )


def test_detect_duplicates_ignora_pares_ja_julgados(dup, vault_com_duplicatas):
    _, conn = vault_com_duplicatas
    initial = dup.detect_duplicates(conn, min_cos=0.7)
    assert len(initial) >= 1
    # Grava com verdict 'not_duplicate'
    p = initial[0]
    conn.execute(
        "INSERT INTO duplicate_candidates "
        "(note_a_id, note_b_id, cosine_similarity, detected_at, verdict) "
        "VALUES (?, ?, ?, datetime('now'), 'not_duplicate')",
        (p["note_a_id"], p["note_b_id"], p["cos"]),
    )
    conn.commit()
    after = dup.detect_duplicates(conn, min_cos=0.7)
    # O par julgado nao deve reaparecer
    judged = (p["note_a_id"], p["note_b_id"])
    for r in after:
        assert (r["note_a_id"], r["note_b_id"]) != judged


# ---------- save_candidates ----------


def test_save_candidates_grava_em_duplicate_candidates(dup, vault_com_duplicatas):
    _, conn = vault_com_duplicatas
    pairs = dup.detect_duplicates(conn, min_cos=0.7)
    count = dup.save_candidates(conn, pairs)
    assert count == len(pairs)
    rows = conn.execute(
        "SELECT note_a_id, note_b_id, verdict FROM duplicate_candidates"
    ).fetchall()
    assert len(rows) == count
    for _, _, verdict in rows:
        assert verdict is None


def test_save_candidates_dedup_par_ja_inserido(dup, vault_com_duplicatas):
    _, conn = vault_com_duplicatas
    pairs = dup.detect_duplicates(conn, min_cos=0.7)
    count1 = dup.save_candidates(conn, pairs)
    count2 = dup.save_candidates(conn, pairs)  # idempotente
    assert count1 == len(pairs)
    assert count2 == 0


def test_save_vazio_retorna_zero(dup, vault_com_duplicatas):
    _, conn = vault_com_duplicatas
    assert dup.save_candidates(conn, []) == 0


# ---------- list_pending ----------


def test_list_pending_retorna_sem_verdict(dup, vault_com_duplicatas):
    _, conn = vault_com_duplicatas
    pairs = dup.detect_duplicates(conn, min_cos=0.7)
    dup.save_candidates(conn, pairs)
    pending = dup.list_pending(conn)
    assert len(pending) == len(pairs)
    assert all(p["a_title"] is not None for p in pending)


def test_list_pending_exclui_ja_julgados(dup, vault_com_duplicatas):
    _, conn = vault_com_duplicatas
    pairs = dup.detect_duplicates(conn, min_cos=0.7)
    dup.save_candidates(conn, pairs)
    # Julga todos
    conn.execute(
        "UPDATE duplicate_candidates SET verdict = 'keep_both' "
        "WHERE verdict IS NULL"
    )
    conn.commit()
    assert dup.list_pending(conn) == []
