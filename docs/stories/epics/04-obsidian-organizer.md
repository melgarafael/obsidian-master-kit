# Epic 04 — `obsidian-organizer`

**ID**: `EPIC04-ORGANIZER`
**Goal**: Skill que varre o vault inteiro com IA. Detecta clusters semânticos órfãos, duplicatas de conceito (cos ≥ 0.92), MOCs faltando (clusters ≥ 10 sem MOC próprio), notas mal-alocadas (area frontmatter ≠ pasta). Propõe consolidações via `migration_plan`. Humano aprova.
**Referência técnica**: `docs/BRIEF-v1.md` §3.3, §6.
**Deps**: Epic 01 completo. Pode rodar antes ou depois de Epic 02 (não bloqueia).
**Pontos totais**: 21.

## Stories

| ID | Title | Points | Deps | Area |
|---|---|---|---|---|
| S01 | Skill shell + SKILL.md + CLI | 3 | EPIC01 | shell |
| S02 | HDBSCAN runner + cluster labeling | 5 | EPIC01-S04 | cluster |
| S03 | Duplicate detection (cos ≥ 0.92) | 3 | EPIC01-S04 | dedup |
| S04 | MOC detection (clusters ≥ 10 sem MOC) | 3 | S02 | moc |
| S05 | Area mismatch detection | 2 | EPIC01-S01 | mismatch |
| S06 | Proposta de moves + merge via `migration_plan` | 5 | S02-S05 | propose |

---

### Story S01 — Skill shell + SKILL.md + CLI

**Descrição**: Criar `skills/obsidian-organizer/SKILL.md`. Descrição aciona em "organiza meu vault", "vê o que está bagunçado", "sugere consolidações". CLI:

- `organizer cluster` — roda clustering
- `organizer duplicates` — detecta duplicatas
- `organizer moc-audit` — checa MOCs faltando
- `organizer propose` — gera migration_plan com tudo
- `organizer report` — imprime relatório visual

**Critérios de aceitação**:
- SKILL.md descrição clara, pt-br, com exemplos de uso
- `organizer --help` mostra todos os subcommands em pt-br
- Cada subcommand tem seu próprio `--help` com exemplo

---

### Story S02 — HDBSCAN runner + cluster labeling

**Descrição**: Roda HDBSCAN sobre `vec_notes` (reusa código do Epic 02 S03 se feito, ou implementa). Labela cada cluster com:

1. Top 8 tokens TF-IDF
2. 3 notas centrais
3. Label canônico via heurística (top tokens + título da nota central)

Grava em `clusters` com `run_id=uuid4()` e timestamp.

**Critérios de aceitação**:
- Run cria novo `run_id`, preservando runs antigos
- `organizer cluster --latest` mostra clusters do último run
- Cluster vazio (todo noise) gera warning útil, não crash

---

### Story S03 — Duplicate detection (cos ≥ 0.92)

**Descrição**: Detecta pares de notas com cosine ≥ 0.92 que são candidatos a duplicata de conceito (ex: "Cabala" e "Qabalah"). Query via `sqlite-vec MATCH` com threshold. Filtra pares triviais (uma é sub-página/MOC da outra, mesmo título+sufixo numérico).

Grava em `duplicate_candidates(note_a_id, note_b_id, cosine_similarity, detected_at, verdict=NULL)`.

**Critérios de aceitação**:
- `organizer duplicates` gera lista com pares e cosine
- CLI interativo oferece verdict: `merge | keep_both | not_duplicate`
- Verdict grava em DB; não executa merge automaticamente
- Não lista pares já julgados nas últimas 30 runs

---

### Story S04 — MOC detection (clusters ≥ 10 sem MOC)

**Descrição**: Para cada cluster do último run com ≥ 10 notas, checa se alguma é `_MOC.md` da área do cluster. Se não:

- Cria entry em `suggestions_cache(kind='moc_missing', target_note_ids=JSON, content='...', reasoning='Cluster "X" com N notas não tem MOC')`
- Opcionalmente: `organizer moc-audit --create-suggestions` gera stub de MOC (arquivo `.md` draft em pasta apropriada) com os wikilinks pras notas do cluster

**Critérios de aceitação**:
- Suggestion gerada pra cada cluster sem MOC
- Reasoning é humano-legível ("Cluster 'Hermetismo & Alquimia' tem 14 notas mas nenhum `_MOC.md`")
- `--create-suggestions` gera `.md` draft com frontmatter `status: draft` e `generated_by: obsidian-organizer`

---

### Story S05 — Area mismatch detection

**Descrição**: Detecta notas com `frontmatter.area` inconsistente com a pasta onde moram. Ex: nota em `01 - Profissional/` com `area: pessoal`. Lista sem aplicar mudança — usuário decide.

Grava em `suggestions_cache(kind='area_mismatch', target_note_ids=[note_id], reasoning='area declarada vs pasta diverge')`.

**Critérios de aceitação**:
- Detecta mismatch corretamente em fixture
- Não flagga casos legítimos (ex: nota em pasta raiz sem area específica)
- `--fix` oferece aplicação interativa (renomeia pasta ou reescreve frontmatter, escolha do usuário)

---

### Story S06 — Proposta de moves + merge via `migration_plan`

**Descrição**: `organizer propose` agrega os outputs de S02-S05 e gera batches em `migration_plan`:

- Cada proposta de move em batch apropriado
- Cada merge aprovado aciona: renomeia target file → `<nome>.merged-<timestamp>.md`, concatena conteúdo, atualiza wikilinks em outras notas
- Dry-run `propose --dry-run` mostra plano sem escrever

Integra com `obsidian-migrate apply` pra execução — reuso do mesmo mecanismo.

**Critérios de aceitação**:
- `propose` gera batches consistentes
- `dry-run` não escreve nada em disco
- Merge preserva conteúdo das 2 notas (nada é perdido)
- E2E: vault com 3 duplicatas + 2 clusters sem MOC → propose → approve → apply → estado final validado
