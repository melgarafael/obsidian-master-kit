"""Tests for core.scanner — scan() + scan_single_file() + delta 3-nivel.

18 cenarios especificados em `.epic-executor/wave-3-plan.md` (Story S03).
Usa `tmp_path` pra vaults throwaway e `_FakeEmbedder` pra isolamento de
modelos reais.
"""
from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from core.db import connect
from core.scanner import NoteChange, ScanReport, scan, scan_single_file


# ---------- test double ----------

class _FakeEmbedder:
    """Embedder determinstico pra testes. `responses` e um map texto→vetor
    opcional; qualquer texto nao mapeado retorna zeros.

    `dim=256` alinha com `vec_notes` (float[256], hardcoded em core/db.py).
    Isso e canonico por BRIEF §3.1 (Model2Vec MRL truncado a 256).
    """

    model_name = "fake-test-v1"
    dim = 256

    def __init__(self, responses: dict[str, np.ndarray] | None = None,
                 model_name: str = "fake-test-v1") -> None:
        self.model_name = model_name
        self._responses = responses or {}
        self.call_count = 0
        self.embedded_texts: list[str] = []

    def embed(self, texts):
        self.call_count += 1
        out = []
        for t in texts:
            self.embedded_texts.append(t)
            v = self._responses.get(t)
            if v is None:
                v = np.zeros(self.dim, dtype=np.float32)
            out.append(v)
        return np.asarray(out, dtype=np.float32)


# ---------- fixture helpers ----------

def _mk_note(vault: Path, rel: str, body: str, frontmatter: str = "") -> Path:
    """Cria um arquivo .md no vault e retorna o path absoluto."""
    path = vault / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    if frontmatter:
        content = f"---\n{frontmatter}\n---\n{body}"
    else:
        content = body
    path.write_text(content, encoding="utf-8")
    return path


# ---------- tests ----------

def test_01_vault_vazio(tmp_path: Path) -> None:
    conn = connect(tmp_path)
    try:
        report = scan(conn, tmp_path)
        assert isinstance(report, ScanReport)
        assert report.counts == {"created": 0, "updated": 0, "deleted": 0, "skipped": 0}
        assert report.changes == []
        assert report.duration_s >= 0
    finally:
        conn.close()


def test_02_vault_com_3_notas_created(tmp_path: Path) -> None:
    _mk_note(tmp_path, "a.md", "corpo a\n")
    _mk_note(tmp_path, "b.md", "corpo b\n")
    _mk_note(tmp_path, "c.md", "corpo c\n")
    conn = connect(tmp_path)
    try:
        report = scan(conn, tmp_path)
        assert report.counts["created"] == 3
        assert report.counts["updated"] == 0
        # todas as 3 devem estar no DB
        rows = conn.execute("SELECT path FROM notes ORDER BY path").fetchall()
        paths = [r[0] for r in rows]
        assert paths == ["a.md", "b.md", "c.md"]
    finally:
        conn.close()


def test_03_rescan_imediato_skipped(tmp_path: Path) -> None:
    _mk_note(tmp_path, "a.md", "corpo a\n")
    _mk_note(tmp_path, "b.md", "corpo b\n")
    _mk_note(tmp_path, "c.md", "corpo c\n")
    conn = connect(tmp_path)
    try:
        scan(conn, tmp_path)  # warm-up
        report = scan(conn, tmp_path)
        assert report.counts["skipped"] == 3
        assert report.counts["created"] == 0
        assert report.counts["updated"] == 0
    finally:
        conn.close()


def test_04_editar_nota_updated(tmp_path: Path) -> None:
    a = _mk_note(tmp_path, "a.md", "corpo a\n")
    _mk_note(tmp_path, "b.md", "corpo b\n")
    _mk_note(tmp_path, "c.md", "corpo c\n")
    conn = connect(tmp_path)
    try:
        scan(conn, tmp_path)
        # editar a.md e empurrar mtime pra frente
        time.sleep(0.01)
        a.write_text("corpo a MUDADO e expandido\n", encoding="utf-8")
        # bump mtime explicitamente pra evitar filesystems low-res
        future = time.time() + 2
        os.utime(a, (future, future))

        report = scan(conn, tmp_path)
        assert report.counts["updated"] == 1
        assert report.counts["skipped"] == 2
    finally:
        conn.close()


