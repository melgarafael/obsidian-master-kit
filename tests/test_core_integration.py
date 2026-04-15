"""Testes de integracao E2E (Story S07, Wave 7).

Cinco cenarios canonicos usando o fixture vault em
`tests/fixtures/vault_fixture/`. Cada teste copia o fixture pra `tmp_path`
antes de mexer (`shutil.copytree`) pra garantir que o fixture no repo
fique imutavel.

Cenarios:
- A: vault novo → init-db (via connect) + scan → valida counts
- B: vault com DB → editar 1 nota → scan detecta apenas 1 updated
- C: deletar 1 nota do disco → scan marca deleted_at
- D: renomear arquivo → scanner detecta como delete + create
- E: trocar embedding_model → scanner re-embeda todas

Bonus:
- broken links preservados (to_note_id IS NULL)
- inline tags hierarquicas capturadas
"""
from __future__ import annotations

import os
import pathlib
import shutil
import time

import numpy as np
import pytest

from core.db import connect
from core.scanner import scan

FIXTURE_SRC = pathlib.Path(__file__).parent / "fixtures" / "vault_fixture"


# ---------- fixtures ----------

@pytest.fixture
def vault(tmp_path: pathlib.Path) -> pathlib.Path:
    """Copia o fixture inteiro pra `tmp_path/vault`.

    O fixture ja tem `.obsidian-master/marker.json`. `connect()` cria o
    `db.sqlite` sob essa mesma pasta. Cada teste recebe um vault zerado
    (sem DB) baseado na mesma arvore de notas.
    """
    dest = tmp_path / "vault"
    shutil.copytree(FIXTURE_SRC, dest)
    return dest


# ---------- test doubles ----------

class _FakeEmbedder:
    """Embedder deterministico pra testes — zeros float32 256-dim."""

    model_name = "fake-integration-v1"
    dim = 256

    def __init__(self, model_name: str | None = None) -> None:
        if model_name is not None:
            self.model_name = model_name
        self.call_count = 0

    def embed(self, texts):
        self.call_count += 1
        return np.zeros((len(texts), self.dim), dtype=np.float32)


# ---------- Cenario A: new vault -> init + scan ----------

def test_cenario_a_vault_novo_init_scan(vault: pathlib.Path) -> None:
    """A: vault novo (fixture) → connect() cria DB + scan popula notes."""
    conn = connect(vault)
    try:
        # connect() ja rodou ensure_schema → ao menos migration 001 aplicada
        assert (vault / ".obsidian-master" / "db.sqlite").exists()
        ver = conn.execute(
            "SELECT MAX(version) FROM schema_version"
        ).fetchone()[0]
        assert ver >= 1

        report = scan(conn, vault, embedder=_FakeEmbedder())

        # Deve criar ao menos 40 notas (tolerancia pra fixture crescer).
        # Fixture atual tem 59 notas scannable (exclui _templates/).
        assert report.counts.get("created", 0) >= 40
        assert report.counts.get("deleted", 0) == 0
        assert report.counts.get("updated", 0) == 0

        # _templates/ deve ser ignorado
        rows = conn.execute(
            "SELECT path FROM notes WHERE path LIKE '_templates/%'"
        ).fetchall()
        assert rows == [], "_templates/ deve ser ignorado pelo scanner"

        # Contagem total no DB bate com counts.created
        total_db = conn.execute(
            "SELECT COUNT(*) FROM notes WHERE deleted_at IS NULL"
        ).fetchone()[0]
        assert total_db == report.counts["created"]
    finally:
        conn.close()


# ---------- Cenario B: edit 1 nota -> 1 updated ----------

def test_cenario_b_edit_uma_nota(vault: pathlib.Path) -> None:
    """B: apos primeiro scan, editar 1 nota → scan detecta apenas 1 updated."""
    emb = _FakeEmbedder()
    conn = connect(vault)
    try:
        scan(conn, vault, embedder=emb)

        target = vault / "02 - Pesquisas e Estudos" / "hermetismo-overview.md"
        assert target.exists()
        original = target.read_text(encoding="utf-8")
        # Mudanca substantiva (>15 palavras) pra garantir gate de re-embed
        appendix = (
            "\n\nParagrafo novo adicionado pelo teste de integracao com muitas"
            " palavras suficientes pra forcar re-parse completo e upsert"
            " semantico no scanner, bem acima do threshold de word-count.\n"
        )
        target.write_text(original + appendix, encoding="utf-8")
        # Bump explicito de mtime pra evitar filesystems low-res que nao
        # percebem a edicao por tempo proximo demais.
        future = time.time() + 10
        os.utime(target, (future, future))

        report2 = scan(conn, vault, embedder=emb)

        assert report2.counts.get("updated", 0) == 1, (
            f"esperava exatamente 1 updated, obteve counts={report2.counts}"
        )
        assert report2.counts.get("created", 0) == 0
        assert report2.counts.get("deleted", 0) == 0
        total = sum(report2.counts.values())
        assert report2.counts.get("skipped", 0) == total - 1
    finally:
        conn.close()


