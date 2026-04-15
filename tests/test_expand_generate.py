"""Testes para generate.py — note generation com prompt restrito (Epic 05 S04)."""
from __future__ import annotations

import importlib.util
import json
import pathlib
import sys

import numpy as np
import pytest

from core import cli as core_cli
from core.db import connect
from core.scanner import scan

_GENERATE_PATH = (
    pathlib.Path(__file__).resolve().parent.parent
    / "skills"
    / "obsidian-expand"
    / "scripts"
    / "generate.py"
)


def _load_generate():
    name = "expand_generate_tests"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, _GENERATE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class _FakeEmbedder:
    model_name = "fake-gen-v1"
    dim = 256

    def embed(self, texts):
        out = []
        for txt in texts:
            rng = np.random.default_rng(hash(txt) & 0xFFFFFFFF)
            v = rng.standard_normal(256).astype(np.float32)
            v /= np.linalg.norm(v) or 1.0
            out.append(v)
        if not out:
            return np.zeros((0, 256), dtype=np.float32)
        return np.stack(out)


@pytest.fixture(scope="module")
def gen():
    return _load_generate()


@pytest.fixture
def vault_with_suggestion(tmp_path):
    """Vault com 3 notas + 1 suggestion 'bridge' entre duas delas."""
    notas = [
        ("02 - Pesquisas e Estudos/hermetismo.md",
         "# Hermetismo\nO hermetismo antigo aborda a natureza do ser e principios universais."),
        ("02 - Pesquisas e Estudos/alquimia.md",
         "# Alquimia\nA alquimia hermetica busca a transmutacao interior."),
        ("02 - Pesquisas e Estudos/cabala.md",
         "# Cabala\nA cabala estuda a Arvore da Vida e os dez sephirot."),
    ]
    for rel, body in notas:
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    core_cli.main(["init-db", "--vault", str(tmp_path)])
    conn = connect(tmp_path)
    scan(conn, tmp_path, embedder=_FakeEmbedder())
    herm_id = conn.execute(
        "SELECT id FROM notes WHERE path='02 - Pesquisas e Estudos/hermetismo.md'"
    ).fetchone()[0]
    alq_id = conn.execute(
        "SELECT id FROM notes WHERE path='02 - Pesquisas e Estudos/alquimia.md'"
    ).fetchone()[0]
    # Insere suggestion manualmente
    conn.execute(
        """
        INSERT INTO suggestions_cache
          (generated_at, expires_at, kind, target_note_ids,
           content, reasoning, score, dismissed, acted_on)
        VALUES (?, ?, 'bridge', ?, ?, ?, 0.42, 0, 0)
        """,
        (
            "2026-04-15T10:00:00+00:00",
            "2026-04-22T10:00:00+00:00",
            json.dumps([herm_id, alq_id]),
            "Ponte entre [[Hermetismo]] e [[Alquimia]].",
            "[[Hermetismo]] e [[Alquimia]] tem cos=0.42 sem link direto.",
        ),
    )
    conn.commit()
    sug_id = conn.execute(
        "SELECT id FROM suggestions_cache ORDER BY id DESC LIMIT 1"
    ).fetchone()[0]
    return tmp_path, conn, sug_id, (herm_id, alq_id)


# ---------- build_prompt ----------


def test_build_prompt_inclui_regras_duras(gen):
    suggestion = {"kind": "bridge", "content": "x", "reasoning": "por que"}
    sources = [{"title": "Hermetismo", "path": "h.md", "body": "Corpo hermetico."}]
    prompt = gen.build_prompt(suggestion, sources)
    assert "APENAS" in prompt
    assert "NAO invente" in prompt
    assert "NAO cite fontes externas" in prompt
    assert "Nao ha informacao suficiente" in prompt
    assert "[[titulo-da-nota-fonte]]" in prompt or "wikilink" in prompt


def test_build_prompt_inclui_conteudo_das_fontes(gen):
    suggestion = {"kind": "bridge", "content": "x", "reasoning": "y"}
    sources = [
        {"title": "Alfa", "path": "a.md", "body": "Corpo Alfa unico."},
        {"title": "Beta", "path": "b.md", "body": "Corpo Beta distinto."},
    ]
    prompt = gen.build_prompt(suggestion, sources)
    assert "Corpo Alfa unico" in prompt
    assert "Corpo Beta distinto" in prompt
    assert "[[Alfa]]" in prompt
    assert "[[Beta]]" in prompt


def test_build_prompt_task_depende_do_kind(gen):
    for kind in ("bridge", "moc_expand", "reference_missing"):
        suggestion = {"kind": kind, "content": "x", "reasoning": "y"}
        sources = [{"title": "X", "path": "x.md", "body": "corpo"}]
        prompt = gen.build_prompt(suggestion, sources)
        assert "TAREFA:" in prompt


def test_build_prompt_trunca_body_longo(gen):
    big_body = "A" * 10_000
    suggestion = {"kind": "bridge", "content": "x", "reasoning": "y"}
    sources = [{"title": "BigNote", "path": "big.md", "body": big_body}]
    prompt = gen.build_prompt(suggestion, sources)
    assert "conteudo truncado" in prompt
    assert len(prompt) < 10_000  # garantimos reducao substancial


# ---------- generate_note: dry_run ----------


