---
name: obsidian-expand
description: Esta skill deve ser usada quando o usuario quer gerar notas-ponte no vault a partir de conteudo que JA EXISTE nele. Acionada por frases como "expande meu vault", "cria as notas que faltam entre X e Y", "preenche gaps do vault", "expande esse MOC", "ha pontes faltando aqui?", ou invoca `/obsidian-master-kit:expand`. Detecta lacunas semanticas (pares de notas proximas sem link), MOCs incompletos (MOC com poucos out-links mas cluster grande ao redor), e conceitos subjacentes ausentes (grupo de notas mencionando algo mas sem nota dedicada). Gera rascunhos `.md` marcados `status: draft, generated_by: obsidian-expand`, SEMPRE citando as notas-fonte do vault como wikilinks. NAO inventa fatos do mundo externo — se o vault nao tem informacao suficiente, a nota gerada diz isso explicitamente.
---

# obsidian-expand

Gerador de **notas-ponte** usando APENAS conteudo existente do vault como
fonte. Preenche gaps semanticos, expande MOCs rasos, propoe notas de conceito
que estao implicitos em varias notas mas nunca foram escritos.

## Quando usar

- Usuario diz "expande meu vault", "cria as notas que faltam", "preenche
  gaps", "ha pontes entre essas duas notas?", "esse MOC ta ralo".
- Usuario invoca `/obsidian-master-kit:expand`.
- Apos rodar `obsidian-organizer` e receber sugestoes `bridge` ou
  `moc_missing` pendentes em `suggestions_cache` — `obsidian-expand` e quem
  gera o conteudo final dessas sugestoes.

## Quando **nao** usar

- Pra escrever nota nova do zero sobre topico que o vault nao cobre — isso
  e `obsidian-init` ou o usuario escrevendo manualmente.
- Pra resumir uma nota so (`generate`/`summarize` sao skills diferentes).
- Em vault pequeno (< 50 notas) — gaps reais precisam de massa critica.

## Fluxo canonico

### Passo 1: Detecte o vault

Walk ancestrais do cwd procurando `.obsidian-master/marker.json`. Se nao
achar, aborte com mensagem clara pedindo `--vault PATH`.

### Passo 2: Escolha o sub-comando apropriado

Quatro entradas reflitindo a intencao do usuario:

| Intencao do usuario | Sub-comando |
|---|---|
| "Ha pontes faltando?" / "Conecte as notas soltas" | `bridges` |
| "Expande esse MOC" / "O MOC X ta ralo" | `moc --moc-path PATH` |
| "Preenche gaps na area Y" | `gaps --area AREA` |
| "Expande a partir dessa nota" | `from --note PATH` |

### Passo 3: Invoque o script

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/obsidian-expand/scripts/expand.py \
  <sub-comando> [--vault PATH] [--dry-run] [opcoes do sub-comando]
```

Sempre comece com `--dry-run` pra mostrar as propostas ao usuario ANTES de
escrever arquivos. Nada e escrito sem aprovacao explicita.

### Passo 4: Apresente as propostas ao usuario

O script imprime candidatas em JSON. Apresente em pt-br humano, com o
`reasoning` embaixo de cada uma. Exemplo:

```
3 notas-ponte sugeridas:

1. Entre [[Tabua de Esmeralda]] e [[Principios Hermeticos]]
   Motivo: similaridade 0.41, sem link direto, 18 notas de Pesquisas
   linkam uma delas mas nao a outra.

2. MOC de Alquimia ta com 4 out-links mas cluster tem 27 notas
   Motivo: 23 notas orfas do mesmo cluster nao estao no MOC.
```

### Passo 5: Gere as notas aprovadas

Pra cada sugestao que o usuario confirmar, rode o script sem `--dry-run`
(ou com `--suggestion-id N` pra gerar uma especifica). A nota `.md` sai
com:

- Frontmatter completo (`status: draft, generated_by: obsidian-expand,
  source: <suggestion_id>`, area inferida da pasta da primeira fonte)
- Wikilinks explicitos pras notas-fonte no corpo
- Mensagem "nao ha informacao suficiente no vault" se o LLM nao conseguir
  preencher sem inventar

### Passo 6: Dispare o librarian

Toda nota gerada precisa ser indexada:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/obsidian-librarian/scripts/update_index.py \
  --vault <vault-root>
```

Isso garante que a nova nota entra em `notes`, `vec_notes`, `_INDEX.md`.

## Garantias duras

1. **Zero invencao**: o prompt mandado ao LLM instrui explicitamente a
   usar APENAS as notas-fonte anexadas. Se informacao falta, diz isso.
2. **Wikilinks obrigatorios**: toda nota gerada cita as fontes como
   `[[nota-fonte]]` no corpo.
3. **`status: draft`**: Rafael decide se promove pra `ativo`.
4. **Sem escrita silenciosa**: `--dry-run` default em apresentacoes, grava
   so com flag explicita.

## CLI: referencia rapida

- `expand bridges [--topic TOPIC] [--min-cos X] [--dry-run]` — pontes
  entre notas proximas sem link.
- `expand moc --moc-path PATH [--dry-run]` — expande um MOC especifico.
- `expand gaps [--area AREA] [--dry-run]` — gaps semanticos numa area.
- `expand from --note PATH [--k N] [--dry-run]` — expansao a partir de
  uma nota seed (top-K vizinhos + sugere notas-ponte).
- `expand generate --suggestion-id N` — materializa uma sugestao do cache
  em `.md` real (invoca o LLM).

Todos os sub-comandos aceitam `--vault PATH` pra rodar fora do vault root.
