---
description: Detecta projetos ativos no PC e gera notas atomicas de contexto no vault
argument-hint: "[--init] [--vault /caminho] [--add /nova/pasta]"
---

# forge-scan — obsidian-forge

Invocar a skill `obsidian-forge` com sub-comando `scan`:

1. Detectar vault via `.obsidian-master/marker.json` (walk-up).
2. Se `_config-scan.md` ausente em `04 - Negocio/` → rodar entrevista `--init`.
3. Rodar scan, gerar notas atomicas em `04 - Negocio/contexto/<slug>.md`, atualizar `_contexto.md`.
4. Invocar `obsidian-librarian` ao final pra atualizar `_INDEX.md`.

Comando:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/obsidian-forge/scripts/forge.py scan $ARGUMENTS
```