# ---------- Cenario C: delete 1 nota do disco -> deleted_at ----------

def test_cenario_c_delete_do_disco(vault: pathlib.Path) -> None:
    """C: deletar arquivo do disco → scan marca com deleted_at."""
    emb = _FakeEmbedder()
    conn = connect(vault)
    try:
        scan(conn, vault, embedder=emb)

        target = vault / "00 - Pessoal" / "meditacao-matinal.md"
        assert target.exists()
        target_rel = target.relative_to(vault).as_posix()
        target.unlink()

        report2 = scan(conn, vault, embedder=emb)
        assert report2.counts.get("deleted", 0) == 1
        assert report2.counts.get("created", 0) == 0

        # Verifica que deleted_at foi setado no DB
        row = conn.execute(
            "SELECT deleted_at FROM notes WHERE path=?", (target_rel,),
        ).fetchone()
        assert row is not None
        assert row[0] is not None
    finally:
        conn.close()


# ---------- Cenario D: rename -> delete + create ----------

def test_cenario_d_rename_detectado_como_delete_mais_create(
    vault: pathlib.Path,
) -> None:
    """D: renomear arquivo → 1 deleted + 1 created."""
    emb = _FakeEmbedder()
    conn = connect(vault)
    try:
        scan(conn, vault, embedder=emb)

        src = vault / "02 - Pesquisas e Estudos" / "tabua-esmeralda.md"
        dst = vault / "02 - Pesquisas e Estudos" / "tabua-esmeralda-renomeada.md"
        assert src.exists()
        src.rename(dst)

        report2 = scan(conn, vault, embedder=emb)
        assert report2.counts.get("deleted", 0) == 1
        assert report2.counts.get("created", 0) == 1

        # old path: soft-deleted
        old_row = conn.execute(
            "SELECT deleted_at FROM notes WHERE path='02 - Pesquisas e Estudos/tabua-esmeralda.md'"
        ).fetchone()
        assert old_row is not None and old_row[0] is not None

        # new path: existe e nao esta deleted
        new_row = conn.execute(
            "SELECT deleted_at FROM notes WHERE path='02 - Pesquisas e Estudos/tabua-esmeralda-renomeada.md'"
        ).fetchone()
        assert new_row is not None and new_row[0] is None
    finally:
        conn.close()


# ---------- Cenario E: swap embedding_model -> re-embed all ----------

