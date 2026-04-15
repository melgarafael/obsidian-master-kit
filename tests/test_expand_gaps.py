"""Testes unit para gaps.py — detectores de bridges/moc_expand/reference_missing
(Epic 05 S03 / Wave 3).

Fixture com oportunidades intencionais:
- Dois pares de notas sem link (detector 1)
- Um MOC com pouco out-degree e area com muitas notas (detector 2)
- Um cluster mutual-KNN sem nota type='referencia' (detector 3)
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import sys

import numpy as np
import pytest

from core import cli as core_cli
from core.db import connect
from core.graph import update_graph_metrics
from core.scanner import scan


def _seed_canonical_areas(conn) -> None:
    """Popula areas com os 4 canonicos (migrate skill far isso em prod)."""
    pairs = [
        ("pessoal", "Pessoal", "00 - Pessoal"),
        ("profissional", "Profissional", "01 - Profissional"),
        ("pesquisa", "Pesquisas e Estudos", "02 - Pesquisas e Estudos"),
        ("ai-memory", "Memoria da IA", "03 - Memoria da IA"),
    ]
    for slug, label, folder in pairs:
        conn.execute(
            "INSERT OR IGNORE INTO areas (slug, label, folder, is_canonical, created_at) "
            "VALUES (?, ?, ?, 1, datetime('now'))",
            (slug, label, folder),
        )
    conn.commit()

_GAPS_PATH = (
    pathlib.Path(__file__).resolve().parent.parent
    / "skills"
    / "obsidian-expand"
    / "scripts"
    / "gaps.py"
)


def _load_gaps():
    name = "expand_gaps_tests"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, _GAPS_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class _ClusteredEmbedder:
    """Embedder que agrupa notas por tag conhecida no caminho.

    Se o path contem 'esoterico/' ou 'tech/' ou 'pessoal/', usa o GRUPO
    como seed base de vetor + pequeno jitter per-text. Assim notas do
    mesmo grupo ficam semanticamente proximas (alta cos entre si) sem
    precisar invocar Model2Vec real.

    Fora desses grupos, cai em seed por hash(text) — vetor aleatorio
    por-texto.
    """

    model_name = "fake-clustered-v1"
    dim = 256

    def __init__(self) -> None:
        self._group_vecs: dict[str, np.ndarray] = {}

    def _group_base(self, group: str) -> np.ndarray:
        if group not in self._group_vecs:
            rng = np.random.default_rng(hash(group) & 0xFFFFFFFF)
            v = rng.standard_normal(self.dim).astype(np.float32)
            v /= np.linalg.norm(v) or 1.0
            self._group_vecs[group] = v
        return self._group_vecs[group]

    def embed(self, texts):
        out = []
        for txt in texts:
            group = None
            for g in ("esoterico", "tech", "pessoal"):
                if g in txt.lower():
                    group = g
                    break
            if group:
                base = self._group_base(group)
                # Jitter pequeno (cos com base ~0.95-0.99)
                rng = np.random.default_rng(hash(txt) & 0xFFFFFFFF)
                jitter = rng.standard_normal(self.dim).astype(np.float32) * 0.05
                v = base + jitter
            else:
                rng = np.random.default_rng(hash(txt) & 0xFFFFFFFF)
                v = rng.standard_normal(self.dim).astype(np.float32)
            v /= np.linalg.norm(v) or 1.0
            out.append(v)
        if not out:
            return np.zeros((0, self.dim), dtype=np.float32)
        return np.stack(out)


@pytest.fixture(scope="module")
def gaps():
    return _load_gaps()


@pytest.fixture
def vault_com_oportunidades(tmp_path):
    """Vault construido com gaps intencionais pros 3 detectors."""
    notas = [
        # Grupo esoterico — 4 notas semanticamente proximas, sem cross-links
        ("02 - Pesquisas e Estudos/hermetismo-esoterico.md",
         "# Hermetismo\nTema esoterico sobre principios ocultos."),
        ("02 - Pesquisas e Estudos/alquimia-esoterico.md",
         "# Alquimia\nTema esoterico sobre transmutacao."),
        ("02 - Pesquisas e Estudos/cabala-esoterico.md",
         "# Cabala\nTema esoterico sobre sephirot."),
        ("02 - Pesquisas e Estudos/gnosticismo-esoterico.md",
         "# Gnosticismo\nTema esoterico sobre demiurgo e pleroma."),
        # Grupo tech — MOC raso + algumas notas de tech sem link
        ("01 - Profissional/_MOC.md",
         "---\ntype: moc\n---\n# MOC Profissional tech\n[[projeto-alpha-tech]]"),
        ("01 - Profissional/projeto-alpha-tech.md",
         "# Projeto Alpha tech\nArquitetura."),
        ("01 - Profissional/projeto-beta-tech.md",
         "# Projeto Beta tech\nMicroservico."),
        ("01 - Profissional/projeto-gamma-tech.md",
         "# Projeto Gamma tech\nAPI Gateway."),
        ("01 - Profissional/projeto-delta-tech.md",
         "# Projeto Delta tech\nObservabilidade."),
        # Grupo pessoal — clutter pra nao enviesar
        ("00 - Pessoal/dia-pessoal.md",
         "---\nstatus: ativo\n---\n# Dia pessoal comum\nAnotacoes."),
    ]
    for rel, body in notas:
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    core_cli.main(["init-db", "--vault", str(tmp_path)])
    conn = connect(tmp_path)
    _seed_canonical_areas(conn)
    scan(conn, tmp_path, embedder=_ClusteredEmbedder())
    update_graph_metrics(conn)
    return tmp_path, conn


# ---------- detector 1: bridges ----------


def test_detect_bridges_encontra_pares_sem_link(gaps, vault_com_oportunidades):
    _, conn = vault_com_oportunidades
    candidates = gaps.detect_bridges(conn, min_cos=0.3)
    assert len(candidates) >= 1, "deveria achar >=1 ponte (grupo esoterico)"
    c = candidates[0]
    assert c.kind == "bridge"
    assert len(c.target_note_ids) == 2
    assert c.reasoning.startswith("[[")
    assert "similaridade" in c.reasoning
    assert 0.0 <= c.score <= 1.0


def test_detect_bridges_respeita_min_cos(gaps, vault_com_oportunidades):
    _, conn = vault_com_oportunidades
    # min_cos=0.99 exclui basicamente tudo
    candidates = gaps.detect_bridges(conn, min_cos=0.99)
    assert candidates == []


def test_detect_bridges_nao_inclui_pares_com_link(gaps, vault_com_oportunidades):
    _, conn = vault_com_oportunidades
    # Pega id do MOC + projeto-alpha (tem link MOC -> projeto-alpha)
    moc_id = conn.execute(
        "SELECT id FROM notes WHERE path='01 - Profissional/_MOC.md'"
    ).fetchone()[0]
    alpha_id = conn.execute(
        "SELECT id FROM notes WHERE path='01 - Profissional/projeto-alpha-tech.md'"
    ).fetchone()[0]
    candidates = gaps.detect_bridges(conn, min_cos=-1.0)  # sem threshold
    for c in candidates:
        pair = set(c.target_note_ids)
        assert pair != {moc_id, alpha_id}, (
            "ponte nao pode ser sugerida pra par com link existente"
        )


def test_detect_bridges_dedup_pares_reversos(gaps, vault_com_oportunidades):
    _, conn = vault_com_oportunidades
    candidates = gaps.detect_bridges(conn, min_cos=0.3)
    pairs = [tuple(sorted(c.target_note_ids)) for c in candidates]
    assert len(pairs) == len(set(pairs)), "pares duplicados (A,B)/(B,A)"


def test_detect_bridges_respeita_limit(gaps, vault_com_oportunidades):
    _, conn = vault_com_oportunidades
    candidates = gaps.detect_bridges(conn, min_cos=-1.0, limit=2)
    assert len(candidates) <= 2


# ---------- detector 2: moc_expand ----------


def test_detect_moc_shallow_encontra_moc_raso(gaps, vault_com_oportunidades):
    _, conn = vault_com_oportunidades
    candidates = gaps.detect_moc_shallow(conn)
    assert len(candidates) >= 1, "deveria achar o MOC raso em 01 - Profissional"
    c = candidates[0]
    assert c.kind == "moc_expand"
    assert len(c.target_note_ids) == 1
    assert "MOC" in c.reasoning
    assert "out-links" in c.reasoning
    assert "notas ativas" in c.reasoning


def test_detect_moc_shallow_ignora_moc_denso(gaps, tmp_path):
    """MOC com muitos out-links nao deve gerar candidato."""
    # Constrói vault com MOC que referencia 15 notas da area
    (tmp_path / "area").mkdir()
    moc_body_lines = ["---", "type: moc", "---", "# MOC Denso"]
    for i in range(15):
        path = tmp_path / "area" / f"nota-{i:02d}.md"
        path.write_text(f"# Nota {i}\nbody", encoding="utf-8")
        moc_body_lines.append(f"[[nota-{i:02d}]]")
    (tmp_path / "area" / "_MOC.md").write_text(
        "\n".join(moc_body_lines), encoding="utf-8"
    )
    core_cli.main(["init-db", "--vault", str(tmp_path)])
    conn = connect(tmp_path)
    # Seed area 'area' pra scanner preencher area_id
    conn.execute(
        "INSERT INTO areas (slug, label, folder, is_canonical, created_at) "
        "VALUES ('custom', 'Custom', 'area', 0, datetime('now'))",
    )
    conn.commit()
    scan(conn, tmp_path, embedder=_ClusteredEmbedder())
    update_graph_metrics(conn)
    candidates = gaps.detect_moc_shallow(conn)
    # MOC denso nao deve estar nos candidatos
    moc_id = conn.execute(
        "SELECT id FROM notes WHERE path='area/_MOC.md'"
    ).fetchone()[0]
    assert all(moc_id not in c.target_note_ids for c in candidates)


# ---------- detector 3: reference_missing ----------


def test_detect_reference_missing_encontra_cluster_sem_referencia(gaps, vault_com_oportunidades):
    _, conn = vault_com_oportunidades
    candidates = gaps.detect_reference_missing(conn)
    # Grupo esoterico deve disparar (4 notas proximas, nenhuma type='referencia')
    assert len(candidates) >= 1
    c = candidates[0]
    assert c.kind == "reference_missing"
    assert len(c.target_note_ids) >= 3
    assert "cluster" in c.reasoning.lower() or "similaridade" in c.reasoning.lower()
    assert "referencia" in c.reasoning.lower()


def test_detect_reference_missing_ignora_cluster_com_nota_referencia(gaps, tmp_path):
    """Cluster semantico com uma nota type='referencia' nao deve aparecer."""
    notas = [
        ("02 - Pesquisas e Estudos/ref-esoterico.md",
         "---\ntype: referencia\n---\n# Ref esoterica central\nConceito."),
        ("02 - Pesquisas e Estudos/tema-a-esoterico.md",
         "# Tema A esoterico\nTexto."),
        ("02 - Pesquisas e Estudos/tema-b-esoterico.md",
         "# Tema B esoterico\nTexto."),
        ("02 - Pesquisas e Estudos/tema-c-esoterico.md",
         "# Tema C esoterico\nTexto."),
        ("02 - Pesquisas e Estudos/tema-d-esoterico.md",
         "# Tema D esoterico\nTexto."),
    ]
    for rel, body in notas:
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    core_cli.main(["init-db", "--vault", str(tmp_path)])
    conn = connect(tmp_path)
    scan(conn, tmp_path, embedder=_ClusteredEmbedder())
    candidates = gaps.detect_reference_missing(conn)
    # Se gerou algum, nenhum deve incluir o cluster inteiro (pois tem ref)
    ref_id = conn.execute(
        "SELECT id FROM notes WHERE path='02 - Pesquisas e Estudos/ref-esoterico.md'"
    ).fetchone()[0]
    # O ref pode aparecer em candidato, mas o cluster esoterico inteiro (com ref)
    # nao deve ser reportado como "missing reference" — testamos que se houver
    # candidato cobrindo a nota ref, isso e inconsistente.
    # Assertiva: nenhum candidato inclui ref_id (pois ela JA e referencia).
    for c in candidates:
        assert ref_id not in c.target_note_ids, (
            "cluster que contem type=referencia nao deve virar reference_missing"
        )


# ---------- run_all + persist ----------


def test_run_all_intercala_tipos(gaps, vault_com_oportunidades):
    _, conn = vault_com_oportunidades
    candidates = gaps.run_all(conn)
    kinds = [c.kind for c in candidates]
    # Deve conter pelo menos 2 tipos diferentes (interleaving garante diversidade
    # enquanto ha material disponivel)
    assert len(set(kinds)) >= 2


def test_run_all_respeita_cap(gaps, vault_com_oportunidades):
    _, conn = vault_com_oportunidades
    candidates = gaps.run_all(conn, limit=3)
    assert len(candidates) <= 3


def test_persist_grava_em_suggestions_cache(gaps, vault_com_oportunidades):
    _, conn = vault_com_oportunidades
    candidates = gaps.run_all(conn, limit=3)
    if not candidates:
        pytest.skip("fixture nao gerou candidates — skip")
    count = gaps.persist(conn, candidates)
    assert count == len(candidates)
    rows = conn.execute(
        "SELECT kind, reasoning, target_note_ids, score FROM suggestions_cache "
        "ORDER BY id DESC LIMIT ?",
        (count,),
    ).fetchall()
    assert len(rows) == count
    for kind, reasoning, targets_json, score in rows:
        assert kind in ("bridge", "moc_expand", "reference_missing")
        assert reasoning is not None and len(reasoning) > 10
        # target_note_ids deve ser JSON array valido
        assert isinstance(json.loads(targets_json), list)
        assert score is not None


def test_persist_vazio_retorna_zero(gaps, vault_com_oportunidades):
    _, conn = vault_com_oportunidades
    assert gaps.persist(conn, []) == 0
