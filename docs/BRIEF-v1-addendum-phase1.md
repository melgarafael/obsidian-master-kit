# BRIEF-v1 Addendum — Achados da Fase 1 (Epic 01 core/)

**Data**: 2026-04-15 (pós-execução Epic 01)
**Fonte**: Assistente 03 durante implementação
**Finalidade**: registrar descobertas operacionais que afetam Epic 02+ pra próximos implementadores não redescobrirem.

---

## 1. sqlite-vec `vec0` não aceita `INSERT OR REPLACE`

**Problema encontrado**: O padrão SQL comum `INSERT OR REPLACE INTO vec_notes(note_id, embedding) VALUES (?, ?)` não funciona em virtual tables `vec0`. A biblioteca requer delete explícito antes de re-insert.

**Solução adotada no core/scanner.py**:
```python
cursor.execute("DELETE FROM vec_notes WHERE note_id = ?", (note_id,))
cursor.execute("INSERT INTO vec_notes(note_id, embedding) VALUES (?, vec_f32(?))", (note_id, blob))
```

**Impacto downstream**:
- Epic 04 (organizer) e Epic 05 (expand): quando re-embeddarem notas modificadas, seguir mesmo padrão
- Epic 06 (pulse): se houver re-ranking que atualize vetores, idem
- Test coverage: Agente 03 adicionou teste explícito validando upsert correto

---

## 2. Calibração pt-br de embeddings: separação absoluta, não threshold fixo

**Problema encontrado**: Teste inicial de S04 esperava `cos > 0.3` para relacionadas e `cos < 0.1` para não-relacionadas. Em pt-br real com Model2Vec static, o floor é mais alto que o esperado — notas totalmente aleatórias ainda dão `cos ~0.05-0.15`.

**Solução adotada**: Teste virou medição de **separação absoluta**:
```python
cos_related = cos(embed("alquimia hermetica"), embed("pedra filosofal"))
cos_unrelated = cos(embed("alquimia hermetica"), embed("receita bolo chocolate"))
assert (cos_related - cos_unrelated) > 0.15  # separação mensurável
```

**Impacto downstream**:
- Epic 04/06: ao usar thresholds absolutos configuráveis (`DUPLICATE_MIN_COS=0.70`, `BRIDGE_MIN_COS=0.40`), calibrar com o mesmo padrão — testar separação em conteúdo do Rafael e ajustar se necessário
- Rafael como beta-tester vai ver thresholds em ação no vault real e pode ajustar via env vars

---

## 3. `scipy` adicionado como dependência obrigatória

**Motivo**: `networkx.pagerank(G, alpha=0.85)` usa scipy sparse matrices internamente para performance em grafos grandes. Sem scipy, networkx cai num fallback muito lento (inaceitável pro alvo <3s em 2k nodes).

**Impacto**:
- Stack total: `170 MB + ~30 MB (scipy) = ~200 MB` — ainda dentro do budget de 200 MB declarado no BRIEF §8.1
- pyproject.toml atualizado com `scipy>=1.13.0`

**Alternativa considerada e rejeitada**: implementar PageRank manualmente sem networkx. Descartado porque networkx já oferece várias métricas de grafo que Epic 04 (organizer) e 06 (pulse) vão precisar — custo marginal de ter scipy é aceitável vs reimplementar tudo.

---

## 4. `core/config.py` stub criado (antecipando Epic 05/06)

**Motivo**: durante wave 5, necessidade de centralizar config surgiu — `core/graph.py` precisava decidir se betweenness é opt-in via env. Em vez de espalhar `os.getenv()` pelo core, criado módulo único.

**Estado atual**: stub mínimo, com helpers `get_bool_env`, `get_float_env`. Epic 05/06 vão expandir com os thresholds de similaridade (`BRIDGE_MIN_COS`, `DUPLICATE_MIN_COS`, `ORPHAN_PROXIMITY_COS`, `PULSE_PORT`, etc.).

**Impacto downstream**: quando Epic 04/05/06 forem implementados, reusar `core.config` em vez de criar módulos separados. Consistência de config em um único lugar.

---

## 5. `core/features.py` com coverage 16% — débito conhecido

**Estado**: module existe com assinaturas mas boa parte não é exercitada pelos testes do Epic 01 diretamente (apenas via integração no scanner).

**Motivo**: Features como `word_count`, `char_count`, `body_hash` já são computadas no parser e ficam disponíveis via `ParsedNote`. O `features.py` hoje tem helpers para: score de densidade de links, ratio frontmatter/body, freshness decay. Esses entram em uso real apenas no Epic 02+ quando suggestions/rankings precisarem.

**Ação**: **não corrigir agora**. Epic 02 (migrate) e Epic 06 (pulse) vão usar esses helpers e gerar coverage naturalmente. Se ao final da Fase 3 coverage ainda estiver < 60%, adicionar testes dedicados como hotfix.

---

## Lições operacionais (não-técnicas)

### `git add -A` em diretório compartilhado é veneno

**Incidente**: durante amendments dos epics mid-Fase 1, o Orquestrador rodou `git add -A` no checkout principal e varreu WIP do Assistente 03 para um commit com mensagem misturada. Nada perdido, mas atribuição ficou errada.

