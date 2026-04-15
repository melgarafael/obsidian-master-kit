# BRIEF-v1 — obsidian-master-kit com ML

**Output da sessão de brainstorming multi-agente (4 cabeças, 2 rounds autônomos).**
**Status:** pronto pra virar epics e ser executado por `@epic-executor`.
**Data:** 2026-04-15.

---

## 1. Contexto e objetivo

Estender o plugin `obsidian-master-kit` (hoje v0.1.1, com 2 skills `obsidian-init` + `obsidian-librarian`) para 4 novas skills integradas, todas rodando 100% local em cima do vault Obsidian de 2 anos do Rafael (usuário 0):

1. **`obsidian-migrate`** — adoção não-destrutiva do kit num vault existente (Opção C híbrida: preserva estrutura, propõe áreas baseadas em clustering do conteúdo real, executa migração em lotes com approval)
2. **`obsidian-organizer`** — curador profundo: detecta clusters órfãos, duplicatas semânticas, MOCs faltando, propõe consolidações
3. **`obsidian-expand`** — gera notas-ponte usando **apenas** conteúdo existente como fonte (nunca inventa do mundo externo)
4. **`obsidian-pulse`** — dashboard localhost com ML ("Netflix/YouTube pessoal rodando local"): heatmap, sugestões contextuais, alertas temporais, deteção de padrões próprios, tudo explicável

**Constraints duras:**
- 100% local, zero cloud, zero telemetry
- Dataset = 1 pessoa, 2 anos (~3k-8k notas estimadas) — collaborative filtering impossível, só content-based + temporal
- Install total < 200 MB
- Tom curador, nunca vigilante — toda sugestão mostra **por que** apareceu
- Privacidade absoluta: journaling contém material pessoal sensível

---

## 2. Princípio zero — `.md` é fonte de verdade, SQLite é cache

Os arquivos `.md` são canônicos. O DB em `.obsidian-master/db.sqlite` é **sempre reconstruível** a partir do vault via comando `obsidian-master rebuild-db`. Nenhum dado vive só no DB (exceto caches reproduzíveis: embeddings, sugestões, eventos agregados).

Isso mata de raiz o anti-padrão dual-storage do Logseq: conflito entre `.md` e DB resolve sempre a favor do `.md`.

---

## 3. Escolhas de Machine Learning

### 3.1 Embeddings semânticos

**Modelo escolhido:** `Model2Vec static-similarity-mrl-multilingual-v1` truncado a **256 dimensões** via MRL (Matryoshka Representation Learning).

| Atributo | Valor |
|---|---|
| Tamanho em disco | ~8 MB (vs 420MB do MiniLM-L12 multilingual) |
| Dimensões | 1024 nativo, truncado a 256 (perda MRL: 0.56% de hits) |
| Idiomas | 51 suportados (pt-br incluído) |
| Velocidade CPU | ~500x mais rápido que all-mpnet-base-v2 |
| Runtime | `model2vec` lib (Python, numpy-only, **sem torch**) |

**Justificativa:** Model2Vec é destilação estática de sentence-transformers. Perde ~15pp em MTEB geral, mas para nosso uso (clusterizar 2k-10k notas de 1 pessoa, sugerir links entre notas próximas) 85% é excesso. Ganho real: install cai de 660MB para 170MB, reindex completo do vault vira trivial (não só noturno).

**Fallback plugável:** config `EMBEDDING_MODEL` swap para `paraphrase-multilingual-MiniLM-L12-v2` (117MB, 384d) se qualidade cair em produção real. Scanner compara `embedding_dim` em notes vs config e re-embeda tudo se detectar mismatch.

**Rejeitados:** sentence-transformers multilingual-e5-small (370MB, 3x mais lento), BGE-small-pt (só pt, quebra conteúdo técnico em inglês), mxbai-embed-large (1024 dims, 670MB), EmbeddingGemma (licença Google + peso).

### 3.2 Temporal pattern recognition

**Escolha: estatística pura (pandas + numpy). Zero modelo de série temporal.**

Prophet traz stan/cmdstan (>200MB de C++) e não entrega nada que `df.groupby(['dow', 'hour']).agg()` + rolling windows não resolva para os 4 padrões que o pulse precisa:

