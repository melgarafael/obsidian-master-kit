# Epic 01 — `core/` foundation

**ID**: `EPIC01-CORE`
**Goal**: Entregar o módulo `core/` compartilhado entre todas as skills futuras. Schema SQLite completo, migrations idempotentes, parser `.md`, scanner incremental, wrapper de embeddings, análise de grafo, CLI unificado.
**Referência técnica**: `docs/BRIEF-v1.md` §2, §4, §5.1, §8.3.
**Pré-requisito de**: Epics 02, 03, 04, 05, 06 (todos).
**Pontos totais**: 34.

## Stories

| ID | Title | Points | Deps | Area |
|---|---|---|---|---|
| S01 | Schema SQLite inicial + migrations system | 5 | — | db |
| S02 | Parser `.md` estendido | 3 | S01 | parser |
| S03 | Scanner incremental com delta em 3 níveis | 8 | S01, S02 | scanner |
| S04 | Wrapper de embeddings (Model2Vec + fallback) | 5 | S01 | ml |
| S05 | Módulo de features + análise de grafo | 5 | S01, S03 | graph |
| S06 | CLI unificado `obsidian-master` | 3 | S01-S05 | cli |
| S07 | Fixture de vault + testes de integração | 5 | S01-S06 | qa |

---

### Story S01 — Schema SQLite inicial + migrations system

**Descrição**: Implementar `core/db.py` com `connect()` que aplica PRAGMAs (`foreign_keys=ON`, `journal_mode=WAL`, `synchronous=NORMAL`), carrega extensão `sqlite-vec` (com fallback pra BLOB plano se extension não carregar), e roda migrations idempotentes via tabela `schema_version`. Primeira migration `migrations/001_initial.sql` cria todas as tabelas do BRIEF §4: `areas`, `notes`, `vec_notes` (virtual table vec0), `notes_embedding_blob` (fallback), `tags`, `note_tags`, `aliases`, `links`, `events` (com CHECK constraint dos 10 event_types), `clusters`, `cluster_notes`, `duplicate_candidates`, `suggestions_cache`, `alerts_cache`, `migration_plan`, `temporal_patterns`. Todos os índices listados no BRIEF.

**Critérios de aceitação**:
- `connect(vault_path)` cria `<vault>/.obsidian-master/db.sqlite` se não existir
- Rodar `connect` duas vezes não causa erro (migrations idempotentes)
- `SELECT version FROM schema_version` retorna `1` após primeira conexão
- `sqlite-vec` carrega com sucesso; se não, fallback ativo e log de warning
- `reasoning NOT NULL` e `severity NOT IN ('critical')` enforçados no schema
- Teste unitário valida criação de cada tabela e índices

**Contratos expostos**:
- `core.db.connect(vault_path: Path) -> sqlite3.Connection`
- `core.db.ensure_schema(conn)` (idempotente)

---

### Story S02 — Parser `.md` estendido

**Descrição**: Mover `skills/obsidian-librarian/scripts/update_index.py:parse_frontmatter` para `core/parser.py`. Estender para: wiki-links com alias `[[X|Y]]`, embeds `![[X]]`, inline tags `#pai/filho` no corpo, aliases no frontmatter como lista. Preservar conteúdo cru via `frontmatter_json` (fidelidade 100% a campos custom).

**Critérios de aceitação**:
- `parse_markdown(text: str) -> ParsedNote` retorna dataclass com: `frontmatter_dict`, `frontmatter_raw_json`, `body`, `wikilinks: list[WikiLink]`, `embeds: list[str]`, `inline_tags: list[str]`, `word_count`, `body_hash` (SHA256)
- Frontmatter malformado é tratado com erro estruturado, não crash
- Wikilinks preservam alias: `[[Nota|Alias]]` retorna `WikiLink(target='Nota', alias='Alias')`
- Teste unitário com ≥20 casos (YAML válido, malformado, sem frontmatter, tags inline, links diversos, embeds)

**Contratos expostos**:
- `core.parser.parse_markdown(text)` → `ParsedNote`
- `core.parser.ParsedNote` dataclass

---

### Story S03 — Scanner incremental com delta em 3 níveis

**Descrição**: Implementar `core/scanner.py:scan(conn, vault_path, embedder)`. Walk recursivo do vault respeitando ignore patterns (`.obsidian/`, `.trash/`, `.obsidian-master/`, `_templates/`, `node_modules/`, `.git/`, `.DS_Store`, `*.backup-*`, extensível via `.obsidian-master/ignore.txt`). Para cada `.md`:

1. **Nível 1 (mtime)**: se `stat.mtime == notes.mtime` no DB, skip
2. **Nível 2 (hash)**: lê arquivo, SHA256 do body; se hash bate, atualiza só `mtime` e passa
3. **Nível 3 (reparse)**: chama `parser.parse_markdown`, atualiza `notes` + `note_tags` + `aliases` + `links`, emite `events(note_created|note_updated)`

Re-embedding condicional: só se body_hash mudou E (`|Δword_count|/old > 15%` OU título mudou OU primeiros 500 chars mudaram). Deleções: notas no DB sem arquivo no disco → `deleted_at=now()` + emite `note_deleted`.

**Critérios de aceitação**:
- Scan completo de vault com 2000 notas termina em < 30s (CPU moderna)
- Scan subsequente sem mudanças termina em < 2s (apenas stat checks)
- Reimport após `UPDATE notes SET body_hash='bogus'` detecta e reparseia
- Links quebrados são registrados em `links` com `to_note_id=NULL` e `to_target` preservado
- Ignore patterns funcionam (test em fixture com `.obsidian/` e `node_modules/`)

**Contratos expostos**:
- `core.scanner.scan(conn, vault_path, embedder=None) -> ScanReport`
- `core.scanner.ScanReport` dataclass com counts (created/updated/deleted/skipped)

