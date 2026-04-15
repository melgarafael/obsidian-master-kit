# Epic 06 — `obsidian-pulse` (dashboard + ML)

**ID**: `EPIC06-PULSE`
**Goal**: Dashboard web rodando em localhost com insights, sugestões, alertas — "Netflix/YouTube pessoal" rodando 100% local. Worker batch analytics gera tudo pré-computado em caches. Dashboard FastAPI + HTMX serve em < 500ms.
**Referência técnica**: `docs/BRIEF-v1.md` §3, §5, §8.2.
**Deps**: Epics 01-05 completos (consome dados de todos).
**Pontos totais**: 42 (o maior).

## Stories

| ID | Title | Points | Deps | Area |
|---|---|---|---|---|
| S01 | Skill shell + CLI (`refresh | serve | status`) | 3 | EPIC01-05 | shell |
| S02 | Worker batch analytics — Stage B pipeline | 8 | S01 | worker |
| S03 | FSRS scheduler integration | 3 | S02 | fsrs |
| S04 | Anomaly detection engine (z-score sazonal) | 5 | S02 | anomaly |
| S05 | Recommendation ranking + anti-repetição | 5 | S02-S04 | ranking |
| S06 | FastAPI app skeleton + autenticação local | 3 | S01 | fastapi |
| S07 | Dashboard views (6 tabs) | 8 | S02-S06 | ui |
| S08 | Privacy redaction layer | 3 | S05-S07 | privacy |
| S09 | Heatmap component | 2 | S07 | heatmap |
| S10 | Testes integração end-to-end | 5 | S01-S09 | qa |

---

### Story S01 — Skill shell + CLI

**Descrição**: Criar `skills/obsidian-pulse/SKILL.md` pt-br + `scripts/pulse.py`:

- `pulse refresh` — roda Stage B (batch analytics)
- `pulse serve [--port 4711]` — sobe FastAPI dashboard
- `pulse status` — resumo: última refresh, count de suggestions/alerts ativos, próxima refresh agendada
- `pulse daemon` — modo daemon (refresh periódico + serve)

**Critérios de aceitação**:
- `pulse serve` abre em http://localhost:4711 (porta configurável)
- Graceful shutdown em Ctrl+C
- `pulse daemon` fica em foreground com logs estruturados

---

### Story S02 — Worker batch analytics — Stage B pipeline

**Descrição**: Implementar `pulse.worker:run_batch_analytics(conn)` que executa em sequência:

1. **Refit HDBSCAN**: atualiza `notes.cluster_id` + `clusters`/`cluster_notes`
2. **Recompute `temporal_patterns`**: pandas groupby por `(dow, hour, area_id)` sobre `events` dos últimos 12 meses. Salva percentis p25/p75, média, sample_size
3. **Refit LR next-action** (só se `events >= 200`): treino em features temporais + last-action. Persiste modelo via `joblib` em `.obsidian-master/models/next_action.pkl`
4. **Run FSRS scheduler** (Story S03)
5. **Detect anomalies** (Story S04)
6. **Generate top-50 suggestions** (Story S05) → `suggestions_cache` com `expires_at=+7d`

Tempo alvo: < 2 min em vault de 5k notas.

**Critérios de aceitação**:
- Worker idempotente: rodar 2× seguidos produz mesmo estado (mesmo suggestion IDs reutilizados se unchanged)
- Modelo LR salvo + carregado corretamente entre runs
- Log estruturado de cada stage com duração

---

### Story S03 — FSRS scheduler integration

**Descrição**: Para cada nota `type in (reference, fleeting)`:

- Calcula stability + difficulty via `fsrs.Card` (lib `fsrs`)
- Heurística sem grading explícito: `updated` recente = "relembrou" (grade=Good); gap longo sem update = auto-grade=Again em vault stale
- Próxima data de revisão (`fsrs_due`) gravada em `notes`
- Se `fsrs_due <= today + 2 dias` → gera `suggestions_cache(kind='review', target_note_ids=[id])`

