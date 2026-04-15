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

**Descrição**: Cada vez que `update_index.py` roda, abre conexão via `core.db.connect` e escreve:

- `events(event_type='scan_run', metadata={triggered_by: 'hook'|'manual'|'init'})`
- Para cada nota criada/atualizada/deletada detectada: `events(note_created|note_updated|note_deleted, note_id, ts=now)`
- Para cada link adicionado/removido: `events(link_added|link_removed)`

Evento é idempotente: se o mesmo `(note_id, event_type, ts)` já existe no último minuto, não duplica.

**Critérios de aceitação**:
- Após `sync`, SELECT events WHERE event_type='scan_run' retorna 1 linha nova
- Adicionar nota nova gera 1 evento `note_created`
- Deletar nota gera 1 evento `note_deleted` + `deleted_at` atualizado em `notes`
- Hook rodando 3× em 10s cria apenas 1 `scan_run` (dedup)

---

### Story S03 — `_INDEX.md` via DB (não via regex direto)

**Descrição**: Refatorar a geração do `_INDEX.md` pra consultar o DB em vez de varrer arquivos. Estrutura do index atualizada:

- Contagem por área: `SELECT area, COUNT(*) FROM notes GROUP BY area`
- Últimas 10 notas: `ORDER BY mtime DESC LIMIT 10`
- MOCs ativos: `WHERE name LIKE '_MOC%' OR pagerank > threshold`
- Notas órfãs: `LEFT JOIN links ON to_note_id IS NULL AND from_note_id IS NULL`

DB vira fonte de verdade pras contagens; filesystem é fonte de verdade pra conteúdo.

**Critérios de aceitação**:
- `_INDEX.md` renderizado via DB é visualmente idêntico ao anterior (diff manual)
- Performance: renderização em < 200ms para vault de 2000 notas
- Contagens batem com `find . -name '*.md' | wc -l` do filesystem (tolerância zero)

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