def test_05_mtime_touch_sem_mudanca_conteudo_hash_hit(tmp_path: Path) -> None:
    """Level 2 hash hit: mtime mudou mas body_hash igual → update so mtime."""
    a = _mk_note(tmp_path, "a.md", "corpo identico\n")
    conn = connect(tmp_path)
    try:
        scan(conn, tmp_path)
        # touch sem mudar conteudo
        future = time.time() + 10
        os.utime(a, (future, future))

        report = scan(conn, tmp_path)
        assert report.counts["skipped"] == 1
        assert report.counts["updated"] == 0
        # mtime no DB foi atualizado pra o novo valor (nao ficou stale)
        row = conn.execute("SELECT mtime FROM notes WHERE path='a.md'").fetchone()
        assert abs(row[0] - future) < 1.0
    finally:
        conn.close()


def test_06_body_hash_corrompido_forca_reparse(tmp_path: Path) -> None:
    """Nivel 2 hash hit funciona ao contrario tambem: se o hash no DB ta
    errado (corrompido/stale), o reparse recalcula. Precisa bumpar mtime
    pra ultrapassar level-1."""
    a = _mk_note(tmp_path, "a.md", "conteudo real\n")
    conn = connect(tmp_path)
    try:
        scan(conn, tmp_path)
        # corrompe o hash no DB E bumpa mtime pra passar level-1
        conn.execute("UPDATE notes SET body_hash='DEADBEEF' WHERE path='a.md'")
        conn.commit()
        future = time.time() + 5
        os.utime(a, (future, future))

        report = scan(conn, tmp_path)
        # level-1 falhou (mtime diff), level-2 falhou (hash diff) → level-3
        # reparse. Como conteudo real nao mudou, word_count/title iguais →
        # re-parse rola, mas no codigo isso e 'updated' (o upsert roda).
        # Aceitamos updated OU skipped (se level-2 rodar o update de mtime).
        # O importante: o hash foi recalculado.
        row = conn.execute("SELECT body_hash FROM notes WHERE path='a.md'").fetchone()
        assert row[0] != "DEADBEEF"
    finally:
        conn.close()


def test_07_delete_arquivo_marca_deleted_at(tmp_path: Path) -> None:
    a = _mk_note(tmp_path, "a.md", "vai sumir\n")
    _mk_note(tmp_path, "b.md", "vai ficar\n")
    conn = connect(tmp_path)
    try:
        scan(conn, tmp_path)
        a.unlink()

        report = scan(conn, tmp_path)
        assert report.counts["deleted"] == 1
        row = conn.execute(
            "SELECT deleted_at FROM notes WHERE path='a.md'"
        ).fetchone()
        assert row[0] is not None
    finally:
        conn.close()


def test_08_ignore_patterns_fixos(tmp_path: Path) -> None:
    _mk_note(tmp_path, "normal.md", "visivel\n")
    _mk_note(tmp_path, ".obsidian/workspace.md", "ignored\n")
    _mk_note(tmp_path, "_templates/tpl.md", "template ignored\n")
    _mk_note(tmp_path, "node_modules/foo/bar.md", "dep ignored\n")
    conn = connect(tmp_path)
    try:
        report = scan(conn, tmp_path)
        paths = {c.path for c in report.changes}
        assert "normal.md" in paths
        # os 3 ignorados nao devem aparecer em changes
        assert not any(".obsidian" in p for p in paths)
        assert not any("_templates" in p for p in paths)
        assert not any("node_modules" in p for p in paths)
    finally:
        conn.close()


