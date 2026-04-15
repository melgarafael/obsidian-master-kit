# CLAUDE.md — Doutrina deste Vault

> Arquivo lido por qualquer skill de IA antes de escrever aqui dentro. Regras definidas
> aqui são soberanas: se uma skill precisar violar algo, ela **pergunta primeiro** e
> **nunca edita este arquivo** — só o humano edita.

---

## Sobre o Owner

- **Nome**: {{OWNER_NAME}}
- **Função / profissão**: {{OWNER_PROFESSION}}
- **Fuso horário**: {{OWNER_TIMEZONE}}
- **Idioma preferido para journaling**: {{OWNER_LANG}}
- **Tom da escrita**: {{OWNER_TONE}}

Este vault é o **segundo cérebro** de {{OWNER_NAME}} — repositório pessoal de notas,
memória profissional, pesquisa viva, e contexto persistente para projetos de código.

## Áreas principais de trabalho

{{OWNER_AREAS_BULLETS}}

## Projetos ativos

{{OWNER_PROJECTS_BULLETS}}

---

## Doutrina para skills de IA

Regras não-negociáveis para qualquer skill que escrever neste vault:

1. **Leia este arquivo inteiro antes de escrever a primeira nota.** É seu contrato.
2. **Nunca edite este arquivo.** Se precisar alterar regra, pergunte.
3. **Nunca delete conteúdo humano.** Mova para `Arquivadas/` da área com justificativa.
4. **Toda nota tem frontmatter.** Campos obrigatórios: `created`, `updated`, `area`,
   `type`, `status`, `tags`. Veja seção *Schema de Frontmatter* abaixo.
5. **Toda nota tem pelo menos 1 wiki-link** — normalmente para o MOC da sua área.
6. **Nada fica fora das 4 áreas.** Se não couber em nenhuma, é sinal pra abrir
   sub-pasta ou pedir ao owner um MOC novo.
7. **Nome de arquivo é o título humano-legível.** Sem `slugification`, sem `kebab-case`.
   Exemplo bom: `Arquitetura do Sistema de Pagamento.md`. Exemplo ruim:
   `arquitetura-sistema-pagamento.md`.
8. **Invoque o `obsidian-librarian` ao final da sua escrita** (ou confie no hook
   `PostToolUse` que o invoca). O bibliotecário valida frontmatter, normaliza tags e
   atualiza o `_INDEX.md`.

---

## Mapa de pastas — o que vive onde

```
00 - Pessoal/              Quem eu sou. Journaling, diario, perfil.
├── Perfil.md              Bio viva. Humano edita. IA só lê.
├── Journaling/            Reflexoes livres, pensamento corrente.
├── Diario/                Registro factual do dia (YYYY-MM-DD.md).
└── _templates/

01 - Profissional/         Meu trabalho. Projetos, areas, materiais.
├── Projetos/              Um arquivo por projeto ativo.
├── Areas/                 Areas de responsabilidade continua.
└── _templates/

02 - Pesquisas e Estudos/  Onde IA despeja pesquisa. Onde eu aprendo.
├── Ativas/                Pesquisa em andamento.
├── Arquivadas/            Pesquisa concluida ou abandonada.
└── _templates/

03 - Memoria da IA/        Contexto persistente para projetos de codigo.
├── Projetos de Codigo/    Um sub-folder por projeto (docs, decisoes, notas).
├── Bibliotecas/           Referencias de libs/frameworks que eu uso.
├── Referencias/           Snippets, padroes, links uteis.
└── _templates/
```

Regra de ouro: **se a nota fala sobre você, vai pra 00. Sobre seu trabalho, 01.
Sobre o mundo/assunto que você estuda, 02. Contexto pra IA construir software, 03.**

---

## Convenções

### Linking

- **Todo conceito mencionado que pode virar nota própria recebe wiki-link.** Ex:
  "Decidi usar [[PostgreSQL]] porque [[Domain-Driven Design]] favorece..."