def test_generate_dry_run_retorna_prompt_sem_invocar_llm(gen, vault_with_suggestion):
    vault, conn, sug_id, _ = vault_with_suggestion

    def _exploder(prompt):
        raise AssertionError("LLM nao deveria ser invocado em dry_run")

    result = gen.generate_note(
        conn, sug_id, vault, dry_run=True, llm_invoker=_exploder
    )
    assert result["dry_run"] is True
    assert "prompt" in result and len(result["prompt"]) > 100
    assert "APENAS" in result["prompt"]
    assert "source_paths" in result
    assert len(result["source_paths"]) >= 2
    assert "would_write_to" in result


def test_generate_dry_run_nao_cria_arquivo(gen, vault_with_suggestion):
    vault, conn, sug_id, _ = vault_with_suggestion
    before_files = set(vault.rglob("*.md"))
    gen.generate_note(
        conn, sug_id, vault, dry_run=True, llm_invoker=lambda p: "nao chamar"
    )
    after_files = set(vault.rglob("*.md"))
    assert before_files == after_files


# ---------- generate_note: erros ----------


def test_generate_suggestion_inexistente_retorna_error(gen, vault_with_suggestion):
    vault, conn, _, _ = vault_with_suggestion
    result = gen.generate_note(conn, 99999, vault, dry_run=False)
    assert "error" in result
    assert "nao encontrada" in result["error"]


def test_generate_suggestion_dismissed_retorna_error(gen, vault_with_suggestion):
    vault, conn, sug_id, _ = vault_with_suggestion
    conn.execute("UPDATE suggestions_cache SET dismissed = 1 WHERE id = ?", (sug_id,))
    conn.commit()
    result = gen.generate_note(conn, sug_id, vault, dry_run=False)
    assert "error" in result
    assert "dismissed" in result["error"].lower() or "descartada" in result["error"]


# ---------- generate_note: materializacao com mock LLM ----------


def test_generate_com_mock_llm_escreve_md_com_frontmatter(gen, vault_with_suggestion):
    vault, conn, sug_id, _ = vault_with_suggestion

    mock_body = (
        "# Ponte Hermetismo e Alquimia\n\n"
        "O [[Hermetismo]] estabelece principios que a [[Alquimia]] opera na "
        "materia. Ambas buscam transformacao do interior.\n\n"
        "## Ver tambem\n- [[Hermetismo]]\n- [[Alquimia]]\n"
    )

    def _mock(prompt):
        assert "APENAS" in prompt  # prompt restritivo entregue ao LLM
        return mock_body

    result = gen.generate_note(
        conn, sug_id, vault, dry_run=False, llm_invoker=_mock
    )
    assert "written_path" in result
    written = pathlib.Path(result["written_path"])
    assert written.exists()
    text = written.read_text(encoding="utf-8")
    # Frontmatter
    assert text.startswith("---\n")
    assert "generated_by: obsidian-expand" in text
    assert "status: draft" in text
    assert f"source: suggestion-{sug_id}" in text
    assert "tags: [draft, generated]" in text
    # Body inclui wikilinks
    assert "[[Hermetismo]]" in text
    assert "[[Alquimia]]" in text


def test_generate_marca_acted_on_depois_de_escrever(gen, vault_with_suggestion):
    vault, conn, sug_id, _ = vault_with_suggestion
    gen.generate_note(
        conn, sug_id, vault, dry_run=False, llm_invoker=lambda p: "x [[Hermetismo]]"
    )
    acted = conn.execute(
        "SELECT acted_on FROM suggestions_cache WHERE id = ?", (sug_id,)
    ).fetchone()[0]
    assert acted == 1


def test_generate_llm_sem_wikilinks_prefixa_warning(gen, vault_with_suggestion):
    vault, conn, sug_id, _ = vault_with_suggestion

    def _mock_no_wiki(prompt):
        return "Texto sem wikilinks, so narrativa."

    result = gen.generate_note(
        conn, sug_id, vault, dry_run=False, llm_invoker=_mock_no_wiki
    )
    written = pathlib.Path(result["written_path"])
    text = written.read_text(encoding="utf-8")
    assert "AVISO" in text and "wikilink" in text


def test_generate_pasta_destino_herda_da_primeira_fonte(gen, vault_with_suggestion):
    vault, conn, sug_id, _ = vault_with_suggestion
    result = gen.generate_note(
        conn,
        sug_id,
        vault,
        dry_run=False,
        llm_invoker=lambda p: "[[Hermetismo]] corpo",
    )
    written = pathlib.Path(result["written_path"])
    # Primeira fonte esta em "02 - Pesquisas e Estudos"
    assert written.parent.name == "02 - Pesquisas e Estudos"


def test_generate_retorna_source_paths(gen, vault_with_suggestion):
    vault, conn, sug_id, _ = vault_with_suggestion
    result = gen.generate_note(
        conn, sug_id, vault, dry_run=False, llm_invoker=lambda p: "[[Hermetismo]]"
    )
    assert result["source_paths"]
    assert any("hermetismo" in p for p in result["source_paths"])


# ---------- invoke_llm: isolamento ----------


def test_invoke_llm_erro_de_binario_levanta_runtime(gen, monkeypatch):
    """Se claude CLI nao existe no PATH, levanta RuntimeError descritivo."""
    import subprocess

    def fake_run(*a, **kw):
        raise FileNotFoundError("claude nao existe")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(RuntimeError, match="claude"):
        gen.invoke_llm("teste")
