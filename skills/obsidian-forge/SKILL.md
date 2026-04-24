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

## Fluxo da entrevista `forge-plan` (Claude Code conduz no chat)

### Passo 1+2 — 3 Ps + Precificacao

1. Ler `_contexto.md` (se existir) pra personalizar.
2. Perguntar: Produto (1 frase), Problema, Pessoa.
3. Perguntar prosa estendida de cada um.
4. Perguntar valor unitario + 4 bases de precificacao.
5. Montar JSON e chamar:

```bash
python3 forge.py plan-save-plano --respostas /tmp/respostas-plano.json
```

### Passo 3 — Matematica

1. Perguntar: objetivo (titulo, valor_alvo, prazo), taxas de conversao, fonte de alcance.
2. Chamar `math_funil.derivar_funil` via script para obter funil calculado.
3. Mostrar funil ao user; se aprovado → chamar:

```bash
python3 forge.py plan-save-metas --respostas /tmp/respostas-metas.json
```

Se `validar_funil` retornar erro, Claude re-pergunta o que nao bate.

### Passo 4 — Acoes Macro

```bash
python3 forge.py plan-save-acoes
```

Cria os 7 arquivos. Claude pode depois ler cada um e sugerir personalizacoes.

### Estado parcial

`04 - Negocio/.forge-state.json` guarda `passo_atual` e respostas. Ao
re-executar, Claude le esse arquivo pra saber onde parou e retomar.
