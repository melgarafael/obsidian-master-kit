# Epic 03 — Estender `obsidian-librarian` para o DB

**ID**: `EPIC03-LIBRARIAN`
**Goal**: Trazer o librarian existente (v0.1.1) pra dentro do novo sistema. Toda sync passa a escrever em `events`. `_INDEX.md` passa a consultar o DB em vez de regex do filesystem. Mantém retro-compatibilidade com vaults v0.1.1 existentes.
**Referência técnica**: `docs/BRIEF-v1.md` §6.
**Deps**: Epic 01 completo.
**Bloqueia**: apenas leituras do pulse (Epic 06).
**Pontos totais**: 13.

## Stories

| ID | Title | Points | Deps | Area |
|---|---|---|---|---|
| S01 | Reusar `core.parser` em `update_index.py` | 2 | EPIC01-S02 | refactor |
| S02 | Escrever `events` em toda scan run | 3 | EPIC01-S01 | events |
| S03 | `_INDEX.md` via DB (não via regex direto) | 3 | S02 | index |
| S04 | Path de migração vaults v0.1.1 → v1.0 | 3 | S03 | migration |
| S05 | Hook PostToolUse continua funcional | 2 | S02 | hook |

---

### Story S01 — Reusar `core.parser` em `update_index.py`

**Descrição**: Substituir o parser interno de `skills/obsidian-librarian/scripts/update_index.py` por `core.parser.parse_markdown`. Manter API pública do script inalterada (output JSON no stdout + reescrita de `_INDEX.md`). Remover código duplicado.

**Critérios de aceitação**:
- `update_index.py` funciona exatamente igual pra vaults existentes v0.1.1 (output JSON bit-idêntico em casos sem features novas)
- Código duplicado de parsing removido (revisão por diff)
- Testes do librarian antigo (se existirem) continuam passando

---

### Story S02 — Escrever `events` em toda scan run

**Descrição**: Cada vez que `update_index.py` roda, abre conexão via `core.db.connect`, chama `core.scanner.scan(conn, vault)` e consome o `ScanReport` retornado:

```python
report = core.scanner.scan(conn, vault_path, embedder)

# Event do run em si
emit_event(conn, event_type='scan_run', metadata={'triggered_by': trigger})

# Per-note events traduzidos do delta explícito
for change in report.changes:
    if change.status == 'created':
        emit_event(conn, event_type='note_created', note_id=change.note_id)
    elif change.status == 'updated':
        emit_event(conn, event_type='note_updated', note_id=change.note_id)
    elif change.status == 'deleted':
        emit_event(conn, event_type='note_deleted', note_id=change.note_id)
    # link diffs do próprio change
    for added in change.links_diff.get('added', []):
        emit_event(conn, event_type='link_added', note_id=change.note_id, metadata={'to': added})
    for removed in change.links_diff.get('removed', []):
        emit_event(conn, event_type='link_removed', note_id=change.note_id, metadata={'to': removed})
```

**Dedup app-level** (em `emit_event`): antes de inserir, `SELECT MAX(ts) FROM events WHERE note_id=? AND event_type=?`. Se `now - max_ts < 60s`, skip. Evita UNIQUE constraint com rounding de timestamp, que é frágil com timezone.

**Critérios de aceitação**:
- Após `sync`, SELECT events WHERE event_type='scan_run' retorna 1 linha nova
- Adicionar nota nova gera 1 evento `note_created`
- Deletar nota gera 1 evento `note_deleted` + `deleted_at` atualizado em `notes`
- Hook rodando 3× em 10s cria apenas 1 `scan_run` (dedup app-level)
- Link adicionado entre A e B gera event `link_added` para `note_id=A` com `metadata.to='B'`

---

### Story S03 — `_INDEX.md` via DB (não via regex direto)

**Descrição**: Refatorar a geração do `_INDEX.md` pra consultar o DB em vez de varrer arquivos. Estrutura do index atualizada com filtros de privacidade (`_INDEX.md` é plaintext na raiz do vault — potencialmente git-commitado, portanto não vaza títulos sensíveis):

- **Contagem por área** (agregada, sem vazamento): `SELECT a.label, COUNT(n.id) FROM notes n JOIN areas a ON n.area_id=a.id WHERE n.deleted_at IS NULL GROUP BY a.id`
- **Últimas 10 adições** (com título — exclui sensitive): `SELECT title, path FROM notes WHERE sensitive=0 AND deleted_at IS NULL ORDER BY mtime DESC LIMIT 10`
- **MOCs ativos** (estruturais, incluídos): filtro `path LIKE '%_MOC.md' OR pagerank > threshold`
- **Notas órfãs** (sem wiki-link de **saída**, exclui sensitive): 
  ```sql
  SELECT n.id, n.path FROM notes n
  LEFT JOIN links l ON l.from_note_id = n.id
  WHERE l.id IS NULL
    AND n.deleted_at IS NULL
    AND n.sensitive = 0
    AND n.path NOT LIKE '%/_templates/%'
    AND n.path NOT LIKE '%_MOC.md'
  ```
  Semântica de "órfã" consistente com librarian v0.1.1 atual = sem link de saída.
- **Projetos ativos**: exclui se a área do projeto tem `sensitive=1`

Notas sensitive ainda aparecem em contagens agregadas mas nunca com título visível. Relatório em `_INDEX.md` pode anotar: *"Órfãs: 12 (3 sensíveis omitidas)"*.

DB vira fonte de verdade pras contagens; filesystem é fonte de verdade pra conteúdo.

**Critérios de aceitação**:
- `_INDEX.md` renderizado via DB é visualmente idêntico ao anterior em vaults sem notas sensíveis (diff manual)
- Notas em pastas blacklisted (`sensitive=1`) não aparecem por título em nenhuma listagem
- Performance: renderização em < 200ms para vault de 2000 notas
- Contagens agregadas batem com `find . -name '*.md' | wc -l` do filesystem (tolerância zero)
- Teste: criar nota em `00 - Pessoal/Journaling/` com `sensitive=1`, regenerar index, verificar que título não aparece mas contagem sobe

---

### Story S04 — Path de migração vaults v0.1.1 → v1.0

**Descrição**: Vaults que instalaram v0.1.1 têm `.obsidian-master/marker.json` mas não têm DB. Script `obsidian-librarian upgrade` que:

1. Detecta ausência de `db.sqlite`
2. Roda `core.db.connect` (cria schema)
3. Roda `core.scanner.scan` completo (popula `notes`, `links`, eventos iniciais)
4. Atualiza marker com `kit_version=1.0` e `schema_version=1`
5. Preserva `CLAUDE.md` existente (humano edita)

**Critérios de aceitação**:
- Upgrade é idempotente (rodar 2× não duplica dados)
- Vault v0.1.1 real (simulado com fixture) upgrada com sucesso
- CLAUDE.md do usuário não é sobrescrito

---

### Story S05 — Hook PostToolUse continua funcional

**Descrição**: Validar que `hooks/post-vault-write.py` continua disparando o librarian estendido corretamente. Garantir que o hook não adiciona latência perceptível (< 100ms por Write) já que agora abre conexão SQLite.

**Critérios de aceitação**:
- Escrita em nota → hook dispara → librarian roda → events atualizados
- Hook não bloqueia a conversa do usuário (assíncrono ou < 100ms)
- Teste manual: edita nota, verifica que `events` tem linha nova
