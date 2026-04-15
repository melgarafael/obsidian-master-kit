"""Tests for core.parser — parse_markdown() + ParsedNote.

Cobre os 22 casos do wave-2-plan.md. Cada teste: um input, uma asserção por
comportamento. Sem fixtures — pytest direto.
"""
from __future__ import annotations

import json

import pytest

from core.parser import ParsedNote, WikiLink, parse_markdown


# ---------- frontmatter ----------

def test_frontmatter_valido_simples():
    text = "---\ntitle: Foo\narea: pessoal\n---\ncorpo aqui\n"
    r = parse_markdown(text)
    assert r.frontmatter_dict == {"title": "Foo", "area": "pessoal"}
    assert r.body == "corpo aqui\n"


def test_frontmatter_multi_line_list():
    text = "---\ntags:\n  - a\n  - b\n---\ncorpo\n"
    r = parse_markdown(text)
    assert r.frontmatter_dict == {"tags": ["a", "b"]}


def test_frontmatter_inline_list():
    text = "---\ntags: [a, b, c]\n---\ncorpo\n"
    r = parse_markdown(text)
    assert r.frontmatter_dict == {"tags": ["a", "b", "c"]}


def test_sem_frontmatter():
    text = "# Titulo direto\n\nsem frontmatter aqui\n"
    r = parse_markdown(text)
    assert r.frontmatter_dict == {}
    assert r.body == text  # body e o texto inteiro quando nao ha frontmatter
    assert r.frontmatter_raw_json == "{}"


def test_frontmatter_malformado_retorna_dict_vazio_body_intacto():
    # Linha sem `:` no meio do frontmatter — parser reporta erro mas continua.
    text = "---\ntitle: Foo\nlinha_sem_dois_pontos\narea: pessoal\n---\ncorpo\n"
    r = parse_markdown(text)
    # `title` e `area` foram parseados; so a linha problematica e ignorada.
    assert r.frontmatter_dict.get("title") == "Foo"
    assert r.frontmatter_dict.get("area") == "pessoal"
    assert r.body == "corpo\n"
    # Nao crashou.
    assert isinstance(r, ParsedNote)


# ---------- wiki-links e embeds ----------

def test_wikilink_simples():
    text = "corpo com [[Foo]] link\n"
    r = parse_markdown(text)
    assert r.wikilinks == [WikiLink(target="Foo", alias=None)]
    assert r.embeds == []


def test_wikilink_com_alias():
    text = "veja [[Foo|Bar]] aqui\n"
    r = parse_markdown(text)
    assert r.wikilinks == [WikiLink(target="Foo", alias="Bar")]


def test_wikilink_com_path():
    text = "ref [[00 - Area/Foo]]\n"
    r = parse_markdown(text)
    assert r.wikilinks == [WikiLink(target="00 - Area/Foo", alias=None)]


def test_embed_nao_vai_em_wikilinks():
    text = "olha: ![[Foo]]\n"
    r = parse_markdown(text)
    assert r.embeds == ["Foo"]
    assert r.wikilinks == []  # embed NAO deve cair em wikilinks


def test_embed_e_wikilink_na_mesma_linha():
    text = "![[img.png]] veja [[Outra]]\n"
    r = parse_markdown(text)
    assert r.embeds == ["img.png"]
    assert r.wikilinks == [WikiLink(target="Outra", alias=None)]


# ---------- inline tags ----------

def test_inline_tag_simples():
    text = "um corpo com #tag aqui\n"
    r = parse_markdown(text)
    assert r.inline_tags == ["tag"]


def test_inline_tag_hierarquica():
    text = "estudo de #area/tipo hoje\n"
    r = parse_markdown(text)
    assert r.inline_tags == ["area/tipo"]


def test_tag_no_meio_de_palavra_nao_conta():
    text = "isso nao e tag: foo#bar\n"
    r = parse_markdown(text)
    assert r.inline_tags == []


def test_tags_frontmatter_e_inline_sao_campos_separados():
    text = "---\ntags: [fm-a, fm-b]\n---\ncorpo com #corpo-x aqui\n"
    r = parse_markdown(text)
    assert r.frontmatter_dict["tags"] == ["fm-a", "fm-b"]
    # inline_tags contem SO o que veio do body, nao do frontmatter
    assert r.inline_tags == ["corpo-x"]
    assert "fm-a" not in r.inline_tags


# ---------- body_hash ----------

def test_body_hash_igual_pra_inputs_iguais():
    text = "---\ntitle: X\n---\ncorpo identico\n"
    r1 = parse_markdown(text)
    r2 = parse_markdown(text)
    assert r1.body_hash == r2.body_hash


def test_body_hash_diferente_pra_mudancas_pequenas():
    t1 = "corpo A\n"
    t2 = "corpo B\n"
    assert parse_markdown(t1).body_hash != parse_markdown(t2).body_hash


# ---------- word_count ----------

def test_word_count_texto_simples():
    text = "uma duas tres quatro cinco\n"
    r = parse_markdown(text)
    assert r.word_count == 5


# ---------- frontmatter preservation ----------

def test_aliases_no_frontmatter_preservados():
    text = "---\naliases: [Foo Bar, Baz]\n---\ncorpo\n"
    r = parse_markdown(text)
    assert r.frontmatter_dict["aliases"] == ["Foo Bar", "Baz"]


def test_frontmatter_raw_json_preserva_campos_custom():
    text = "---\ncampo_x: valor_custom\nconfidence: 0.9\n---\ncorpo\n"
    r = parse_markdown(text)
    parsed = json.loads(r.frontmatter_raw_json)
    assert parsed["campo_x"] == "valor_custom"
    assert parsed["confidence"] == 0.9


# ---------- edge cases ----------

def test_wikilink_dentro_de_code_fence_ainda_capturado():
    # v1: capturamos; futura exclusao e outra wave.
    text = "```\n[[DentroDoCodigo]]\n```\n"
    r = parse_markdown(text)
    assert WikiLink(target="DentroDoCodigo", alias=None) in r.wikilinks


def test_emoji_no_conteudo_nao_quebra():
    text = "---\ntitle: Teste\n---\ncorpo com emoji aqui e [[Link]]\n"
    r = parse_markdown(text)
    assert r.wikilinks == [WikiLink(target="Link", alias=None)]
    # body preserva o emoji em UTF-8
    assert r.body.startswith("corpo com emoji")


def test_frontmatter_vazio_dict_vazio_body_intacto():
    text = "---\n---\ncorpo aqui\n"
    r = parse_markdown(text)
    assert r.frontmatter_dict == {}
    assert r.body == "corpo aqui\n"


# ---------- bonus: deduplicacao e json canonico ----------

def test_inline_tags_deduplicadas_preservando_ordem():
    text = "#alpha blah #beta mais #alpha outra vez\n"
    r = parse_markdown(text)
    assert r.inline_tags == ["alpha", "beta"]


def test_frontmatter_raw_json_e_sort_keys():
    # sort_keys=True garante que a serializacao e determinstica.
    text = "---\nz_last: 1\na_first: 2\n---\ncorpo\n"
    r = parse_markdown(text)
    # chaves devem aparecer em ordem alfabetica no JSON
    idx_a = r.frontmatter_raw_json.index("a_first")
    idx_z = r.frontmatter_raw_json.index("z_last")
    assert idx_a < idx_z
