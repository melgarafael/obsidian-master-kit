---
tipo: plano
protected: true
atualizado: {{atualizado}}
ciclo: {{ciclo}}
produto: "{{produto}}"
problema: "{{problema}}"
pessoa: "{{pessoa}}"
precificacao:
  valor_unitario: {{valor_unitario}}
  moeda: BRL
  base:
    resultado_potencial: "{{resultado_potencial}}"
    tempo_economizado: "{{tempo_economizado}}"
    esforco_reduzido: "{{esforco_reduzido}}"
    producao_aumentada: "{{producao_aumentada}}"
status: ativo
---

# Plano — ciclo {{ciclo}}

## 3 Ps

### Produto
{{produto_prosa}}

### Problema
{{problema_prosa}}

### Pessoa (ICP)
{{pessoa_prosa}}

## Precificação — raciocínio

Preço unitário: **R$ {{valor_unitario}}**.

- Resultado potencial: {{resultado_potencial}}
- Tempo economizado: {{tempo_economizado}}
- Esforço reduzido: {{esforco_reduzido}}
- Produção aumentada: {{producao_aumentada}}
