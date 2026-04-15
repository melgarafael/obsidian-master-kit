---
description: Scaffolda um vault Obsidian do zero seguindo o padrao obsidian-master-kit (4 areas, CLAUDE.md doutrina, _INDEX.md vivo, MOCs, templates). Conduz entrevista curta em pt-br.
argument-hint: "[--path /caminho/para/vault]"
---

# Init — obsidian-master-kit

Invoque a skill `obsidian-init` para scaffoldar um novo vault Obsidian. A skill:

1. Determina o diretorio-alvo (default: pwd, ou `$ARGUMENTS` se passado).
2. Verifica se a pasta e segura para scaffold (nao e `$HOME`, nao tem `.git` alheio,
   nao ja e um vault-master).
3. Conduz uma entrevista curta em pt-br (7 perguntas: nome, profissao, areas,
   projetos, idioma, fuso, tom).
4. Invoca `scripts/scaffold_vault.py` com as respostas.
5. Reporta os proximos passos (abrir no Obsidian, revisar Perfil.md, etc.).

Siga exatamente o que esta em `${CLAUDE_PLUGIN_ROOT}/skills/obsidian-init/SKILL.md`.
Use `${CLAUDE_PLUGIN_ROOT}/skills/obsidian-init/references/interview-script.md`
como roteiro da entrevista.

Se `$ARGUMENTS` comecar com `--path`, passe o caminho para a skill sem re-perguntar
o diretorio.
