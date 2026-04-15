---
created: 2026-01-05
updated: 2026-04-15
area: profissional
type: projeto
status: ativo
project: obsidian-master-kit
tags: [projeto, obsidian, tooling, open-source]
---

# Projeto Obsidian Master Kit

Kit de skills que transforma uma pasta vazia num vault Obsidian profissional.
Plugin Claude Code, publicado como marketplace oficial.

## Estado (abril 2026)

Epic 01 (core foundation) em fase final. 7 waves executadas:

1. DB + migrations (sqlite + sqlite-vec)
2. Parser de markdown (frontmatter, links, tags)
3. Scanner incremental com delta de 3 niveis
4. Embeddings via Model2Vec (256 dim)
5. Graph metrics (pagerank, betweenness, MOCs)
6. CLI + slash commands
7. Fixture vault + integration tests (atual)

## Proximos epics

- Epic 02: migrate skill (reestruturar vault existente)
- Epic 03: librarian Python (substituir o bash atual)
- Epic 04: sync mode incremental (hook-driven)

Contratos publicos dessa foundation: `connect`, `scan`, `parse_markdown`,
`Embedder`, `update_graph_metrics`. Epic 02+ importa desses.