---

### Story S04 — Wrapper de embeddings (Model2Vec + fallback)

**Descrição**: Implementar `core/embeddings.py`. Definir Protocol `Embedder` com `model_name: str`, `dim: int`, `embed(texts: list[str]) -> np.ndarray`. Implementação default `Model2VecEmbedder` usando `model2vec` lib, modelo `static-similarity-mrl-multilingual-v1` truncado a 256 dimensões via MRL. Baixar modelo on-install (uma vez, cache em `~/.cache/model2vec/`). Serialização: `pack(vec) -> bytes` (float32.tobytes() = 1024 bytes), `unpack(blob, dim=256) -> np.ndarray`.

Configuração via env var `EMBEDDING_MODEL` (default `model2vec-mrl-256`). Swap pra `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` via `PARAPHRASE_FALLBACK=1`.

**Critérios de aceitação**:
- `Model2VecEmbedder().embed(["texto"]).shape == (1, 256)`
- `pack(vec)` retorna exatamente 1024 bytes para 256 dims float32
- `unpack(pack(v))` devolve array bit-idêntico
- Swap de modelo via config funciona e dispara re-embed total (scanner detecta `embedding_model` divergente em `notes`)
- Batch de 64 textos em < 2s em CPU moderna

**Contratos expostos**:
- `core.embeddings.Embedder` Protocol
- `core.embeddings.Model2VecEmbedder` default
- `core.embeddings.pack(vec) -> bytes`
- `core.embeddings.unpack(blob, dim) -> np.ndarray`
- `core.embeddings.get_default_embedder() -> Embedder`

---

### Story S05 — Módulo de features + análise de grafo

**Descrição**: Implementar `core/features.py` (word_count, char_count, body_hash — reuso) e `core/graph.py`. O graph module calcula, a partir da tabela `links`:

- `in_degree`, `out_degree` via `COUNT(*) GROUP BY`
- `pagerank` via `networkx.pagerank(G, alpha=0.85)` (~2s em 2k nodes)
- Detecção de MOCs (notas com `out_degree > 10` e `in_degree > 5` em clusters densos)
- Betweenness centrality só sob flag `--with-betweenness` (O(n³), opt-in)

Grava resultados nas colunas `notes.in_degree`, `notes.out_degree`, `notes.pagerank`.

**Critérios de aceitação**:
- `update_graph_metrics(conn)` atualiza as 3 colunas para todas as notas
- PageRank sum = 1.0 (±0.001) em teste unitário
- Com 2000 nodes, `update_graph_metrics` termina em < 3s
- Links quebrados (to_note_id=NULL) não contam em `in_degree` de nenhuma nota

**Contratos expostos**:
- `core.graph.update_graph_metrics(conn, with_betweenness=False)`
- `core.graph.find_mocs(conn) -> list[int]` (retorna note_ids candidatos a MOC)

---

### Story S06 — CLI unificado `obsidian-master`

**Descrição**: Criar entry point `obsidian-master` (via `pyproject.toml` scripts). Subcommands:

- `obsidian-master init-db [--vault PATH]` — força criação/upgrade do DB
- `obsidian-master scan [--vault PATH]` — roda scanner completo
- `obsidian-master rebuild-db [--vault PATH]` — apaga DB e reconstrói do zero lendo `.md`
- `obsidian-master status [--vault PATH]` — resumo: #notas, último scan, tamanho DB
- `obsidian-master version` — versão do kit + versão do schema DB

Vault path padrão: pwd se tem `.obsidian-master/marker.json` (qualquer ancestral), senão erro claro.

**Critérios de aceitação**:
- `obsidian-master status` em vault não-inicializado dá erro com mensagem útil
- `obsidian-master init-db` + `obsidian-master scan` popula DB com sucesso
- `obsidian-master rebuild-db` confirma interativamente antes de apagar
- `--help` de cada subcommand é em pt-br e mostra exemplos

**Contratos expostos**:
- Binário `obsidian-master` no PATH após `pip install`

---

### Story S07 — Fixture de vault + testes de integração

**Descrição**: Criar `tests/fixtures/vault_fixture/` com vault de teste bem estruturado (~50 notas, 4-6 áreas fictícias, notas com/sem frontmatter, links internos, alguns links quebrados, uma nota em `_templates/` pra testar ignore pattern). Testes de integração end-to-end em `tests/test_core_integration.py`:

- Cenário A: vault novo → `init-db` + `scan` → valida counts
- Cenário B: vault já com DB → edita 1 nota → `scan` detecta só 1 mudança
- Cenário C: deleta 1 nota do disco → `scan` marca como `deleted_at`
- Cenário D: renomeia arquivo → scanner detecta como delete + create
- Cenário E: muda `EMBEDDING_MODEL` via env → scanner re-embeda tudo

**Critérios de aceitação**:
- `pytest tests/test_core_integration.py` passa verde
- Cobertura do `core/` ≥ 75% (via `pytest-cov`)
- CI roda testes em GitHub Actions

---

## Architecture contracts (expostos pro Epic 02+)

- `core.db.connect(vault_path)` → conexão SQLite pronta
- `core.parser.parse_markdown(text)` → ParsedNote
- `core.scanner.scan(conn, vault_path, embedder)` → ScanReport
- `core.embeddings.get_default_embedder()` → Embedder
- `core.graph.update_graph_metrics(conn)`
- CLI `obsidian-master` com subcommands `init-db | scan | rebuild-db | status | version`

## Deps (from the main stack)

Adicionar ao `pyproject.toml`:
- `model2vec>=0.4.0`
- `sqlite-vec>=0.1.3`
- `networkx>=3.3`
- `numpy>=1.26.4`
