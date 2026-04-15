# Changelog

Todas as mudanças relevantes deste projeto são documentadas aqui.

O formato segue [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/)
e o versionamento segue [SemVer](https://semver.org/lang/pt-BR/).

## [Unreleased]

## [0.1.0-mvp] — 2026-04-15

### Adicionado
- Skill `obsidian-init` para gerar um vault Obsidian do zero com estrutura opinionada
  (4 áreas: Pessoal, Profissional, Pesquisas e Estudos, Memória da IA) via entrevista pt-br.
- Skill `obsidian-librarian` para curadoria contínua: valida frontmatter, normaliza tags,
  mantém o `_INDEX.md` vivo e garante links para MOCs das áreas.
- Hook `PostToolUse` que detecta escritas dentro de um vault-master e instrui o Claude
  a invocar o bibliotecário antes de seguir adiante.
- Slash commands `/obsidian-master-kit:init` e `/obsidian-master-kit:sync`.
- Roadmap com as skills futuras previstas (daily-note, moc-builder, search, linker,
  archiver, graph-audit, export).