1. **Cadência por dia-da-semana × hora × área** — pivot simples
2. **Streaks por área** — diferença de datas consecutivas
3. **Rolling 4-week mean por área** — detecta drop de produtividade (desvio > 2σ)
4. **Sazonalidade anual** — só com > 18 meses (confirmado, 2 anos ok)

Output armazenado em tabela `temporal_patterns` pré-computada. Dashboard lê direto em < 50ms.

### 3.3 Recommendation content-based

Três sinais compõem o feed, ranqueados por score ponderado:

**a) FSRS-lite para notas `reference` ou `fleeting`.**
FSRS (Free Spaced Repetition Scheduler, 2023) calcula próxima data de revisão com stability + difficulty. Sem grading explícito do usuário, heurística: `updated` recente = "relembrou"; gap longo sem update em nota `type: reference` = devida. Lib `fsrs` (1MB).

**b) Pontes semânticas entre notas órfãs.**
Para cada par (A, B) com cosseno > 0.75 e **sem** link direto, sugerir. Query via `sqlite-vec MATCH` (virtual table vec0 retorna top-K em O(log N) com ANN). Filtro: ambas notas da mesma área OU uma delas sendo MOC.

**c) Clusters dormentes.**
HDBSCAN sobre matriz de embeddings (offline, semanal). Cluster cuja média de `last_update` > 60 dias vira sugestão "área X ficou fria, N notas sem toque". HDBSCAN sobre k-means porque descobre número natural de clusters e marca noise — o vault do Rafael é naturalmente heterogêneo.

**Ranking final:**
```
score = 0.35·fsrs_due + 0.25·orphan_proximity + 0.20·cluster_dormancy + 0.20·temporal_match
```

**Anti-repetição:** tabela `suggestions_cache` com campos `dismissed, acted_on`. Sugestão mostrada nos últimos 7 dias sem ação perde 50% de score. Dismissed explicitamente = -90% por 30 dias. Top 10 por dia, no máximo.

### 3.4 Next-action prediction

**Escolha: heurística rule-based + logistic regression como refinamento opcional.**

Dataset = ~3k-8k eventos em 2 anos. Gradient boosting ou MLP overfitam garantidamente.

**Heurística base (funciona desde dia zero, sem treino):**
```
se (dow_hoje, hora_agora) bate padrão top-3 histórico da área X:
  sugerir "abrir área X"
se streak_area_Y quebrou há 2+ dias e média histórica >= 14 dias:
  sugerir "retornar pra Y"
se último evento foi link_added entre A e B em área Z:
  sugerir "continuar em Z, notas vizinhas a A/B"
```

**Logistic regression** liga quando `COUNT(*) FROM events WHERE kind LIKE 'dashboard_%' > 200`.
Features: `dow, hour, last_3_areas, last_note_type, days_since_last_per_area (7 cols), current_streak_per_area (7 cols), recent_link_activity`.
Target: qual área o usuário abre no próximo `dashboard_open`.
`sklearn.LogisticRegression(multi_class='multinomial', class_weight='balanced')`. Treino nightly. Feature importance direta de `coef_` — base da explicabilidade.

**Cold-start do feedback loop** (primeiros 30 dias de uso do pulse, mesmo com 2 anos de vault): LR dormente, heurística serve. Ela usa temporal_patterns que NÃO são cold.

### 3.5 Anomaly detection

**Escolha: z-score sazonal. Isolation Forest rejeitado (tuning opaco, interpretabilidade morre).**

| Alerta | Sinal | Threshold |
|---|---|---|
| Streak quebrado | área com streak >= 14 dias falhou 2+ dias | absoluto |
| Keyword emergente | freq(token, últ 14d) > μ(90d) + 3σ, após stopwords pt-br + stem | sazonal |
| Área abandonada | time_since_last > p95 histórico, CV < 0.5 (cadência regular) | percentil |
| Produção anormal | contagem diária > 3x média 30d | não alerta, só logga |

**Tom obrigatório:** SEMPRE pergunta aberta, NUNCA diagnóstico. Não "você está em burnout" — sim *"a palavra burnout subiu 4x esse mês, quer olhar?"*. Máximo **1 alerta forte por dia** no topo do dashboard, resto vai para aba "padrões" passiva.

