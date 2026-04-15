---
created: 2025-05-20
updated: 2026-02-01
area: profissional
type: projeto
status: ativo
project: tomik-crm
tags: [projeto, crm, saas]
---

# Projeto Tomik CRM

CRM vertical com foco em pequenas operacoes de servico. Principal diferencial:
automacao assistida por IA dentro do fluxo do vendedor, nao em painel separado.

## Decisoes de arquitetura

- Postgres como fonte unica de verdade
- Supabase pra auth + realtime
- Frontend NextJS com componentes derivados do design system interno
- Agents customizados via Agent Runtime Data Split

## Status

Em producao com 4 clientes. Revenue mensal estavel. Principal dor atual
e governanca de dados sensiveis — ver nota relacionada:
[[governanca-dados-sensiveis]] (esta nota ainda nao existe, criar).

#projeto #crm
