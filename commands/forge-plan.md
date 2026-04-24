---
description: Conduz entrevista dos 4 passos (3 Ps, precificacao, matematica, 7 acoes)
argument-hint: "[--status] [--new-cycle] [--vault /caminho]"
---

# forge-plan — obsidian-forge

Invocar a skill `obsidian-forge` com sub-comando `plan`:

1. Detectar vault.
2. Ler `04 - Negocio/_contexto.md` (se existir) pra personalizar as perguntas.
3. Conduzir os 4 passos no chat (pt-BR):
   - Passo 1+2: 3 Ps + Precificacao → `plan-save-plano`
   - Passo 3: Matematica do Resultado (com validacao aritmetica) → `plan-save-metas`
   - Passo 4: 7 Acoes Macro → `plan-save-acoes`
4. Ao final: sugerir `/obsidian-master-kit:forge-dash`.

Fluxo detalhado: `skills/obsidian-forge/SKILL.md`.

Comando base:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/obsidian-forge/scripts/forge.py plan $ARGUMENTS
```
