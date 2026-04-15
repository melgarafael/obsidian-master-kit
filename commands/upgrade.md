---
description: Migra um vault obsidian-master-kit de v0.1.1 pra v1.0 (cria SQLite, popula via scan completo, emite eventos iniciais, bumpa marker). Idempotente.
argument-hint: "[--vault /caminho/para/vault]"
---

# Upgrade — obsidian-master-kit

Migra um vault instalado com kit **v0.1.1** pra **v1.0**. O que muda na v1.0:

- DB SQLite em `.obsidian-master/db.sqlite` (fonte de verdade pra `_INDEX.md`,
  metricas, e queries do librarian).
- Tabela `events` com historia de scans, criacoes, updates e links.
- `marker.json` bumpado com `kit_version=1.0` + `schema_version=1` +
  `upgraded_at`.

O que **NAO** muda:

- `CLAUDE.md` do usuario (preservado byte-identico — e onde mora sua doutrina).
- Conteudo das notas `.md` (autofix fica pro proximo `/sync`).
- Campos antigos do `marker.json` (so adiciona, nao deleta).

## Como rodar

Dentro do vault (auto-discovery):

```
/obsidian-master-kit:upgrade
```

Ou com path explicito:

```
/obsidian-master-kit:upgrade --vault /caminho/para/vault
```

## O que esperar

Na primeira execucao (vault v0.1.1):

1. Detecta ausencia de `db.sqlite`.
2. Cria o DB via `core.db.connect` (aplica migrations).
3. Roda `core.scanner.scan` completo (popula `notes`, `links`, `areas`).
4. Emite eventos iniciais: `scan_run(triggered_by=init)` + 1 `note_created`
   por nota + 1 `link_added` por edge detectado.
5. Atualiza `marker.json`.
6. Imprime resumo JSON em stdout.

Na segunda execucao (ja v1.0): detecta estado, faz `ensure_schema` (no-op),
re-scaneia (upsert por `body_hash` — nao duplica notas), e reporta
`upgraded: false, reason: "already_v1"` **sem duplicar eventos**.

## Invocacao direta do script

Se quiser pular a slash-command:

```
obsidian-master upgrade --vault /caminho/vault
```

Ou via Python direto:

```
python skills/obsidian-librarian/scripts/upgrade.py --vault /caminho/vault
```
