---
created: {{DATE_TODAY}}
updated: {{DATE_TODAY}}
area: ai-memory
type: moc
status: ativo
tags: [ai-memory/projeto]
aliases: [MOC Memoria da IA, Memória da IA]
---

# MOC — Memória da IA

Contexto persistente para projetos de código. Esta é a área que a IA consulta quando
você está desenvolvendo software. Documentação de decisões, referências de libs,
contexto acumulado por projeto.

## Estrutura

- **Projetos de Codigo/** — uma pasta por projeto, com docs, decisões, estado atual
- **Bibliotecas/** — referências de libs/frameworks que você usa (snippets, padrões)
- **Referencias/** — material técnico genérico (padrões de design, links úteis)

## Como usar

Quando começar um projeto de código novo:

1. Crie `Projetos de Codigo/<Nome do Projeto>/` (pasta)
2. Duplique [[_templates/Contexto de Projeto|Contexto de Projeto]] para
   `Projetos de Codigo/<Nome do Projeto>/_Contexto.md`
3. À medida que for decidindo coisas, acrescente notas na pasta do projeto.
4. Aponte o Claude Code (ou outra IA) para ler esta pasta antes de codar.

## Projetos de código ativos

_(Aparece conforme você cria. O bibliotecário mantém.)_

## Relacionado

- [[../_INDEX|Índice geral]]
- [[../CLAUDE|Doutrina]]
- [[../01 - Profissional/_MOC|MOC Profissional]]
