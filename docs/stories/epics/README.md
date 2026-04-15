# Epics — obsidian-master-kit v1

Epics prontos pra serem executados via `@epic-executor` do Claude Code. Cada arquivo é self-contained com stories, deps, pontos e critérios de aceitação.

## Ordem de execução

Epic 01 é pré-requisito absoluto. Epics 02-05 podem rodar em paralelo depois. Epic 06 depende de todos.

```
                  ┌─ 01 (core/) ─┐
                  │              │
        ┌─────────┼──────┬───────┼───────────┐
        ▼         ▼      ▼       ▼           │
    02 migrate  03 lib  04 org  05 expand    │
        │         │      │       │           │
        └─────────┴──────┴───────┘           │
                         │                    │
                         ▼                    │
                     06 pulse ◄───────────────┘
```

## Sumário

| Epic | Skill | Pontos | Stories | Deps |
|---|---|---|---|---|
| [01](01-core-foundation.md) | `core/` (infra) | 34 | 7 | — |
| [02](02-obsidian-migrate.md) | `obsidian-migrate` | 28 | 6 | 01 |
| [03](03-librarian-extension.md) | librarian v1.0 | 13 | 5 | 01 |
| [04](04-obsidian-organizer.md) | `obsidian-organizer` | 21 | 6 | 01 |
| [05](05-obsidian-expand.md) | `obsidian-expand` | 18 | 5 | 01, (04 ideal) |
| [06](06-obsidian-pulse.md) | `obsidian-pulse` | 42 | 10 | 01-05 |

**Total**: 156 pontos, 39 stories, 6 epics.

## Brief consolidado

Toda a especificação técnica está em [`../BRIEF-v1.md`](../BRIEF-v1.md). Cada epic referencia seções específicas do brief.

## Como executar

Com o kit instalado e o repositório em estado limpo:

```
@epic-executor 01-core-foundation.md
```

O executor lê o épico, extrai stories na ordem de deps, e executa wave por wave com build/QA/regression entre cada.

## Contratos arquiteturais

Cada epic expõe "architecture contracts" na seção final — interfaces, módulos, tabelas, endpoints que epics posteriores podem depender. Ver cada arquivo individual pra detalhes.