### 3.6 Explicabilidade — first-class citizen do schema

Cada sugestão e alerta tem coluna `reasoning TEXT NOT NULL` no cache. Constraint garante que sugestão opaca é impossível por construção.

Quatro padrões de reasoning em produção:

1. **Revisão FSRS:** *"Sugerindo revisar 'Circuito da Realidade - Hermetismo' — FSRS indica devido (último toque 47 dias, stability 32d). Dom 21h você abriu Pesquisas em 12 dos últimos 16 domingos."*
2. **Ponte semântica:** *"'Tábua de Esmeralda' e 'Princípios Herméticos' têm similaridade 0.82 mas nenhum link entre si. 18 notas de Pesquisas linkam uma das duas, não as duas."*
3. **Alerta temporal:** *"Área Profissional: última atualização há 9 dias. Seu p95 histórico é 6 dias. Maior pausa em 2 anos."*
4. **Next-action (LR):** *"Sugerindo Pessoal. Top features: dow=dom (peso 0.41), hora=22 (0.28), last_area=Pesquisas (0.19)."*

**SHAP rejeitado:** LR linear — `coef_ × feature` JÁ é explicação exata. SHAP é dep extra e overhead para nada.

---

## 4. Schema de dados — SQLite em `.obsidian-master/db.sqlite`

Abertura: `PRAGMA foreign_keys=ON; journal_mode=WAL; synchronous=NORMAL`. WAL permite dashboard ler durante scan.

**Tabelas principais** (ver brief técnico completo nas seções dos agentes na `Nota Compartilhada - Obsidian Master`):

- `schema_version` — migrations idempotentes
- `areas` — áreas dinâmicas descobertas via HDBSCAN (Opção C), com flag `is_canonical` e `sensitive`
- `notes` — linha por `.md`, com `frontmatter_json` preservando campos custom, `body_hash`, `embedding_model`, `embedding_dim`, `pagerank`, `deleted_at` (soft-delete)
- `vec_notes` (virtual table `vec0`) — embedding 256d via sqlite-vec
- `notes_embedding_blob` — fallback quando extension não carrega
- `tags` + `note_tags` — tags hierárquicas como path string (`profissional/projeto`), índice prefix-aware
- `aliases`
- `links` — preserva intenção mesmo quando link quebrado (`to_note_id` nullable + `to_target` TEXT)
- `events` — série temporal. 10 event_types validados por CHECK constraint: `note_created`, `note_updated`, `note_deleted`, `link_added`, `link_removed`, `dashboard_open`, `scan_run`, `suggestion_shown`, `suggestion_accepted`, `suggestion_dismissed`
- `clusters` + `cluster_notes` — output do HDBSCAN, com `label`, `algorithm`, `proposed_area_id`, `proposed_moc_path`
- `duplicate_candidates` — pares com cos ≥ 0.92 esperando verdict humano
- `suggestions_cache` — TTL de 24h, `kind` enum (rediscover/bridge/stale/drift/moc_missing/duplicate/cluster_label), `reasoning NOT NULL`, `score`, `dismissed`
- `alerts_cache` — análogo, `severity` só tem `info|warn` (sem `critical` — enforcement do anti-tom-vigilante no schema)
- `migration_plan` — Opção C por batch: `status pending|approved|rejected|applied`, `current_location`, `proposed_location`, `reason`, `confidence`

**Índices críticos:** `(area_id)`, `(updated DESC)`, `(mtime DESC)`, `(body_hash)` em `notes`; `(date, event_type)` e `(area_id, date)` em `events`; `(dismissed, kind, expires_at)` em caches.

---

## 5. Pipeline completo — ingestão → features → modelo → UI

**Três estágios. Runner CLI único `obsidian-pulse` com subcommands `ingest | refresh | serve | status`.**

### 5.1 Stage A — Ingest (incremental, <30s para 2k notas)

Delta em 3 níveis:

1. **mtime check** (zero I/O além de `stat`): se `stat.mtime == notes.mtime`, skip
2. **body_hash check** (lê arquivo, hasheia SHA256): se hash bate, atualiza só mtime
3. **full reparse** (parse YAML + links + tags + word_count): se hash mudou