- **MOCs são o topo da hierarquia.** Toda nota de uma área deve linkar para o `_MOC.md`
  dessa área no mínimo uma vez (normalmente no footer em `## Relacionado`).
- **Backlinks são automáticos no Obsidian.** Não faça listas manuais de "notas
  relacionadas" — o painel de backlinks do Obsidian já mostra.
- **Aliases no frontmatter** quando o título tem variações comuns (ex: título é
  "Teoria Geral dos Sistemas", alias `["TGS", "Systems Theory"]`).

### Tags

Tags complementam pastas — pastas respondem "o que é", tags respondem "qual estado/qualidade".

Tags seguem hierarquia (`#pai/filho`):

- `#pessoal/{journaling, diario, perfil}`
- `#profissional/{projeto, area, material}`
- `#pesquisa/{ativa, arquivada, referencia}`
- `#ai-memory/{projeto, biblioteca, documento}`
- `#status/{draft, ativo, arquivado}`

### Datas

- Datas sempre ISO `YYYY-MM-DD`.
- `created` nunca muda depois de escrito.
- `updated` é atualizado pelo bibliotecário toda vez que a nota muda.

### Nomes

- Arquivos e pastas **sem acentos** (compatibilidade cross-plataforma).
- Títulos e conteúdo **com acentos normais**.
- Espaços em nome de arquivo são OK — o Obsidian trata bem.

---

## Schema de Frontmatter (obrigatório)

```yaml
---
created: 2026-04-15          # ISO date, nunca muda apos criacao
updated: 2026-04-15          # ISO date, librarian atualiza
area: pessoal                # pessoal | profissional | pesquisa | ai-memory
type: nota                   # nota | projeto | pesquisa | diario | journaling | contexto | area | referencia
status: draft                # draft | ativo | arquivado
tags: []                     # ver schema acima
aliases: []                  # opcional
---
```

Campos opcionais úteis:

- `source: <url>` — pra notas de pesquisa com fonte externa
- `project: <nome>` — pra notas em `03 - Memoria da IA/Projetos de Codigo/`
- `confidence: alto | medio | baixo` — pra pesquisa com qualidade variável

---

## Schema de Tags (canônico)

| Tag raiz | Uso |
|---|---|
| `#pessoal/journaling` | Reflexão pessoal livre |
| `#pessoal/diario` | Registro diário factual |
| `#pessoal/perfil` | Informação biográfica |
| `#profissional/projeto` | Projeto ativo com começo/fim |
| `#profissional/area` | Área de responsabilidade contínua |
| `#profissional/material` | Material de trabalho (docs, planilhas) |
| `#pesquisa/ativa` | Pesquisa em andamento |
| `#pesquisa/arquivada` | Pesquisa concluída ou abandonada |
| `#pesquisa/referencia` | Nota de referência pontual |
| `#ai-memory/projeto` | Contexto de projeto de código |
| `#ai-memory/biblioteca` | Snippet ou padrão de uma lib |
| `#ai-memory/documento` | Referência acumulada |
| `#status/draft` | Ainda não tem forma |
| `#status/ativo` | Útil, em uso |
| `#status/arquivado` | Sem uso ativo |

**Tag nunca duplica pasta.** Se a nota está em `02 - Pesquisas e Estudos/Ativas/`,
a tag `#pesquisa/ativa` é redundante. Use só quando agrega informação nova (ex: a nota
mora na pasta de projeto mas tem caráter de referência → `#pesquisa/referencia`).

---

## Como o `_INDEX.md` funciona

Na raiz deste vault existe um `_INDEX.md`. É **gerado pelo bibliotecário** — não edite
à mão. Ele é reescrito toda vez que uma skill invoca `obsidian-librarian` (ou toda vez
que o hook `PostToolUse` dispara após uma escrita no vault).

O `_INDEX.md` contém: contagem por área, últimas 10 notas adicionadas, lista de MOCs
ativos, notas órfãs (sem links).

Para forçar uma atualização manual: `/obsidian-master-kit:sync`.