def test_09_ignore_txt_extension(tmp_path: Path) -> None:
    _mk_note(tmp_path, "normal.md", "visivel\n")
    _mk_note(tmp_path, "archive/old.md", "a ignorar via custom\n")
    # ignore.txt customizado — .obsidian-master ja existe por virtude do connect()
    kit = tmp_path / ".obsidian-master"
    kit.mkdir(exist_ok=True)
    (kit / "ignore.txt").write_text("archive\n", encoding="utf-8")

    conn = connect(tmp_path)
    try:
        report = scan(conn, tmp_path)
        paths = {c.path for c in report.changes}
        assert "normal.md" in paths
        assert not any("archive" in p for p in paths)
    finally:
        conn.close()


def test_10_scan_single_file_updated(tmp_path: Path) -> None:
    a = _mk_note(tmp_path, "a.md", "original\n")
    conn = connect(tmp_path)
    try:
        scan(conn, tmp_path)
        a.write_text("mudou muito mais expandido aqui\n", encoding="utf-8")
        future = time.time() + 5
        os.utime(a, (future, future))

        change = scan_single_file(conn, tmp_path, a)
        assert isinstance(change, NoteChange)
        assert change.kind == "updated"
        assert change.path == "a.md"
        assert change.note_id is not None
    finally:
        conn.close()


def test_11_scan_single_file_created(tmp_path: Path) -> None:
    conn = connect(tmp_path)
    try:
        # nota ainda nem existe no DB — scan single deve criar
        a = _mk_note(tmp_path, "nova.md", "conteudo novo\n")
        change = scan_single_file(conn, tmp_path, a)
        assert change.kind == "created"
        assert change.path == "nova.md"
        # esta no DB agora
        row = conn.execute(
            "SELECT id FROM notes WHERE path='nova.md'"
        ).fetchone()
        assert row is not None
    finally:
        conn.close()


def test_12_links_quebrados_preservam_intent(tmp_path: Path) -> None:
    _mk_note(tmp_path, "a.md", "veja [[NotaInexistente]] aqui\n")
    conn = connect(tmp_path)
    try:
        scan(conn, tmp_path)
        rows = conn.execute(
            "SELECT to_note_id, to_target FROM links "
            "WHERE to_target='NotaInexistente'"
        ).fetchall()
        assert len(rows) == 1
        assert rows[0][0] is None  # quebrado
        assert rows[0][1] == "NotaInexistente"
    finally:
        conn.close()


def test_13_wikilink_resolve_por_title(tmp_path: Path) -> None:
    # Duas notas; uma com frontmatter title, outra linkando por titulo
    _mk_note(
        tmp_path, "pasta/destino.md",
        "conteudo\n",
        frontmatter="title: Meu Destino",
    )
    _mk_note(tmp_path, "origem.md", "eu linko [[Meu Destino]] aqui\n")
    conn = connect(tmp_path)
    try:
        scan(conn, tmp_path)
        # buscar o link da origem → deve ter resolvido
        rows = conn.execute(
            "SELECT l.to_note_id, n.path FROM links l "
            "LEFT JOIN notes n ON n.id=l.to_note_id "
            "WHERE l.to_target='Meu Destino'"
        ).fetchall()
        assert len(rows) == 1
        assert rows[0][0] is not None
        assert rows[0][1] == "pasta/destino.md"
    finally:
        conn.close()


def test_14_inline_tag_hierarquica(tmp_path: Path) -> None:
    _mk_note(tmp_path, "a.md", "uso #profissional/projeto aqui\n")
    conn = connect(tmp_path)
    try:
        scan(conn, tmp_path)
        rows = conn.execute("SELECT tag FROM tags").fetchall()
        tags = {r[0] for r in rows}
        assert "profissional/projeto" in tags
        # ligacao N:N existe
        row = conn.execute("""
            SELECT COUNT(*) FROM note_tags nt
            JOIN tags t ON t.id=nt.tag_id
            WHERE t.tag='profissional/projeto'
        """).fetchone()
        assert row[0] == 1
    finally:
        conn.close()