Então:
- Glob `.md`, respeitando ignore patterns (`.obsidian/`, `.trash/`, `.obsidian-master/`, `_templates/`, `node_modules/`, `.git/`, `.DS_Store`, `*.backup-*`, mais `.obsidian-master/ignore.txt` gitignore-syntax)
- Parser reusa `skills/obsidian-librarian/scripts/update_index.py:parse_frontmatter` movido para `core/parser.py` + extensões (wiki-links com alias `[[X|Y]]`, embeds `![[X]]`)
- Recompute embedding via Model2Vec (batch de 64 notas) só se `body_hash` mudou E `|Δword_count|/old > 15%` OU título mudou OU primeiros 500 chars mudaram
- Grafo pós-scan: `in_degree`, `out_degree` via `COUNT(*) GROUP BY`; PageRank via `nx.pagerank(G, alpha=0.85)` (~2s em 2k nodes). Betweenness só sob flag `--with-betweenness` (O(n³))
- Deleções: notas no DB sem arquivo no disco → `deleted_at=now()` + emite `note_deleted`
- Escreve em `notes`, `embeddings` (via `vec0`), `events`, atualiza `links`

### 5.2 Stage B — Batch analytics (nightly cron ou first `dashboard_open` do dia)

1. Refit HDBSCAN (atualiza `notes.cluster_id` e tabelas `clusters`/`cluster_notes`)
2. Recompute `temporal_patterns` via pandas groupby
3. Refit LR next-action (se `events >= 200`)
4. Run FSRS scheduler para notas `type: reference|fleeting` (grava due_date em `notes.fsrs_due`)
5. Detect anomalies, escreve em `alerts_cache`
6. Gera top-50 sugestões ranked, escreve em `suggestions_cache` (expires_at = +7d)

### 5.3 Stage C — Dashboard serve (FastAPI + HTMX)

- Endpoints: `GET /` (dashboard), `GET /api/suggestions`, `GET /api/alerts`, `POST /api/accept/{id}`, `POST /api/dismiss/{id}`, `GET /api/heatmap`
- Todos leem de caches pré-computados — abre em < 500ms
- Ação do usuário (dismiss/act) → event → próximo run de Stage B deprioriza kinds repetidamente dismissados
- Concorrência: WAL permite leitura durante scan

---

## 6. Arquitetura das 4 skills — como dialogam via SQLite

```
                      ┌── SQLite (.obsidian-master/db.sqlite) ──┐
                      │ notes/areas/tags/links/events/clusters  │
                      │ vec_notes/migration_plan/*_cache        │
                      └──▲────▲────▲─────▲─────▲────────────────┘
                         │    │    │     │     │
                     migrate librarian organizer expand pulse
                     (popular)(sync+ev)(propor) (gerar)(servir)
```

- **`obsidian-migrate`**: primeira indexação completa. Popula `notes`, descobre `areas` via HDBSCAN, propõe moves em `migration_plan` com `status=pending` por `batch_id`. **Não move arquivos até approval humano.**
- **`obsidian-librarian`** (estende o existente v0.1.1): cada sync escreve `events` (`scan_run`, `note_created/updated/deleted`). `_INDEX.md` passa a consumir contadores do DB.
- **`obsidian-organizer`**: HDBSCAN sobre `vec_notes` → escreve `clusters` + `cluster_notes`. Duplicatas (cos ≥ 0.92) → `duplicate_candidates`. Clusters ≥ 10 notas sem MOC → `suggestions_cache(kind='moc_missing')`. Propõe moves → `migration_plan`.
- **`obsidian-expand`**: KNN em `vec_notes` + proximidade de grafo → acha gaps. Gera `.md` com frontmatter `generated_by: obsidian-expand, status: draft, source: <nota-origem>`. Librarian indexa no próximo sync.
- **`obsidian-pulse`**: lê tudo. Worker periódico preenche `suggestions_cache` + `alerts_cache` com TTL de 24h. Dashboard FastAPI+HTMX lê cache.

---

## 7. Migração Opção C — procedimento operacional

