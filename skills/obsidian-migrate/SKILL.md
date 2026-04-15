---
name: obsidian-migrate
description: Esta skill deve ser usada quando o usuario tem um vault Obsidian ja existente e quer adotar o padrao obsidian-master-kit SEM destruir a estrutura atual. Detecta o estado do vault, faz backup automatico, roda shadow-scan com embeddings, descobre areas reais via clustering (HDBSCAN), propoe mapping pasta->area adaptativo, executa migracao em lotes com approval humano obrigatorio, e oferece rollback. Adocao hibrida (Opcao C). Invocada via /obsidian-master-kit:migrate ou quando o usuario pede "quero usar o kit no meu vault que ja existe". Nunca executa automaticamente sem aprovacao explicita.
---

# obsidian-migrate

Adota o `obsidian-master-kit` em um vault Obsidian existente sem quebrar o que ja funciona.
Segue a **Opcao C (hibrida)**: descoberta de areas reais via clustering + approval humano
por lote + rollback disponivel + backup obrigatorio antes de qualquer movimento.

## Quando usar

- Usuario diz: "quero usar o kit no vault que ja tenho", "adota o obsidian-master-kit
  no meu Obsidian atual", "migra meu vault pro kit sem apagar nada"
- Usuario invoca `/obsidian-master-kit:migrate`
- Usuario aponta pra uma pasta que ja tem .md e quer estrutura do kit

## Quando **nao** usar

- Vault vazio — use `obsidian-init` (scaffold do zero)
- Vault ja migrado (tem `.obsidian-master/marker.json`) — use `obsidian-librarian`
- Usuario quer reorganizacao continua de vault ja migrado — use `obsidian-organizer`
  (Epic 04, futuro)

## Como usar — fluxo canonico

A skill tem 6 etapas, cada uma com aprovacao do usuario. Nunca pula etapa nem executa
sem confirmacao.

### Etapa 1 — Deteccao de estado

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/obsidian-migrate/scripts/migrate.py status --vault PATH
```

Retorna um de:

- `empty` — pasta nao tem .md. Sugere `/obsidian-master-kit:init`.
- `existing` — tem .md, sem marker. Pronto pra migrar.
- `already_migrated` — tem `.obsidian-master/marker.json`. Usa `obsidian-librarian`.

### Etapa 2 — Shadow scan + backup (Wave 2)

```bash
migrate.py shadow-scan --vault PATH
```

Cria backup (`vault.backup-YYYYMMDD-HHMMSS/`), inicializa DB, roda scanner sem mover
arquivos. Output: contagem por pasta + total + tamanho do DB.

### Etapa 3 — Clustering (Wave 3)

```bash
migrate.py cluster --vault PATH [--ai-label]
```

HDBSCAN sobre embeddings + TF-IDF pra label candidato. Opcional: `--ai-label` pede
label via Claude.

### Etapa 4 — Proposta de mapping (Wave 4)

```bash
migrate.py propose --vault PATH
```

Gera `.obsidian-master/migration-proposal.md`: tabela `pasta -> cluster dominante ->
area proposta`. Usuario revisa/edita.

### Etapa 5 — Plan + approval (Wave 5)

```bash
migrate.py plan --vault PATH
migrate.py approve --batch 1 [--batch all]
```

Gera registros em `migration_plan` em lotes de 20. Approval interativo por nota
(`y/n/a/s`).

### Etapa 6 — Execute + rollback (Wave 6)

```bash
migrate.py apply --batch 1 [--batch all]
migrate.py rollback --batch N   # se precisar reverter
```

Aplica os renames dos `approved`, refatora wikilinks que quebrariam, emite eventos,
e ao terminar cria `.obsidian-master/marker.json` com `migration_completed=true`.

## Garantias

- **Backup obrigatorio**: nunca move nada sem ter um `.backup-*` intacto
- **Approval por lote**: usuario aprova 20 notas por vez, nunca o vault inteiro de
  um golpe
- **Rollback disponivel**: cada batch aplicado pode ser revertido
- **Opcao C**: descoberta de areas respeita o que ja existe; o kit adapta ao vault,
  nao o vault ao kit
