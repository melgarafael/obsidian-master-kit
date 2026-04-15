---
description: Forca sincronizacao do vault Obsidian atual (invoca obsidian-librarian). Valida frontmatter, normaliza tags, atualiza _INDEX.md, detecta orfas.
argument-hint: "[--vault /caminho/para/vault]"
---

# Sync — obsidian-master-kit

Invoque a skill `obsidian-librarian` para sincronizar o vault manualmente. Util
depois de:

- Editar varias notas a mao e querer o `_INDEX.md` atualizado
- Importar notas de fora
- Suspeitar que alguma skill terceira escreveu sem respeitar o schema

A skill:

1. Detecta o vault-master a partir do diretorio atual (walk-up procurando
   `.obsidian-master/marker.json`). Se `$ARGUMENTS` contem `--vault <path>`, usa
   esse caminho direto.
2. Le `<vault>/CLAUDE.md` como doutrina viva.
3. Invoca `scripts/update_index.py --vault <vault>`.
4. Trata issues reportadas (orfas, area mismatch, etc.) seguindo
   `references/linking-rules.md` e `references/frontmatter-schema.md`.
5. Reporta 1 bloco conciso com o que foi feito.

Siga exatamente `${CLAUDE_PLUGIN_ROOT}/skills/obsidian-librarian/SKILL.md`.