1. **Backup obrigatório:** `cp -R <vault>/ <vault>.backup-YYYYMMDD-HHMMSS/`. Aborta se `df` mostra < 2× livre
2. **Shadow scan:** embeda tudo, nada se move. Produz mapa `folder → cluster_ids`
3. **HDBSCAN** com `min_cluster_size = max(5, n_notas/200)`. Por cluster: top 8 tokens TF-IDF (stopwords pt-br + en), 3 notas centrais, label via Claude
4. **Mapping folder → area:** cluster dominante > 60% da pasta → pasta vira área. Espalhado → usuário decide interativamente
5. **CLAUDE.md adaptativo:** template com `{{areas}}` renderiza o set descoberto. Rafael pode acabar com 4, 6 ou 8 áreas — conforme vault real, não forçando as 4 canônicas
6. **Approval por batch:** `migration_plan` em lotes de 20. CLI interativo `obsidian-migrate approve --batch N` mostra diffs
7. **Rollback:** `obsidian-migrate rollback --batch N` reverte via `current_location`

---

## 8. Stack Python + estrutura de módulos

### 8.1 Dependências definitivas

```
model2vec==0.4.0              # ~3MB lib + ~8MB modelo baixado on-install
scikit-learn==1.5.0           # ~40MB (LR + HDBSCAN wrapper)
hdbscan==0.8.38               # ~15MB (cython, clustering)
pandas==2.2.2                 # ~50MB
numpy==1.26.4                 # ~25MB (dep transitiva)
sqlite-vec==0.1.3             # ~2MB (virtual table vec0 para ANN)
fsrs==4.0.0                   # ~1MB (spaced repetition)
networkx==3.3                 # ~10MB (PageRank)
fastapi==0.115.0              # ~15MB
uvicorn==0.30.0               # ~5MB
jinja2==3.1.4                 # ~5MB (templates HTMX)
```

**Total: ~170 MB instalado.**

**Rejeitados explicitamente:** Prophet (200MB+ sem ganho), LightGBM (dataset N=1 não justifica), spaCy (lemma pt-br custa 500MB), transformers full (desnecessário com Model2Vec), Streamlit (pesado, feio), torch (evitado justamente pelo Model2Vec ser numpy-puro), SHAP (LR linear já é interpretável).

### 8.2 Frontend do dashboard

**FastAPI + HTMX + Jinja2 + Chart.js via CDN.**

Razões: sem bundler, sem npm, stack Python-pura, HTMX permite interatividade rica (sugestão aceita/dismiss sem reload) e dashboards bonitos em < 500 linhas de HTML. Zero dependência de frontend tooling.

### 8.3 Estrutura de módulos

```
obsidian-master/
├── core/
│   ├── __init__.py
│   ├── db.py          # connect (pragmas + vec0 fallback), migrations/, DAOs
│   ├── parser.py      # movido de librarian, estendido
│   ├── scanner.py     # walk + delta (mtime → hash → reparse)
│   ├── features.py    # word_count, hash, graph metrics
│   ├── embeddings.py  # Embedder Protocol; default Model2Vec MRL@256
│   ├── graph.py       # PageRank, in/out degree, MOC inference
│   ├── paths.py       # vault root detection, ignore patterns
│   └── migrations/
│       ├── 001_initial.sql
│       └── ...
└── skills/
    ├── obsidian-init/        # existente, v0.1.1
    ├── obsidian-librarian/   # existente, estendido para escrever events
    ├── obsidian-migrate/     # NOVA
    ├── obsidian-organizer/   # NOVA
    ├── obsidian-expand/      # NOVA
    └── obsidian-pulse/       # NOVA (maior — inclui FastAPI app)
```

**Contrato de embeddings:**
```python
class Embedder(Protocol):
    model_name: str
    dim: int  # 256
    def embed(self, texts: list[str]) -> np.ndarray: ...
```

Migrations idempotentes via `schema_version`. `core/db.py:connect()` tenta carregar sqlite-vec; se falhar, usa `notes_embedding_blob` com cosine full-scan (mais lento mas funcional).

---

## 9. Privacidade e dados sensíveis

