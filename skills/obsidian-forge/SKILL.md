---
name: obsidian-forge
description: Use quando o usuario diz "meu plano de negocio", "matematica do resultado", "abre o painel do negocio", "scanear projetos", "registrar progresso", ou invoca `/obsidian-master-kit:forge-scan|plan|dash`. Conduz entrevista dos 4 passos (3 Ps, precificacao, matematica, 7 acoes macro) conforme metodologia da aula "IA como ferramenta"; mapeia projetos ativos do PC como notas atomicas; sobe dashboard HTML estatico em localhost:4712 com File System Access API para cliques executores. 100% local, zero cloud, zero daemon.
---

# obsidian-forge

Skill de execucao de negocio. Transforma o vault num sistema operacional
pessoal pra empreender usando IA como ferramenta.

## Quando usar

- Usuario digita `/obsidian-master-kit:forge-plan`, `forge-scan` ou `forge-dash`.
- Usuario fala "plano de negocio", "matematica do resultado", "abre painel".
- Usuario quer registrar progresso nas metas.

## Quando **nao** usar

- Vault sem `obsidian-init` rodado (requer estrutura base).

## Fluxo canonico

### Passo 1: Detecte o vault

Walk ancestrais procurando `.obsidian-master/marker.json`. Senao,
pede `--vault PATH`.

### Passo 2: Escolha o sub-comando

| Intencao | Sub-comando |
|---|---|
| "Varrer projetos no PC" | `scan` |
| "Fazer plano de negocio" | `plan` |
| "Abrir painel" | `dash` |

### Passo 3: Invoque

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/obsidian-forge/scripts/forge.py \
  <sub-comando> [--vault PATH] [flags]
```

## Invariantes duros

1. **Territorialidade**: so escreve em `04 - Negocio/`. Nunca em outras areas.
2. **Zero aritmetica no LLM**: contas em Python/JS, validadas por teste.
3. **Zero daemon**: so CLI on-demand + hook `SessionStart` opt-in.
4. **Localhost-only**: `http.server` em `127.0.0.1`.
5. **Zero LLM no dashboard runtime**: "proximo passo" e deterministico.
6. **pt-BR hardcoded** em templates, entrevista, dashboard.
7. **Metodologia hardcoded** (4 passos + 7 acoes da aula).
8. **Dashboard requer Chromium** pra edicao. Outros browsers: read-only.
9. **Dashboard usa DOM APIs seguras**: sem `.innerHTML` com conteudo de
   arquivo; tudo via `createElement` + `textContent` + `replaceChildren`.