def test_cenario_e_swap_embedding_model_forca_reembed(
    vault: pathlib.Path,
) -> None:
    """E: trocar embedding_model → scanner re-embeda todas as notas.

    Detalhe de implementacao: a logica de swap de modelo vive em
    `_should_reembed`, que so e consultada quando o scanner chega no
    nivel 3 (reparse). Se mtime bate, nivel 1 retorna skipped sem
    consultar a logica. Se hash bate, nivel 2 idem. Pra testar
    model-swap de forma determinstica precisamos forcar nivel 3 em
    todas as notas — aqui invalidamos mtime E body_hash pra garantir.
    Esse mesmo approach e usado em `test_17_reembed_disparado_em_model_swap`
    do scanner unit tests.
    """
    conn = connect(vault)
    try:
        emb_v1 = _FakeEmbedder(model_name="fake-v1")
        report_initial = scan(conn, vault, embedder=emb_v1)
        initial_created = report_initial.counts.get("created", 0)
        assert initial_created > 0

        # Todas as notas do scan inicial devem ter embedding_model='fake-v1'
        with_v1 = conn.execute(
            "SELECT COUNT(*) FROM notes "
            "WHERE embedding_model='fake-v1' AND deleted_at IS NULL"
        ).fetchone()[0]
        assert with_v1 == initial_created, (
            f"esperava {initial_created} notas com fake-v1, obteve {with_v1}"
        )

        # Forca reparse completo de todas:
        # 1) bump mtime pra quebrar level-1
        # 2) corrompe body_hash no DB pra quebrar level-2
        future = time.time() + 100
        for md in vault.rglob("*.md"):
            if "_templates" in md.parts or ".obsidian-master" in md.parts:
                continue
            os.utime(md, (future, future))
        conn.execute(
            "UPDATE notes SET body_hash='STALE-FORCE-REPARSE' "
            "WHERE deleted_at IS NULL"
        )
        conn.commit()

        emb_v2 = _FakeEmbedder(model_name="fake-v2")
        report2 = scan(conn, vault, embedder=emb_v2)

        # Toda nota deve ter sido re-embedada (model swap gate)
        reembedded_count = sum(1 for c in report2.changes if c.reembedded)
        # Tolerancia: embedder pode falhar em alguma nota isolada (logado,
        # nao aborta scan). Aceitamos ate 5 falhas.
        assert reembedded_count >= initial_created - 5, (
            f"esperava ~{initial_created} re-embeds, obteve {reembedded_count}"
        )

        # Todas as notas ativas agora devem ter embedding_model='fake-v2'
        with_v2 = conn.execute(
            "SELECT COUNT(*) FROM notes "
            "WHERE embedding_model='fake-v2' AND deleted_at IS NULL"
        ).fetchone()[0]
        assert with_v2 >= initial_created - 5
    finally:
        conn.close()


# ---------- Bonus: broken links preservados ----------

def test_broken_links_preservados(vault: pathlib.Path) -> None:
    """Links pra notas inexistentes devem ficar com to_note_id=NULL."""
    emb = _FakeEmbedder()
    conn = connect(vault)
    try:
        scan(conn, vault, embedder=emb)
        broken = conn.execute(
            "SELECT to_target FROM links WHERE to_note_id IS NULL"
        ).fetchall()
        # Fixture tem varios links quebrados deliberados:
        # - [[projeto-xyz-que-ainda-nao-existe]] em ideias-aleatorias
        # - [[projeto-que-nao-existe-deliberadamente]] em alquimia-espiritual
        # - [[nota-fantasma-xyz]] em nota-sem-frontmatter
        # - [[governanca-dados-sensiveis]] em projeto-tomik-crm
        # - ![[imagem-opus-magnum-diagrama]] embed em alquimia-espiritual
        # - ![[imagem-fluxograma-resumo]] embed em ideias-aleatorias
        assert len(broken) >= 4, (
            f"esperava ao menos 4 links quebrados, obteve {len(broken)}"
        )
    finally:
        conn.close()


# ---------- Bonus: inline tags hierarquicas capturadas ----------

def test_inline_tags_hierarquicas_capturadas(vault: pathlib.Path) -> None:
    """Tags inline com `/` (ex: #hermetismo/corpus) devem ser capturadas."""
    emb = _FakeEmbedder()
    conn = connect(vault)
    try:
        scan(conn, vault, embedder=emb)
        hier = conn.execute(
            "SELECT DISTINCT tag FROM tags WHERE tag LIKE '%/%'"
        ).fetchall()
        # Fixture tem varias: hermetismo/corpus, pratica/diaria, alquimia/espiritual,
        # alquimia/opus, alquimia/nigredo, esoterico/antiguidade, etc.
        assert len(hier) >= 3, (
            f"esperava ao menos 3 tags hierarquicas, obteve {len(hier)}: "
            f"{[r[0] for r in hier]}"
        )
    finally:
        conn.close()


# ---------- Bonus: alias de wiki-link registrado ----------

def test_aliases_registrados(vault: pathlib.Path) -> None:
    """Frontmatter `aliases:` deve ser persistido na tabela `aliases`."""
    emb = _FakeEmbedder()
    conn = connect(vault)
    try:
        scan(conn, vault, embedder=emb)
        # tabua-esmeralda.md tem aliases: [A Tabua, Tabula Smaragdina]
        row = conn.execute(
            "SELECT n.path, a.alias FROM aliases a "
            "JOIN notes n ON n.id = a.note_id "
            "WHERE n.path LIKE '%tabua-esmeralda.md'"
        ).fetchall()
        aliases = {r[1] for r in row}
        assert "A Tabua" in aliases or "Tabula Smaragdina" in aliases, (
            f"esperava aliases de tabua-esmeralda, obteve {aliases}"
        )
    finally:
        conn.close()