1. **Local-only duro:** DB em `.obsidian-master/` (já no `.gitignore`). Zero syscall de rede no core. Embeddings gerados offline.
2. **Flag `sensitive`** em `areas` e `notes`. Setada auto via `.obsidian-master/blacklist.json` (glob patterns tipo `00 - Pessoal/Journaling/**`)
3. **Redação:** em `suggestions_cache` e `alerts_cache`, nota sensível nunca aparece com título/snippet. `reasoning` redige: *"item em [área: Journaling] com cos=0.87"* em vez de *"[[Diário 2025-07-12]]"*
4. **Dashboard:** toggle `show_sensitive` (default off). Export CSV/JSON zera campos sensíveis mesmo com toggle on
5. **Logging:** logger estruturado aceita só `note_id` / `path_hash`. Regra de CI: regex que detecta `body` ou `content` em chamadas de log falha o build
6. **Embeddings de nota sensível OK** (vetor é irreversível na prática), mas nunca saem do DB — dashboard só serve similaridades agregadas, nunca vetor cru

---

## 10. Riscos, tradeoffs, anti-padrões evitados

### Tradeoffs assumidos

| Trade-off | Decisão | Risco aceito |
|---|---|---|
| Embedding rico vs leve | Model2Vec 256d (leve) | Qualidade pt-br não benchmarkada — fallback plugável mitiga |
| Série temporal formal vs estatística | pandas groupby | Se padrões anuais ficarem ruidosos, adicionar `statsmodels STL` na v1.x |
| Next-action classifier vs heurística | Híbrido (heurística default, LR opcional) | Pode não capturar padrões não-lineares — aceitável em N=1 |
| SQLite vs DB real | SQLite com WAL + vec0 | Scaling limit ~50k notas; muito além do uso real |
| Frontend separado vs Python puro | HTMX + Jinja | Menos rico que SPA React, mas manutenção trivial |

### Anti-padrões evitados por construção

- ✅ ML que não roda local em CPU razoável → Model2Vec numpy-puro
- ✅ Feature creep → escopo congelado em 4 skills, sem "v1.5 teria X"
- ✅ Serviços cloud → zero syscall de rede no core
- ✅ Collaborative filtering → tudo content-based + temporal (dataset N=1)
- ✅ Sugestões opacas → `reasoning NOT NULL` no schema
- ✅ Tom vigilante → `severity` sem `critical`; alerts ≤ 1/dia; reasoning como pergunta aberta
- ✅ Arquivos binários no scan → ignore patterns fixos + extensível
- ✅ Logging de conteúdo cru → regex CI barra commits com `body`/`content` em log calls
- ✅ Schema drift → `frontmatter_json` preserva campos custom
- ✅ Vendor lock → `.md` é fonte de verdade, DB é reconstruível via comando

---

## 11. Ordem de execução sugerida para `@epic-executor`

Dependências de dados ditam a ordem. 6 epics sequenciais:

### Epic 1 — `core/` foundation
Bloqueia tudo. Modulos compartilhados + schema SQLite + migrations + tests. Sem skill nova ainda, só infra.

**Deliverables:**
- `core/db.py` com `connect()`, migrations idempotentes, vec0 fallback
- `core/parser.py` estendido a partir de `update_index.py`
- `core/scanner.py` com delta em 3 níveis
- `core/embeddings.py` com `Embedder` protocol + `Model2VecEmbedder`
- `core/graph.py` com PageRank
- `core/paths.py` com ignore patterns
- Migrations 001 (schema completo)
- Testes unitários dos parsers e delta

### Epic 2 — `obsidian-migrate` (Opção C)
Primeira skill que consome o `core/`. Popula o DB inicial + propõe áreas.

**Deliverables:**
- SKILL.md pt-br
- `scripts/migrate.py` com subcommands `scan | propose | approve | apply | rollback`
- Integração com HDBSCAN para descoberta de áreas
- CLAUDE.md adaptativo via template
- Testes end-to-end em vault de fixture
- Backup obrigatório como primeira etapa

### Epic 3 — Estender `obsidian-librarian`
Trava a curadoria contínua sobre o novo DB.

**Deliverables:**
- `update_index.py` passa a escrever `events`
- `_INDEX.md` consome contadores do DB
- Hook PostToolUse continua funcionando
- Migration de vaults que já têm v0.1.1 instalado (não-destrutiva)

### Epic 4 — `obsidian-organizer`
HDBSCAN + detecção de duplicatas + MOCs faltando.

**Deliverables:**
- SKILL.md
- `scripts/organizer.py` com `cluster | duplicates | moc-audit | propose`
- Geração de suggestions do tipo `cluster_label`, `moc_missing`, `duplicate`
- Integração com `migration_plan` (propõe moves sem aplicar)

