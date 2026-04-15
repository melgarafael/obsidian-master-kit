---
name: obsidian-librarian
description: Esta skill deve ser usada sempre que alguma skill (ou humano) escrever, editar ou adicionar notas dentro de um vault obsidian-master-kit. Tambem e invocada automaticamente pelo hook PostToolUse do plugin depois de qualquer Write/Edit em paths dentro de um vault. Le o CLAUDE.md do vault como memoria, valida o frontmatter das notas recem-modificadas, normaliza tags, garante wiki-link para o MOC da area, reescreve o _INDEX.md vivo e reporta desvios que exigem decisao humana. NAO deleta conteudo humano. NAO edita o CLAUDE.md.
---

# obsidian-librarian

Curador automatico do vault. Roda apos qualquer escrita, le a doutrina (`CLAUDE.md`
do vault), valida o que foi escrito, corrige o que e deterministico, e mantem o
`_INDEX.md` vivo.

## Quando usar

- Apos qualquer `Write` ou `Edit` em path dentro de um vault-master (disparo
  automatico via hook `post-vault-write.sh`).
- Quando o usuario invoca `/obsidian-master-kit:sync`.
- Quando o usuario diz "atualiza o indice", "roda o bibliotecario", "sincroniza o
  vault".

## Quando **nao** usar

- Em paths fora de um vault-master (o hook protege, mas valide antes por seguranca).
- Se a ultima invocacao foi ha menos de 5 segundos — dedupe para evitar loops.

## Fluxo canonico

### Passo 1: Detecte o vault

Caminhe para cima a partir do arquivo modificado procurando `.obsidian-master/marker.json`.
Esse arquivo marca a raiz do vault. Se nao achar, aborta silenciosamente — nao e
vault-master.

### Passo 2: Leia a doutrina

Leia `<vault-root>/CLAUDE.md` inteiro. Dali voce extrai:

- Schema de frontmatter (campos obrigatorios, valores validos)
- Schema de tags (hierarquia canonica)
- Mapa de pastas (qual area cada pasta representa)
- Regras de linking (todo arquivo linka pelo menos para o MOC da area)

Essas sao regras locais do vault — podem divergir do default do kit se o humano
tiver editado.

### Passo 3: Invoque o script de indexacao

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/obsidian-librarian/scripts/update_index.py \
  --vault "<vault-root>" \
  [--since <ISO-timestamp>]
```

O script faz a parte deterministica:
- Walka o vault, le todo `.md`
- Parseia frontmatter (YAML)
- Valida campos obrigatorios (`created`, `updated`, `area`, `type`, `status`, `tags`)
- Normaliza tags (lowercase, sem `#` prefix no frontmatter)
- Atualiza campo `updated` com mtime do arquivo se estiver desatualizado
- Calcula estatisticas: contagem por area, MOCs ativos, notas orfas (sem wiki-link pra
  MOC), ultimas 10 adicoes
- Reescreve `<vault-root>/_INDEX.md`
- Atualiza `<vault-root>/.obsidian-master/last-sync.json`
- Reporta em stdout (JSON) as issues que precisam intervencao humana ou LLM

### Passo 4: Trate as issues reportadas

O script retorna JSON como:

```json
{
  "updated_index": true,
  "notes_scanned": 42,
  "orphans": ["02 - Pesquisas e Estudos/Ativas/Nota Solta.md"],
  "missing_frontmatter_fields": [
    {"file": "01 - Profissional/Projetos/X.md", "missing": ["status"]}
  ],
  "unknown_tags": [
    {"file": "02 - Pesquisas e Estudos/Ativas/Y.md", "tags": ["random/custom"]}
  ],
  "area_folder_mismatch": [],
  "last_sync": "2026-04-15T14:20:00"
}
```

Para cada categoria:

- **orphans**: consulte as referencias (em `references/linking-rules.md`) sobre como
  sugerir um MOC. Adicione linha em `## Relacionado` da nota apontando para o MOC da
  area. Se a nota nao cabe em nenhuma area existente, escale para o usuario.
- **missing_frontmatter_fields**: adicione os campos faltando com defaults razoaveis:
  - `status` ausente → `draft`
  - `tags` ausente → `[]`
  - `updated` ausente → data de hoje (mas o script ja faz isso)
  - **Nunca** chute `area` ou `type` — escale pro usuario.
- **unknown_tags**: compare com o schema em `CLAUDE.md` do vault. Se a tag nao bate,
  sugira a tag canonica mais proxima em 1 comentario para o usuario; nao altere sem
  permissao (tags podem ter significado semantico que o humano escolheu).
- **area_folder_mismatch**: a nota tem `area: pesquisa` mas esta em `01 - Profissional/`.
  **Nunca mova sem perguntar** — reporte ao usuario.

### Passo 5: Reporte curto ao usuario

Depois que o script rodou e voce tratou as issues, imprima 1 bloco conciso:

```
Librarian synced:
- 42 notas escaneadas, _INDEX.md atualizado
- 2 orfas linkadas ao MOC apropriado
- 1 frontmatter preenchido (status: draft)
- 1 tag desconhecida reportada (esperando sua decisao)
```

Mais que isso e ruido — a pessoa quer saber que o vault esta ok, nao um relatorio
de auditoria.

## Guardrails — regras inviolaveis

1. **Nunca deleta conteudo humano.** Nem 1 linha, nem 1 palavra.
2. **Nunca edita o `CLAUDE.md` do vault.** Territorio humano.
3. **Nunca move arquivos entre areas sem confirmacao.** Mismatch de area e um
   sinalizador, nao uma licenca pra mover.
4. **Nunca chuta campos semanticos** (`area`, `type`, `aliases`, conteudo do corpo).
5. Se o script falha, reporte o erro e pare. Nao tente "consertar" o vault na
   marra — prefere halt a corromper.

## Referencias bundled

- `references/obsidian-conventions.md` — convencoes oficiais do Obsidian destiladas
- `references/frontmatter-schema.md` — schema canonico do kit (fonte de verdade
  quando o vault nao tem override)
- `references/linking-rules.md` — regras de wiki-link, backlinks, aliases, MOCs