def test_15_reembed_disparado_por_delta_word_count(tmp_path: Path) -> None:
    # nota com 10 palavras; edicao vai pra >15 palavras → Δ > 15%
    body = " ".join(f"palavra{i}" for i in range(10))
    a = _mk_note(tmp_path, "a.md", body + "\n")
    embedder = _FakeEmbedder()
    conn = connect(tmp_path)
    try:
        report1 = scan(conn, tmp_path, embedder=embedder)
        # primeira vez: re-embed ocorre (new note)
        calls_after_first = embedder.call_count
        assert calls_after_first >= 1
        assert report1.changes[0].reembedded is True

        # edicao que adiciona >50% das palavras
        new_body = body + " " + " ".join(f"extra{i}" for i in range(20))
        a.write_text(new_body + "\n", encoding="utf-8")
        future = time.time() + 5
        os.utime(a, (future, future))

        report2 = scan(conn, tmp_path, embedder=embedder)
        assert embedder.call_count > calls_after_first
        assert report2.counts["updated"] == 1
        assert report2.changes[0].reembedded is True
    finally:
        conn.close()


def test_16_reembed_NAO_disparado_em_typos(tmp_path: Path) -> None:
    # 20 palavras, typo numa letra → word_count estavel, title igual
    words = [f"palavra{i}" for i in range(20)]
    body = " ".join(words)
    a = _mk_note(tmp_path, "a.md", body + "\n")
    embedder = _FakeEmbedder()
    conn = connect(tmp_path)
    try:
        scan(conn, tmp_path, embedder=embedder)
        calls_after_first = embedder.call_count

        # typo: muda 'palavra5' pra 'palavraX' — 1 char difere, word_count igual
        fixed = body.replace("palavra5", "palavraX")
        a.write_text(fixed + "\n", encoding="utf-8")
        future = time.time() + 5
        os.utime(a, (future, future))

        report = scan(conn, tmp_path, embedder=embedder)
        # body_hash mudou → kind='updated', mas re-embed nao deve disparar
        assert report.counts["updated"] == 1
        assert report.changes[0].reembedded is False
        assert embedder.call_count == calls_after_first
    finally:
        conn.close()


def test_17_reembed_disparado_em_model_swap(tmp_path: Path) -> None:
    """Swap de modelo forca re-embed. Pra chegar na logica de swap,
    precisamos chegar em _process_file level-3 — isso exige que o mtime OU
    hash tenha mudado. Simulamos invalidando o hash E bumping mtime."""
    a = _mk_note(tmp_path, "a.md", "corpo qualquer\n")
    embedder_v1 = _FakeEmbedder(model_name="model-v1")
    conn = connect(tmp_path)
    try:
        scan(conn, tmp_path, embedder=embedder_v1)
        row = conn.execute(
            "SELECT embedding_model FROM notes WHERE path='a.md'"
        ).fetchone()
        assert row[0] == "model-v1"

        # segundo scan com embedder de outro modelo. Precisamos forcar
        # reparse (stat diff) pra logica de swap ter chance de rodar.
        future = time.time() + 10
        os.utime(a, (future, future))
        # forcando hash inconsistente pra evitar level-2 skip (body_hash
        # ainda igual). Mexer no hash do DB faz o level-2 falhar → level-3.
        conn.execute("UPDATE notes SET body_hash='STALE' WHERE path='a.md'")
        conn.commit()

        embedder_v2 = _FakeEmbedder(model_name="model-v2")
        scan(conn, tmp_path, embedder=embedder_v2)
        assert embedder_v2.call_count >= 1
        row = conn.execute(
            "SELECT embedding_model FROM notes WHERE path='a.md'"
        ).fetchone()
        assert row[0] == "model-v2"
    finally:
        conn.close()


def test_18_performance_50_notas_reasonable(tmp_path: Path) -> None:
    """Scan + rescan de 50 notas < 5s (bound generoso). Smoke de performance."""
    for i in range(50):
        _mk_note(tmp_path, f"nota_{i:03d}.md", f"corpo da nota {i}\n")
    conn = connect(tmp_path)
    try:
        r1 = scan(conn, tmp_path)
        assert r1.counts["created"] == 50
        r2 = scan(conn, tmp_path)
        assert r2.counts["skipped"] == 50
        assert r1.duration_s < 5.0
        assert r2.duration_s < 5.0
    finally:
        conn.close()
