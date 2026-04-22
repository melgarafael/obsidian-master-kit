---
tipo: metas
protected: true
atualizado: {{atualizado}}
ciclo: {{ciclo}}
objetivo:
  titulo: "{{objetivo_titulo}}"
  valor_alvo: {{valor_alvo}}
  valor_atual: 0
  moeda: BRL
  prazo: {{prazo}}
funil:
  - etapa: clientes
    alvo: {{clientes_alvo}}
    atual: 0
    valor_unitario: {{valor_unitario}}
  - etapa: reunioes
    alvo: {{reunioes_alvo}}
    atual: 0
    taxa_conversao: {{reunioes_taxa}}
  - etapa: leads
    alvo: {{leads_alvo}}
    atual: 0
    taxa_conversao: {{leads_taxa}}
  - etapa: alcance
    alvo: {{alcance_alvo}}
    atual: 0
    fonte: {{alcance_fonte}}
---

# Metas — ciclo {{ciclo}}

## Matemática do resultado

- Objetivo: **{{objetivo_titulo}}** ({{valor_alvo}} BRL).
- Dividido por **R$ {{valor_unitario}}/cliente** = **{{clientes_alvo}} clientes**.
- Taxa reuniao→cliente **{{reunioes_taxa_pct}}%** = **{{reunioes_alvo}} reuniões**.
- Taxa lead→reuniao **{{leads_taxa_pct}}%** = **{{leads_alvo}} leads**.
- Alcance ({{alcance_fonte}}): **{{alcance_alvo}}**.
