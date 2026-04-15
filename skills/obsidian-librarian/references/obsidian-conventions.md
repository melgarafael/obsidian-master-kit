# Convenções do Obsidian — referência destilada

Extrato das convenções oficiais do Obsidian que o `obsidian-librarian` precisa
respeitar. Para a documentação completa, ver https://help.obsidian.md.

## Wiki-links

Formato: `[[Nome da Nota]]` — resolve para o arquivo `Nome da Nota.md` em qualquer
pasta do vault.

Variantes:

- `[[Nome da Nota|Texto Alternativo]]` — display com alias sem criar alias no
  frontmatter.
- `[[Nome da Nota#Seção]]` — link para uma seção específica (heading `##`).
- `[[Nome da Nota^block-id]]` — link para um bloco específico (referência por âncora).
- `[[../Pasta/Nota]]` — link relativo explícito (raro; prefira links por nome).

**Resolução**: o Obsidian resolve `[[Nome]]` pelo nome do arquivo em qualquer parte
do vault. Se houver ambiguidade, usa match exato primeiro.

## Backlinks

Automáticos. Painel de backlinks mostra todas as notas que linkam para a atual.

**Nunca mantenha listas manuais de "notas relacionadas"** — o painel já mostra.
O exceção: link para o MOC da área é explícito (a doutrina exige) e fica em
`## Relacionado` no footer.

## Properties (frontmatter)

YAML no topo do arquivo entre `---`. Obsidian parseia e expõe como filtro nativo
desde v1.4.

Tipos suportados nativamente:

- `text` — string única
- `list` — array de strings (usado para `tags`, `aliases`)
- `number`
- `checkbox` — boolean
- `date` — ISO date
- `datetime` — ISO datetime

Tags podem viver em `tags: []` no frontmatter (sem `#` prefix) OU no corpo (com `#`).
O librarian prefere frontmatter (mais limpo, queryable).

## Tags

- Hierarquicas: `#pai/filho/neto`
- Case-insensitive em buscas, mas convencao e usar lowercase.
- Tag de 1 caractere (ex: `#a`) e valida mas ruim para buscas.
- Em frontmatter: `tags: [pai/filho]` (sem `#`, sem aspas para tags simples).
- No corpo: `#pai/filho` (com `#`).

## Aliases

Em frontmatter:

```yaml
aliases:
  - Nome Alternativo
  - Outro Alias
```

Efeito: `[[Nome Alternativo]]` resolve para este arquivo. Quick-switcher tambem
encontra pelo alias.

## Maps of Content (MOC)

Nao e um conceito nativo do Obsidian — e uma convencao da comunidade. No
`obsidian-master-kit` todo diretorio importante tem um `_MOC.md` que serve como:

- Indice navegavel da area
- Ancora para novas notas dessa area linkarem
- Ponto de contato entre sub-areas

Convencao de nome: `_MOC.md` (o underscore garante que aparece no topo da listagem
alfabetica).

## Canvas, Dataview, Templater

Sao **plugins de terceiros**. O MVP do kit **nao** depende deles.

- Canvas: ja vem no core desde v1.1. Pode ser adicionado em skills futuras.
- Dataview: plugin externo. Queries dinamicas. Futuro — ver roadmap.
- Templater: plugin externo. Templates com logica. Futuro — ver roadmap.

## Search

Operadores uteis:

- `tag:#pesquisa/ativa` — busca por tag
- `path:"02 - Pesquisas"` — busca por path
- `file:md` — limita a markdown
- `["frase exata"]` — frase exata
- `["termo" OR "outro"]` — booleano

O `obsidian-librarian` nao precisa disso (ele walka o filesystem direto), mas
queries sugeridas no `_INDEX.md` podem usar essa sintaxe para a pessoa.

## Estrutura de pastas vs tags

Regra de dedo:

- **Pasta** responde "o que isso e" (substantivo).
- **Tag** responde "qual estado/qualidade" (adjetivo ou status).

Nao duplique pasta e tag. Se a nota esta em `02 - Pesquisas e Estudos/Ativas/`, a tag
`#pesquisa/ativa` e redundante. Use tags so quando agregam informacao ortogonal a
pasta (ex: nota em pasta de projeto com caracter de referencia).

## Graph view

O grafo do Obsidian mostra notas como nos, links como arestas. Ilhas (clusters
desconectados do nucleo) sao um sinal de problema — a skill futura
`obsidian-graph-audit` lida com isso. No MVP, o librarian so reporta notas orfas
(sem nenhum wiki-link saindo).

## Arquivos binarios no vault

Obsidian suporta PNG, JPG, PDF etc. embutidos com `![[arquivo.pdf]]`. Nao mexa
com binarios — o librarian lida so com `.md`.

## Templates nativos

Obsidian tem "Templates" plugin core que insere conteudo de um arquivo em
outro. O kit traz `_templates/` em cada area e o usuario pode apontar o plugin
Templates do Obsidian pra essas pastas. Nao requer config automatica no MVP.
