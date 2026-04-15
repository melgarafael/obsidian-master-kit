# Epic 02 — `obsidian-migrate` (Opção C híbrida)

**ID**: `EPIC02-MIGRATE`
**Goal**: Skill que adota o kit em vault existente sem destruir estrutura. Descobre áreas reais via HDBSCAN, propõe mapping folder→area, gera CLAUDE.md adaptativo, executa migração em lotes com approval humano. Backup obrigatório e rollback disponível.
**Referência técnica**: `docs/BRIEF-v1.md` §7.
**Deps**: Epic 01 completo.
**Bloqueia**: nenhum (4, 5, 6 podem começar em paralelo).
**Pontos totais**: 28.

## Stories

| ID | Title | Points | Deps | Area |
|---|---|---|---|---|
| S01 | Skill shell + SKILL.md + detecção de vault existente | 3 | EPIC01 | shell |
| S02 | Shadow scan + backup automático | 5 | S01 | scan |
| S03 | HDBSCAN + TF-IDF labeling + label via Claude | 5 | S02 | cluster |
| S04 | Proposta de mapping folder→area + CLAUDE.md adaptativo | 5 | S03 | mapping |
| S05 | `migration_plan` generation + approval CLI | 5 | S04 | approval |
| S06 | Execute migration em batch + rollback | 5 | S05 | execute |

---

### Story S01 — Skill shell + SKILL.md + detecção de vault existente

**Descrição**: Criar `skills/obsidian-migrate/` com SKILL.md pt-br, estrutura `scripts/migrate.py`, referenciar core/. Detecção: checa se o vault-alvo já tem `.obsidian-master/marker.json` (já migrado — abortar com sugestão de `/obsidian-master-kit:sync`), se tem conteúdo (migração real — procede), se está vazio (sugere `/obsidian-master-kit:init`).

**Critérios de aceitação**:
- SKILL.md tem frontmatter `name` + `description` que dispara quando usuário diz "quero usar o kit no meu vault que já existe" ou similar
- `migrate.py status --vault PATH` retorna estado: `empty | existing | already_migrated`
- Se `already_migrated`, exit 1 com mensagem clara
- Testes unitários dos 3 estados

---

### Story S02 — Shadow scan + backup automático

**Descrição**: Implementar `migrate.py shadow-scan --vault PATH`. Passos:

1. Checa disk free > 2× tamanho do vault (abortar se menos)
2. Cria backup: `cp -R <vault>/ <vault>.backup-YYYYMMDD-HHMMSS/`
3. Cria DB em `.obsidian-master/db.sqlite` via `core.db.connect`
4. Roda `core.scanner.scan` com embedder default — popula `notes` + `vec_notes` sem mover nada
5. Emite `events(scan_run, metadata={mode: 'shadow'})`
6. Relatório: contagem por pasta atual, total de notas, tamanho do DB

**Critérios de aceitação**:
- Backup criado com permissões idênticas ao original
- Abortar se `shutil.disk_usage().free < 2 * vault_size`
- `shadow-scan` rodado duas vezes não duplica backup
- Notas ficam no DB prontas pro próximo step (S03)
- Teste e2e com fixture: 50 notas backupeadas + DB populado em < 10s

---

### Story S03 — HDBSCAN + TF-IDF labeling + label via Claude

**Descrição**: Implementar `migrate.py cluster`. Roda HDBSCAN sobre `vec_notes` com:

- `min_cluster_size = max(5, n_notas // 200)`
- `min_samples = 3`
- `metric='euclidean'` sobre vetores normalizados

Para cada cluster não-noise:

- Top 8 tokens TF-IDF (stopwords pt-br + en, lib `sklearn.feature_extraction.text.TfidfVectorizer`)
- 3 notas centrais (menor distância ao centroide)
- Label candidato via LLM local ou heurística: junta top-3 tokens + título da nota mais central
- Opcionalmente: label via `Claude` se usuário passou `--ai-label` (invoca skill com prompt curto)

Grava em `clusters` + `cluster_notes`.

