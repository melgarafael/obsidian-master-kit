---
name: obsidian-organizer
description: Esta skill deve ser usada quando o usuario diz "organiza meu vault", "ve o que esta bagunçado", "sugere consolidações", "detecta duplicatas", "confere os MOCs", ou invoca `/obsidian-master-kit:organize`. Roda clustering HDBSCAN sobre os embeddings do vault, detecta pares proximos (cos >= DUPLICATE_MIN_COS) que sao candidatos a duplicata conceitual, encontra clusters grandes sem MOC proprio, flagga notas com `area` no frontmatter divergente da pasta onde moram, e propoe tudo em `migration_plan` pra aprovacao humana. NUNCA move ou apaga arquivos sem verdict explicito.
---

# obsidian-organizer

Organizador semantico do vault. Varre tudo com IA, detecta bagunca, propoe consolidacoes. 100% local, zero side-effects sem aprovacao.

## Quando usar

- Usuario diz "organiza meu vault", "limpa duplicatas", "expande MOCs",
  "o que ta bagunçado?".
- Usuario invoca `/obsidian-master-kit:organize`.
- Apos um scan completo (`obsidian-master scan`) — organizer consome
  dados de `notes` + `vec_notes`/`notes_embedding_blob`.

## Quando **nao** usar

- Em vault vazio ou com < 10 notas (HDBSCAN nao tem material).
- Sem ter rodado scan primeiro.
- Pra ACAO destrutiva — organizer SO propoe; `obsidian-migrate apply`
  executa os moves/merges aprovados.

## Fluxo canonico

### Passo 1: Detecte o vault

Walk ancestrais do cwd procurando `.obsidian-master/marker.json`. Se
nao achar, aborte com `--vault PATH`.

### Passo 2: Garanta scan recente

Se notes+vec estao desatualizados, peca ao usuario pra rodar `obsidian-master scan` primeiro.

### Passo 3: Escolha o sub-comando

| Intencao do usuario | Sub-comando |
|---|---|
| "Agrupa as notas parecidas" / "Cluster semantico" | `cluster` |
| "Acha duplicatas de conceito" | `duplicates` |
| "Quais clusters faltam MOC?" | `moc-audit` |
| "Area do frontmatter bate com a pasta?" | `area-mismatch` |
| "Propoe tudo em lotes pra eu aprovar" | `propose` |
| "Me da o relatorio visual" | `report` |

### Passo 4: Invoque o script

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/obsidian-organizer/scripts/organizer.py \
  <sub-comando> [--vault PATH] [--dry-run] [opcoes]
```

### Passo 5: Apresente em pt-br humano

O script emite JSON estavel. Traduza pra markdown com reasoning embaixo:

```
3 candidatos de duplicata:

1. [[Cabala]] ↔ [[Qabalah]]
   Cosine: 0.78, ambas na area Pesquisas. Verdict pendente.

2. [[Hermetismo - Overview]] ↔ [[Hermetismo Antigo]]
   Cosine: 0.72, ambas na area Pesquisas.

...
```

### Passo 6: Aplique os verdicts aprovados

`duplicates --interactive` pede verdict (`merge | keep_both | not_duplicate`). `propose` gera batches em `migration_plan`. Execucao real e pelo `obsidian-migrate apply`.

## Garantias duras

1. **Zero escrita silenciosa**: `--dry-run` e default em `propose` e `moc-audit`.
2. **Verdicts humanos**: `duplicate_candidates.verdict` so muda via aprovacao explicita.
3. **Preserva conteudo**: merge final concatena os dois, renomeia `.merged-TIMESTAMP`. Nada e perdido.
4. **Integra com migrate**: organizer propõe, migrate aplica — separacao clara.

## CLI: referencia rapida

- `organizer cluster [--latest] [--ai-label]` — HDBSCAN runner
- `organizer duplicates [--min-cos X] [--interactive]` — detecta + verdict
- `organizer moc-audit [--create-suggestions]` — clusters ≥ 10 sem MOC
- `organizer area-mismatch [--fix]` — area frontmatter ≠ pasta
- `organizer propose [--dry-run]` — agrega tudo em migration_plan
- `organizer report` — relatorio visual consolidado