### Epic 5 — `obsidian-expand`
KNN + geração de notas-ponte.

**Deliverables:**
- SKILL.md
- `scripts/expand.py` com `bridges | expand-moc | fill-gaps`
- Geração de notas draft com `generated_by` e `source`
- Prompt engineering para usar só conteúdo do vault (sem mundo externo)

### Epic 6 — `obsidian-pulse` (maior)
Worker + dashboard web. Depende de TODOS os anteriores estarem maduros.

**Deliverables:**
- SKILL.md
- `scripts/pulse.py` com `refresh | serve | status`
- Worker de batch analytics (Stage B)
- FastAPI app com templates Jinja + HTMX
- 5 views do dashboard: Hoje, Pulso, Grafo, Saúde, Descobrir, Insights
- Testes de integração end-to-end (vault → DB → dashboard → ação)
- Documentação de uso

Cada epic entrega **uma funcionalidade shippável** em isolamento. Epic 1 é pré-requisito absoluto; Epics 2-5 podem ser paralelizados após Epic 1. Epic 6 depende de 1-5.

---

## 12. Referências externas

### 12.1 Precedentes diretos no ecossistema Obsidian

1. [Smart Connections](https://github.com/brianpetro/obsidian-smart-connections) — plugin com centenas de milhares de users rodando embeddings 100% locais. Prova que indexar vault real em CPU doméstica é viável. Padrão: hook após save, embeda só o diff, em background.
2. [Copilot for Obsidian (logancyang)](https://github.com/logancyang/obsidian-copilot) — RAG completo com Ollama + nomic-embed-text local. Template arquitetural de referência.
3. [Omnisearch](https://github.com/scambier/obsidian-omnisearch) — busca full-text via MiniSearch. Alternativa pura-FTS se quisermos simplificar busca.
4. [Logseq DB schema (DeepWiki)](https://deepwiki.com/logseq/logseq/4.2-database-schema-and-validation) — Datascript + SQLite com blocks/parent/properties como entidades first-class. **Aprendizado:** dual-storage sem source-of-truth = bug-factory.

### 12.2 ML local & embeddings

5. [static-similarity-mrl-multilingual-v1 (model card)](https://huggingface.co/sentence-transformers/static-similarity-mrl-multilingual-v1) — 51 idiomas (pt incluso; pt não está nos 5 de eval). MRL dims: 1024/512/256/128/64/32. Perda: 0.15% em 512, 0.56% em 256.
6. [Static Embeddings blog (HF)](https://huggingface.co/blog/static-embeddings) — justificativa técnica Model2Vec.
7. [EmbeddingGemma (2025)](https://huggingface.co/blog/embeddinggemma) — fallback mais rico se qualidade insuficiente.
8. [MTEB benchmark](https://github.com/embeddings-benchmark/mteb) — critério objetivo de troca.
9. [BERTopic](https://maartengr.github.io/BERTopic/) — pipeline sentence-embeddings + UMAP + HDBSCAN + c-TF-IDF. HDBSCAN permite outliers.

### 12.3 Spaced repetition & recomendação content-based

10. [FSRS (fsrs4anki)](https://github.com/open-spaced-repetition/fsrs4anki) — Free Spaced Repetition Scheduler. Three-Component Model (Retrievability/Stability/Difficulty).
11. [Explainable Recommendation: A Survey (arXiv 1804.11192)](https://arxiv.org/abs/1804.11192) — toda sugestão sem "por quê" mina confiança.
12. [Cold Start (Wikipedia)](https://en.wikipedia.org/wiki/Cold_start_(recommender_systems)) — confirma tecnicamente content-based como escolha para N=1.
13. [Matryoshka Representation Learning (arXiv 2205.13147)](https://arxiv.org/abs/2205.13147) — truncamento de dimensões com perda mínima.

### 12.4 Inspirações de produto

14. [Netflix Research — Recommendations](https://research.netflix.com/research-area/recommendations) — hybrid content + collaborative com LSTMs/VAEs.
15. [Spotify Wrapped methodology 2025](https://newsroom.spotify.com/2025-12-05/wrapped-methodology-explained/) — heurísticas priorizadas + LM fine-tuned para narrativa.
16. [Duolingo — How the owl decides](https://blog.duolingo.com/hi-its-duo-the-ai-behind-the-meme/) — multi-armed bandit para escolha de notificação.
17. [RescueTime Productivity Pulse](https://help.rescuetime.com/article/73-how-is-my-productivity-pulse-calculated) — **usado como anti-exemplo** (score único 0-100 que mata introspecção).
18. [Cal-Heatmap](https://github.com/wa0x6e/cal-heatmap) — lib JS pra replicar heatmap GitHub-style.
19. [HTMX](https://htmx.org) — interatividade rica sem SPA, justificou o stack do dashboard.

### 12.5 Inspirações — o que especificamente importamos

- **Netflix (hybrid recs)** → similaridade item-based traduzida pra notes: dado nota atual, top-k ranking por `cosine(embedding) + jaccard(tags+links)`. NÃO importamos user-based (N=1).
- **YouTube Shorts (swipe-away rate)** → dismissal = signal. Duas dispensas consecutivas de mesma classe de insight = decay de 7 dias. Substitui swipe por X explícito.
- **Duolingo (multi-armed bandit)** → bandit escolhe QUAL insight surfacar entre candidatos (links faltando / cluster emergente / órfã / padrão temporal / revisão FSRS). Reward = clique/aceite. **NÃO importamos streaks nem push ansiogênico** — pulse é pull, dashboard abre quando Rafael quer.
- **GitHub heatmap** → calendar grid (domain=semana, sub-domain=dia), intensidade = notas criadas + editadas. Hover revela títulos.
- **Spotify Wrapped (heurísticas priorizadas)** → top-5 standout days/weeks por heurísticas ordenadas. **NÃO importamos LM generativo** — templates com variáveis geram narrativa determinista.
- **BERTopic pipeline** → sentence-embeddings + UMAP + HDBSCAN. HDBSCAN deixa outliers de fora — crítico: notas idiossincráticas (sonhos, journaling) NÃO são forçadas em cluster.
- **Smart Connections (indexação)** → hook após save, embeda só o diff, em background. Padrão já validado no ecossistema Obsidian.

### 12.6 Anti-padrões consolidados com regra aplicável

1. **Sugestões opacas (Netflix/Spotify/YouTube)** → regra: todo card do pulse mostra "por quê" em 1 linha. Aplica-se ao schema: coluna `reasoning TEXT NOT NULL` em `suggestions_cache`.
2. **Streak vanity (Duolingo)** → regra: não criar métrica de consistência sem ação derivada. Se mostrar streak, acopla ao tópico ("você mantém Hermetismo constante há 4 semanas"), nunca só o número.
3. **Score KPI-like (RescueTime Productivity Pulse)** → regra: NÃO resumir vault em 0-100. Goodhart mata vault reflexivo. Substituição: 3-5 observações qualitativas por semana.
4. **Feed infinito / shelf-bloat (Netflix/YouTube home)** → regra: pulse mostra **máximo 5 insights por dia**, ordenados por bandit score. Aplica-se ao endpoint FastAPI: `LIMIT 5` em queries de `suggestions_cache`.
5. **LLM no loop crítico (Spotify Wrapped 2025, Mem 2.0)** → regra: zero LLM no pulse core. Templates + variáveis. LLM só em `obsidian-expand` onde o usuário invoca conscientemente. Motivos: peso, determinismo, privacidade.
6. **Dual-storage sem source-of-truth (Logseq)** → regra: `.md` é truth, SQLite é cache descartável. Se divergir, regenera do `.md`. Nunca o contrário.

---

## 13. Próximos passos

1. Rafael revisa este BRIEF-v1.md (foco: concorda com ML choices? HDBSCAN apropriado? FastAPI+HTMX confortável?)
2. Eventuais ajustes
3. Criação dos 6 epics como arquivos em `docs/stories/epics/` no formato `@epic-executor`
4. Execução wave-a-wave do Epic 1 (`core/`) até finalizar
5. Shipar v1.0 do kit com ML

---

*Brainstorming facilitado via Maestri — time de 4 agentes (Pesquisador + ML Architect + Data Architect + Orquestrador) em 2 rounds autônomos com cross-review.*