**Critérios de aceitação**:
- Lib `fsrs==4.0.0` instalada
- Nota recém-criada tem `fsrs_due` em ~3 dias
- Nota com 50 updates em 60 dias tem `stability` alta (intervalo crescente)
- Suggestions de review aparecem no dashboard na data certa

---

### Story S04 — Anomaly detection engine (z-score sazonal)

**Descrição**: Implementar 4 detectores conforme BRIEF §3.5:

1. **Streak quebrado**: área com streak ≥ 14 dias falhou 2+ dias
2. **Keyword emergente**: frequência de token últ 14d > μ(90d) + 3σ (após stopwords pt-br + stem via PortugueseStemmer)
3. **Área abandonada**: `time_since_last > p95 histórico` + `CV < 0.5` (cadência era regular)
4. **Produção anormal**: contagem diária > 3× média 30d (não alerta, só logga em events)

Grava em `alerts_cache` com `severity` em `{info, warn}` (sem critical — enforcement no schema). Máximo 1 alerta `warn` por dia.

**Critérios de aceitação**:
- Cada detector testado com fixture sintético que ativa o alerta
- Reasoning em pt-br, pergunta aberta ("a palavra X subiu 4× esse mês, quer olhar?")
- Regex CI: se algum reasoning contiver "você está" ou similar diagnóstico, falha o build

---

### Story S05 — Recommendation ranking + anti-repetição

**Descrição**: 3 sinais da §3.3 do BRIEF ranqueados:

```python
score = (
    0.35 * fsrs_due_score +
    0.25 * orphan_bridge_score +
    0.20 * cluster_dormancy_score +
    0.20 * temporal_match_score
)
```

**Thresholds de similaridade configuráveis** (BRIEF §3.3 listava 0.7/0.75 ancorados em MiniLM; Model2Vec static comprime range):

```
BRIDGE_MIN_COS=0.40       # pontes semânticas (par sem link direto)
ORPHAN_PROXIMITY_COS=0.45 # ranking de rediscovery
```

Env vars lidas na inicialização, defaults conservadores. Rafael calibra empírico.

Anti-repetição:

- Suggestion já mostrada nos últimos 7 dias sem ação: `score *= 0.5`
- Suggestion `dismissed`: `score *= 0.1` por 30 dias
- Sugestões do mesmo `kind` repetidas: decay crescente (2ª = 0.7, 3ª = 0.4, 4ª+ = 0.1)

Top 10 por dia, no máximo. Cada uma com `reasoning` pré-renderizado.

**Critérios de aceitação**:
- 10 sugestões geradas em 4 kinds diferentes (diversidade garantida por código)
- Dismissed 2× consecutivas → kind aparece só após 7 dias
- Reasoning nunca é `NULL` (schema constraint + lógica garantem)
- Threshold env vars mudam número de candidatos detectados (validação que config funciona)

---

### Story S06 — FastAPI app skeleton + autenticação local

**Descrição**: Criar `pulse/server.py` com FastAPI app:

- Middleware de autenticação: aceita só requests de `127.0.0.1` (bind explícito a localhost). Hook adicional: token em `.obsidian-master/pulse-token.txt` enviado via header `X-Pulse-Token`
- Endpoints: `GET /`, `GET /api/suggestions`, `GET /api/alerts`, `GET /api/heatmap`, `GET /api/insights`, `POST /api/accept/{id}`, `POST /api/dismiss/{id}`
- Templates Jinja2 em `pulse/templates/`
- Static assets (Chart.js, HTMX, Cal-Heatmap) via CDN — sem bundler

**Critérios de aceitação**:
- Server sobe em 127.0.0.1:4711 e rejeita requests de outros IPs
- Token único gerado na primeira run, armazenado localmente
- `curl localhost:4711/api/suggestions` retorna JSON válido
- CORS fechado por default (pulse é local-only)

---

### Story S07 — Dashboard views (6 tabs)

**Descrição**: Implementar 6 views (tabs HTMX):