**Regra adotada daqui pra frente**: `git add <arquivo específico>` sempre que múltiplos agentes operam no mesmo diretório. Worktrees em Fase 2 resolvem o problema na prática, mas a disciplina fica.

### Pushback técnico dos executores salva rework

**Observação**: os 4 questionamentos do Assistente 01 (parser contract, delta source, hook latência, privacy do `_INDEX.md`) e os 3 achados do Assistente 02 (thresholds calibrados pra MiniLM errado, API model2vec 0.8.1, L2 norm contract) foram **antes** da execução do Epic 01. Isso evitou:

- Scanner com API errada (emitindo events direto, perdendo desacoplamento)
- Hook que rodaria scan completo em cada edit (inviável <100ms)
- Duplicate detection com threshold 0.92 que nunca disparava
- `_INDEX.md` vazando títulos sensíveis em git commits

**Custo**: ~30 min de orquestração. **Valor**: epic 01 executado com zero rework estrutural.

Regra reforçada: agentes executores devem fazer **prep de Fase 1** lendo o epic deles + BRIEF antes de disparar `/epic-executor`, com tempo dedicado a identificar contratos ambíguos e levantá-los ao orquestrador.

---

## Achados adicionais pós-Epic 02 (obsidian-migrate)

### 6. `scikit-learn>=1.3` — dep faltando no Epic 01

**Gap identificado pelo Agente 03**: o BRIEF §8.1 listava `scikit-learn==1.5.0`, mas `pyproject.toml` do Epic 01 Wave 1 não incluiu. Epic 02 S03 (HDBSCAN + TF-IDF) precisava, adicionado então.

**Ação corretiva futura**: Epic 04 (organizer) e Epic 06 (pulse) já herdam a dep agora disponível. Sem impacto downstream.

### 7. HDBSCAN precisa contraste entre clusters pra dar sinal

**Problema encontrado**: fixtures de teste mono-tema (todas as notas sobre alquimia, por exemplo) fazem HDBSCAN marcar tudo como noise — sem separação de densidade, não há cluster.

**Solução adotada nos testes**: fixtures passaram a ter **≥ 2 temas distintos** (ex: alquimia + programação) pra que HDBSCAN encontre pelo menos 2 clusters. Regra de projeto: quando testar clustering em vault pequeno, garantir heterogeneidade semântica.

**Impacto downstream**: Epic 04 (organizer) vai rodar em vault real do Rafael (mix esoterico+profissional) — naturalmente heterogêneo, não tem esse problema. Epic 06 também.

### 8. `propose` auto-popula áreas pré-decisão

**Decisão arquitetural do Agente 03**: o comando `migrate propose` **cria entries na tabela `areas` imediatamente** com slug vindo do cluster label, mesmo antes do usuário decidir se aceita dominância. Motivo: preview do CLAUDE.md precisa de slug pra renderizar; esperar aprovação humana pra popular gera workflow quebrado.

**Override mechanism**: usuário edita `migration-proposal.md` à mão e `apply` usa `.replace()` no slug literal pra renomear áreas. Isso é idempotente porque área sem `migration_plan` apontando pra ela pode ser deletada em rollback.

**Contrato pra Epic 04**: organizer pode assumir que `areas` está populada após migrate. Se descobrir novo cluster durante re-scan, pode adicionar novas entries — compatível.

### 9. Schema v2: `note_moved` event type

**Migration 002 criada pelo Agente 03**: adicionou `note_moved` ao CHECK constraint de `events.event_type`. Motivo: Wave 6 do Epic 02 (apply migration) precisa emitir este event para auditoria.

**Detalhes técnicos**: SQLite não permite `ALTER TABLE ... ADD CHECK`. Solução: rebuild da tabela (`CREATE TABLE new_events AS SELECT * FROM events`, DROP old, RENAME new). **Foreign keys ON DELETE SET NULL foram preservadas** — Agente 03 validou explicitamente nos testes.

**Regra pra migrations futuras**: toda migration que muda CHECK constraint rebuilda tabela. Preserva FKs + INSERT com `INSERT INTO ... SELECT ...`. Schema version vai pra v3, v4, etc.

**Tests ajustados**: testes Wave 1 que assumiam `schema_version == 1` viraram `schema_version >= 1` pra sobreviver futuras migrations.

### 10. Contratos do `obsidian-migrate` expostos

Epic 04 e 06 podem depender:

- **8 subcomandos funcionais**: `status`, `shadow-scan`, `cluster`, `propose`, `plan`, `approve`, `apply`, `rollback`
- **`migration_plan` auditável**: toda linha tem `status` em `{pending, approved, rejected, applied, rolled_back}` com `decided_at` e `applied_at`. Epic 04 (organizer) pode ler pra ver histórico ou contribuir com novas propostas.
- **`.obsidian-master/marker.json` com `migration_completed: true`**: flag que indica vault pós-migração. Epic 04 e 06 checam antes de propor moves (se completed, só mexe com aprovação fresca).

---

## Métrica final de Fase 2 (até agora)

| Epic | Testes | Coverage core/ | LOC adicionado |
|---|---|---|---|
| 01 (core) | 97 | 84% | ~2000 |
| 02 (migrate) | 112 | — | ~1800 |
| 05 (expand) | 65 | 85% | ~3300 |

**Total em main**: 203 testes rápidos + 6 slow = 209 testes verdes.