**Critérios de aceitação**:
- HDBSCAN sobre 2000 notas termina em < 15s
- Cluster labels são descritivos (não "cluster-1")
- Noise (ruído) é marcado com `cluster_id=NULL` e não quebra downstream
- Teste com fixture: vault com pastas claramente temáticas gera ≥3 clusters coerentes

---

### Story S04 — Proposta de mapping folder→area + CLAUDE.md adaptativo

**Descrição**: Implementar `migrate.py propose`. Lógica:

- Para cada pasta top-level do vault: conta cluster dominante entre suas notas
- Se cluster dominante ≥ 60% das notas da pasta → pasta vira **área** (registra em `areas` com `is_canonical=0`)
- Se espalhado (nenhum cluster > 60%) → marca como `needs_manual_decision` em relatório
- Oferece também as 4 áreas canônicas (pessoal, profissional, pesquisa, ai-memory) como opção
- CLAUDE.md adaptativo: template com `{{areas}}` renderiza o set descoberto. Rafael pode ter 4, 6 ou 8 áreas.

Output: arquivo `.obsidian-master/migration-proposal.md` com:

- Tabela `pasta → cluster dominante → área proposta`
- Lista de pastas ambíguas
- Preview do CLAUDE.md que seria gerado

**Critérios de aceitação**:
- `migrate.py propose` nunca escreve fora de `.obsidian-master/` nesta etapa
- Proposal.md lista TODAS as pastas (dominância clara ou não)
- CLAUDE.md preview tem seção `## Mapa de Áreas` com as áreas descobertas
- Usuário pode editar `migration-proposal.md` manualmente antes do próximo step

---

### Story S05 — `migration_plan` generation + approval CLI

**Descrição**: Implementar `migrate.py plan` e `migrate.py approve`. O `plan` lê a proposal (editada ou não) e gera registros em `migration_plan` em lotes (`batch_id`) de 20 notas. Cada registro tem:

- `note_path`, `current_location`, `proposed_location`, `reason`, `confidence`, `status=pending`

`approve --batch N` mostra diffs interativos no terminal (cada nota com current→proposed), aceita `y/n/a/s` (yes, no, all-yes, skip). Atualiza `status=approved|rejected`.

**Critérios de aceitação**:
- `plan` nunca move arquivos
- `approve --batch 1` é interativo e rejeitável por nota
- `approve --batch all` aprova tudo (com confirmação dupla)
- `migration_plan` consultável: `SELECT status, COUNT(*) FROM migration_plan GROUP BY status`
- Rejeição de uma nota preserva ela na pasta original permanentemente

---

### Story S06 — Execute migration em batch + rollback

**Descrição**: Implementar `migrate.py apply --batch N` e `migrate.py rollback --batch N`. `apply`:

1. Para cada registro `approved` do batch: `os.rename(current_location, proposed_location)`
2. Atualiza wikilinks quebrados em outras notas que apontavam pra essas (refactor automático)
3. Marca `applied_at=now()`, `status=applied`
4. Emite `events(note_moved, metadata={from, to})`
5. Regenera `_INDEX.md` via librarian

`rollback --batch N`:
- Para cada `applied` do batch: `os.rename(proposed_location, current_location)`
- Reverte wikilinks
- Marca `status=rolled_back`

Após o último batch aplicado com sucesso: cria `.obsidian-master/marker.json` com `kit_version` e `migration_completed=true`.

**Critérios de aceitação**:
- `apply` respeita ordem dos batches (não pula)
- Wikilinks quebrados por rename são detectados e atualizados (testado com fixture)
- `rollback` restaura estado exato do backup (checksum de estrutura)
- Marker.json só é criado depois de todos os batches aprovados serem aplicados
- E2E: scaffold fake vault → migrate → checa que todas notas aprovadas estão nas novas pastas e os links funcionam

---

## Architecture contracts (expostos)

- `.obsidian-master/marker.json` indica vault migrado
- Tabela `areas` populada com áreas descobertas (custom + canônicas opcionais)
- Tabela `migration_plan` com histórico auditável
- `events(note_moved)` registrados pra análise histórica do pulse futuramente
