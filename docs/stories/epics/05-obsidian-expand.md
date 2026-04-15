# Epic 05 — `obsidian-expand`

**ID**: `EPIC05-EXPAND`
**Goal**: Skill que gera **notas-ponte** usando APENAS conteúdo existente do vault como fonte (nunca inventa do mundo externo). Preenche gaps semânticos, expande MOCs incompletos, propõe "notas que faltam" entre conceitos existentes. Tudo marcado como `status: draft` e `generated_by: obsidian-expand`.
**Referência técnica**: `docs/BRIEF-v1.md` §6.
**Deps**: Epic 01 completo (core), Epic 04 ideal mas não obrigatório.
**Pontos totais**: 18.

## Stories

| ID | Title | Points | Deps | Area |
|---|---|---|---|---|
| S01 | Skill shell + SKILL.md + CLI | 2 | EPIC01 | shell |
| S02 | KNN engine (top-k similar notes) | 3 | EPIC01-S04 | knn |
| S03 | Gap detection (semântico + grafo) | 5 | S02 | gaps |
| S04 | Note generation com prompt restrito ao vault | 5 | S03 | generation |
| S05 | Frontmatter auto + integração com librarian | 3 | S04 | integration |

---

### Story S01 — Skill shell + SKILL.md + CLI

**Descrição**: Criar `skills/obsidian-expand/SKILL.md` pt-br, acionada por "expande meu vault", "cria notas que faltam entre X e Y", "preenche gaps". CLI:

- `expand bridges [--topic TOPIC]` — encontra pontes semânticas sem link direto
- `expand moc [--moc-path PATH]` — expande um MOC específico
- `expand gaps [--area AREA]` — detecta gaps em uma área
- `expand from [--note PATH]` — expande a partir de uma nota seed

**Critérios de aceitação**:
- SKILL.md com exemplos de uso reais
- CLI aceita seeds (nota, MOC, tópico, área)
- `--dry-run` mostra propostas sem escrever

---

### Story S02 — KNN engine (top-k similar notes)

**Descrição**: Implementar `expand.py:knn(note_id, k=20) -> list[tuple[int, float]]`. Usa `sqlite-vec MATCH`:

```sql
SELECT note_id, distance FROM vec_notes
WHERE embedding MATCH vec_f32(?)
ORDER BY distance LIMIT ?
```

Filtra notas com `status='arquivado'` e `deleted_at IS NOT NULL`. Retorna IDs + distância coseno.

**Critérios de aceitação**:
- `knn` retorna exatamente `k` vizinhos (ou menos se vault pequeno)
- Tempo: < 100ms para k=20 em vault de 5k notas
- Exclui a própria nota da lista
- Teste unitário com vault fixture: vizinhos são semanticamente relacionados

---

### Story S03 — Gap detection (semântico + grafo)

**Descrição**: Detecta "pontes faltando" combinando sinais:

1. **Pontes semânticas**: par (A, B) com cos > 0.7, sem link direto, nem compartilham um terceiro nó conectado a ambos → candidato a "nota-ponte entre A e B"
2. **MOC incompleto**: MOC X com `out_degree=5` mas cluster do X tem 30 notas → cluster tem "notas órfãs que o MOC deveria referenciar"
3. **Conceito subjacente**: grupo de 4+ notas mencionando mesmo conceito no body (via embedding proximity) mas nenhuma é sobre esse conceito → falta a nota de referência

Grava candidatos em `suggestions_cache(kind='bridge'|'moc_expand'|'reference_missing')` com `reasoning` explícito.

**Critérios de aceitação**:
- Detecta pelo menos 1 caso de cada tipo em fixture com oportunidades intencionais
- Reasoning é humano-legível ("[[Hermetismo]] e [[Alquimia]] têm cos=0.87, 0 links, compartilham 5 termos-chave")
- Não gera spam (limite 20 propostas por run)

---

### Story S04 — Note generation com prompt restrito ao vault

**Descrição**: Implementar geração de `.md` draft para cada sugestão aprovada. Crítico: **a IA usada deve ser instruída a usar apenas o conteúdo do vault como fonte**, nunca inventar do mundo externo.

Arquitetura:

1. CLI `expand generate --suggestion-id N` invoca Claude (via SDK ou skill) com prompt:
   ```
   Você está gerando uma nota de Obsidian. Use APENAS o conteúdo das
   notas-fonte abaixo. NÃO invente fatos. NÃO cite fontes externas.
   Se não houver informação suficiente, diga isso explicitamente.

   Notas-fonte:
   <conteúdo das 3-5 notas mais relevantes via KNN>

   Tarefa: <da suggestion — ex: "crie uma nota que faça a ponte entre A e B">
   ```
2. Output: `.md` em pasta apropriada (pasta da primeira nota-fonte ou MOC)
3. Frontmatter automático (S05)

**Critérios de aceitação**:
- Nota gerada contém wikilinks pras notas-fonte (referência explícita)
- Frase "não há informação suficiente no vault" é possível (testado com prompt deliberadamente vago)
- Nota nunca contém fato fora do que as notas-fonte disseram (spot-check manual em 5 gerações)
- `--dry-run` mostra o prompt e sai sem invocar LLM (economia)

---

### Story S05 — Frontmatter auto + integração com librarian

**Descrição**: Toda nota gerada recebe frontmatter:

```yaml
---
created: YYYY-MM-DD
updated: YYYY-MM-DD
area: <inferida da pasta>
type: nota | moc
status: draft
generated_by: obsidian-expand
source: <suggestion_id>
tags: [draft, generated]
aliases: []
---
```

Após escrita, dispara librarian (`obsidian-master sync --vault PATH`) pra indexar a nova nota no DB. Librarian também adiciona link estrutural pro MOC da área.

**Critérios de aceitação**:
- Nota gerada aparece no próximo scan do librarian
- `status: draft` e `generated_by` visíveis no dashboard de review
- Usuário pode promover pra `status: ativo` manualmente (removendo o tag `generated`)
- E2E: gap detectado → aprovar → gerar → librarian indexa → aparece no vault pronta pra edição