1. **Hoje** — top 5 suggestions + alerts do dia, cards com `reasoning` embaixo
2. **Pulso** — heatmap de contribuição (S09), streak por área, produção últ 30d
3. **Grafo** — visualização simples do grafo (D3-force, topology view) com ilhas destacadas
4. **Saúde** — órfãs, rascunhos velhos (`status: draft` > 14d), pesquisa sem fonte, projetos stale
5. **Descobrir** — busca semântica + "notas que você esqueceu" (low recency, high past engagement)
6. **Insights** — padrões comportamentais narrativos (templates determinísticos, sem LLM)

Cada card tem botões `aceitar | dispensar | lembrar depois`.

**Critérios de aceitação**:
- Cada tab carrega em < 500ms
- Tabs trocam via HTMX sem reload
- Acessível em mobile (responsive básico)
- Todas as ações persistem no DB via POST endpoints

---

### Story S08 — Privacy redaction layer

**Descrição**: Implementar `pulse/privacy.py` que:

1. Detecta notas `sensitive=1` (blacklist patterns em `.obsidian-master/blacklist.json`)
2. Em suggestions/alerts, substitui `[[Diário 2025-07-12]]` por `[item em área Journaling]`
3. Reasoning é reescrita via template que omite títulos de notas sensíveis
4. Toggle no dashboard `show_sensitive` (default off) libera exibição mas requer re-login com token
5. Export CSV/JSON zera campos sensíveis mesmo com toggle on

**Critérios de aceitação**:
- Nota em pasta blacklisted nunca aparece com título em suggestions
- Teste: criar nota em `00 - Pessoal/Journaling/` + rodar organizer → suggestion redige corretamente
- `POST /api/export` com toggle off redige; com toggle on preserva não-sensíveis mas ainda redige sensitive=1

---

### Story S09 — Heatmap component

**Descrição**: Usando `cal-heatmap` via CDN, renderizar heatmap de contribuição estilo GitHub:

- Domain: semana (53 colunas)
- Sub-domain: dia (7 linhas)
- Valor: `events(note_created|note_updated|link_added) COUNT()` por dia
- Tooltip: hover revela top 3 títulos de notas tocadas no dia
- Legend: 0 / 1-3 / 4-9 / 10+

**Critérios de aceitação**:
- Renderiza corretamente vault com 2 anos de histórico
- Hover não vaza títulos de notas `sensitive=1`
- Click no dia navega pra aba Descobrir com filtro pré-aplicado

---

### Story S10 — Testes integração end-to-end

**Descrição**: Criar `tests/test_pulse_e2e.py` com cenários:

- A: fixture vault → `pulse refresh` → `pulse serve` → request `/` → todos os 6 tabs renderizam
- B: accept suggestion via POST → verificar `acted_on=1` no DB → próximo refresh deprioriza
- C: blacklist ativada → suggestion gerada pra nota sensível → dashboard redige corretamente
- D: vault com 5k notas → `refresh` termina em < 2min; dashboard abre em < 500ms
- E: 90 dias de eventos fictícios → 3 anomalies detectadas corretamente

Cobertura `pulse/` ≥ 70%.

**Critérios de aceitação**:
- `pytest tests/test_pulse_e2e.py` verde em CI
- Métricas de performance atingidas em CPU moderna (M1 / Ryzen 7)
- Smoke test manual documentado (checklist em `docs/QA-pulse.md`)

---

## Architecture contracts finais

- HTTP API documentada em `docs/API-pulse.md`
- Schema de `suggestions_cache` e `alerts_cache` estável (documentado em BRIEF §4)
- Dashboard é self-contained — zero dep de SPA externa
- Privacy é first-class: não contornável via query string ou toggle leve

## Critérios de "MVP shippable" do Epic 06 (e do kit v1 inteiro)

1. Rafael usa o dashboard por 2 semanas consecutivas sem crash
2. Ao menos 1 sugestão acionável por dia (FSRS due / bridge / cluster_dormancy)
3. Zero leak de conteúdo sensível em review manual
4. Stack total < 200 MB instalado
5. Graceful degradation: se `sqlite-vec` falhar, fallback BLOB funciona
