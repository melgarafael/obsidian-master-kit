---
description: Abre painel executor em localhost:4712 (Chrome/Arc/Edge/Brave)
argument-hint: "[--port PORT] [--no-browser] [--refresh] [--vault /caminho]"
---

# forge-dash — obsidian-forge

Invocar a skill `obsidian-forge` com sub-comando `dash`:

1. Validar que `_plano.md` e `_metas.md` existem.
2. Iniciar `python3 -m http.server` em `127.0.0.1:4712`.
3. Abrir browser em `http://127.0.0.1:4712/dashboard.html`.
4. User escolhe pasta do vault via File System Access API (primeira vez).

Requer Chromium (Chrome, Arc, Edge, Brave) pra edicao completa.

Comando:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/obsidian-forge/scripts/forge.py dash $ARGUMENTS
```
