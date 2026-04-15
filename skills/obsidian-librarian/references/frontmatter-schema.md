# Schema de Frontmatter — canônico

Fonte de verdade quando o `CLAUDE.md` do vault **não** redefine o schema. Se o vault
tem override no CLAUDE.md, o override vence.

## Campos obrigatórios

| Campo | Tipo | Valores válidos | Default se ausente |
|---|---|---|---|
| `created` | date (ISO) | `YYYY-MM-DD` | Data de hoje |
| `updated` | date (ISO) | `YYYY-MM-DD` | Data de hoje |
| `area` | string | `pessoal` \| `profissional` \| `pesquisa` \| `ai-memory` | **escalar** (não chutar) |
| `type` | string | `nota` \| `projeto` \| `pesquisa` \| `diario` \| `journaling` \| `contexto` \| `area` \| `referencia` \| `moc` \| `perfil` \| `indice` | **escalar** |
| `status` | string | `draft` \| `ativo` \| `arquivado` | `draft` |
| `tags` | list[string] | ver schema de tags | `[]` |

## Campos opcionais

| Campo | Tipo | Uso |
|---|---|---|
| `aliases` | list[string] | Nomes alternativos para resolução de wiki-link |
| `source` | string (URL) | Notas de pesquisa com fonte externa |
| `project` | string | Para notas em `03 - Memoria da IA/Projetos de Codigo/` |
| `confidence` | string | `alto` \| `medio` \| `baixo` — qualidade de uma pesquisa |
| `generated_by` | string | Nome da skill que criou a nota (p/ rastreabilidade) |

## Regras semânticas

### `area` vs pasta

A `area` no frontmatter deve bater com a pasta raiz:

| Pasta | `area:` |
|---|---|
| `00 - Pessoal/*` | `pessoal` |
| `01 - Profissional/*` | `profissional` |
| `02 - Pesquisas e Estudos/*` | `pesquisa` |
| `03 - Memoria da IA/*` | `ai-memory` |

Mismatch → reportar ao usuário (não mover automaticamente).

### `type` vs nome do arquivo

| Padrão de nome | `type:` esperado |
|---|---|
| `_MOC.md` | `moc` |
| `YYYY-MM-DD.md` (dentro de `Diario/`) | `diario` |
| `_INDEX.md` | `indice` |
| `Perfil.md` | `perfil` |

### `status: arquivado`

Se `status: arquivado` → a nota deveria estar em `Arquivadas/` da sua área (quando
existe). Mismatch → reportar ao usuário.

### Datas

- `created` nunca muda depois de gravado. Se uma skill tentar alterar, o librarian
  reverte.
- `updated` é atualizado automaticamente pelo librarian com base em mtime do
  arquivo (a cada sync).

## Normalizações automáticas (o librarian faz)

- Tags em `#pai/filho` no frontmatter → converter para `pai/filho` (sem `#`).
- Tags em CamelCase ou com espaços → lowercase com `-` (`#Minha Tag` → `minha-tag`).
- Aliases duplicados → dedupe.
- Datas em formato BR (`15/04/2026`) → converter para ISO (`2026-04-15`).

## O que o librarian **nunca** modifica

- `area` (decisão semântica — escalar se estiver errado)
- `type` (idem)
- `aliases` (humano escolhe)
- `tags` customizadas (só normaliza casing/formato, nunca remove)
- Corpo da nota (só adiciona linha em `## Relacionado` se estiver ausente e a nota
  não linka para MOC nenhum)

## Exemplo completo

```yaml
---
created: 2026-04-15
updated: 2026-04-15
area: pesquisa
type: pesquisa
status: ativo
tags: [pesquisa/ativa, ai-memory/documento]
aliases: [RAG, Retrieval Augmented Generation]
source: "https://arxiv.org/abs/2005.11401"
confidence: alto
generated_by: pesquisador-autonomo
---
```
