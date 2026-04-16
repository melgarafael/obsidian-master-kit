# Changelog

Todas as mudanças relevantes deste projeto são documentadas aqui.

O formato segue [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/)
e o versionamento segue [SemVer](https://semver.org/lang/pt-BR/).

## [Unreleased]

## [1.0.0] — 2026-04-15

Primeira versão completa do kit. 6 skills integradas, 310+ testes verdes em main, ~200 MB de stack instalado total.

### Adicionado

- **Skill `obsidian-migrate`** — adoção não-destrutiva em vault existente (Opção C híbrida):
  - 8 subcomandos: `status`, `shadow-scan`, `cluster`, `propose`, `plan`, `approve`, `apply`, `rollback`
  - Descoberta automática de áreas via HDBSCAN sobre embeddings Model2Vec
  - `migration_plan` auditável com máquina de estado (pending → approved/rejected → applied/rolled_back)
  - Backup obrigatório antes de qualquer movimento (checksum de estrutura validado em rollback)
  - CLAUDE.md adaptativo: render do mapa de áreas reflete o vault real, não força 4 canônicas

- **Skill `obsidian-organizer`** — curador profundo:
  - HDBSCAN sobre `vec_notes` com run_id versionado
  - Duplicate detection (cos ≥ `DUPLICATE_MIN_COS`, default 0.70 calibrado pra Model2Vec)
  - MOC audit (clusters ≥ 10 sem MOC geram `suggestions_cache` com reasoning humano)
  - Area mismatch detection (frontmatter vs pasta canônica)
  - Proposta consolidada via `migration_plan` batches

- **Skill `obsidian-expand`** — gerador de notas-ponte (fontes só do vault):
  - KNN via sqlite-vec `vec_distance_L2` com fallback numpy blob-scan
  - 3 detectores de gap (bridges, MOC shallow, reference missing via mutual-KNN graph)
  - Geração de `.md` com prompt determinista pt-br: "APENAS fontes", "NÃO invente", wikilinks obrigatórios
  - Integração com librarian fecha loop E2E (scan indexa a nota nova)

- **Skill `obsidian-pulse`** — dashboard localhost com ML:
  - Worker batch analytics (Stage B): HDBSCAN + temporal patterns + FSRS + anomaly detection + ranking
  - FSRS scheduler (Free Spaced Repetition) com reasoning explícito por sugestão
  - Anomaly detection via z-score sazonal (stdlib puro, sem pandas/Prophet)
  - Recommendation ranking com kind weights (review 0.35, bridge 0.25, moc 0.20, temporal 0.20) + anti-repetição exponencial
  - FastAPI server com auth token local-only (bind 127.0.0.1)
  - Dashboard HTMX + Jinja2 + Chart.js + cal-heatmap (6 tabs: Hoje, Pulso, Grafo, Saúde, Descobrir, Insights)
  - Privacy redaction layer (blacklist globs; sensitive nunca aparece com título em suggestions/alerts/heatmap-drill)
  - Anti-XSS por construção: zero innerHTML, tudo via `createElement` + `textContent`
  - Zero LLM no loop do dashboard (insights via templates determinísticos pt-br)

- **Foundation `core/`** compartilhada entre todas as skills:
  - SQLite schema v2 com 14 tabelas + migrations idempotentes + WAL mode
  - Parser `.md` unificado (frontmatter + wikilinks com alias + embeds + inline tags)
  - Scanner incremental delta em 3 níveis (mtime → hash → reparse) + `scan_single_file` (< 80ms)
  - Wrapper Model2Vec @ 256d L2-normalized (MRL) — stack 170 MB vs 660 MB de sentence-transformers
  - Graph module com PageRank (via networkx + scipy)
  - CLI unificado `obsidian-master` com subcomandos `init-db | scan | rebuild-db | upgrade | status | version`

- **3 slash commands**: `/obsidian-master-kit:init`, `/obsidian-master-kit:sync`, `/obsidian-master-kit:upgrade`

- **Hook PostToolUse** agora tem fastpath: emite events imediatamente via `scan_single_file` antes do signal pro agente rodar o librarian

- **Upgrade path v0.1.1 → v1.0** idempotente (preserva CLAUDE.md byte-identical, gera DB + scanner events iniciais)

- **209+ testes verdes** em main (core 97 + migrate 112 + expand 65 + organizer 53 + librarian-ext inclusos + pulse 54 = 310+)

### Arquitetura

- **Princípio zero**: `.md` é fonte de verdade, SQLite é cache sempre reconstruível via `obsidian-master rebuild-db`
- **Explicabilidade por construção**: `reasoning TEXT NOT NULL` em `suggestions_cache` e `alerts_cache` — sugestão opaca é impossível
- **Tom não-vigilante enforçado**: `alerts_cache.severity` sem `critical`; alertas como perguntas abertas; máximo 1 alerta forte por dia
- **Privacy first**: flag `sensitive` em `areas` e `notes`, redaction nos endpoints + nas listagens do `_INDEX.md`, logs proibidos de conter conteúdo cru (regex CI barra)

### Dependências

- `model2vec>=0.8.1,<1.0` + `sqlite-vec>=0.1.3` + `scikit-learn>=1.3` + `hdbscan>=0.8.38`
- `networkx>=3.3` + `scipy>=1.13.0` + `pandas>=2.2.2` + `numpy>=1.26.4`
- `fsrs>=4.0.0`
- `fastapi>=0.115.0` + `uvicorn>=0.30.0` + `jinja2>=3.1.4` + `httpx>=0.27.0` (extra `[pulse]`)

Total instalado: ~200 MB.

### Documentação

- `docs/BRIEF-v1.md` — especificação técnica completa (consolidada de sessão multi-agente de 4 cabeças)
- `docs/BRIEF-v1-addendum-phase1.md` — 10 descobertas pós-execução + lições operacionais
- `docs/stories/epics/` — 6 epics em formato `@epic-executor` (34 + 28 + 13 + 21 + 18 + 42 = 156 pontos / 39 stories)
- `docs/ROADMAP.md` — skills futuras previstas (daily-note, moc-builder, search, archiver, graph-audit, export)

## [0.1.1] — 2026-04-15

## [0.1.1] — 2026-04-15

### Adicionado
- `.claude-plugin/marketplace.json` declarando o repo como marketplace single-plugin.
  Sem esse arquivo, o Claude Code nao conseguia instalar via `/plugin install` —
  o sistema de plugins exige que o repo se declare como marketplace antes de ser
  consumido.

### Corrigido
- README e docs/DEV: instrucoes de instalacao trocadas de "git clone pra
  ~/.claude/plugins/" (que nao funciona) para o fluxo correto via
  `/plugin marketplace add` + `/plugin install` dentro do Claude Code. Isso
  funciona em todas as versoes de Claude Code sem depender de marketplace oficial
  da Anthropic.

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
