# Regras de Linking — `obsidian-librarian`

Quando e como criar wiki-links durante a curadoria.

## Princípio central

Toda nota tem **pelo menos 1 wiki-link de saída** — tipicamente para o `_MOC.md` da
sua área. Isso impede que notas fiquem órfãs no grafo.

## Decisão: qual MOC linkar

Use a `area` do frontmatter para mapear:

| `area:` | MOC alvo |
|---|---|
| `pessoal` | `[[00 - Pessoal/_MOC\|MOC Pessoal]]` |
| `profissional` | `[[01 - Profissional/_MOC\|MOC Profissional]]` |
| `pesquisa` | `[[02 - Pesquisas e Estudos/_MOC\|MOC Pesquisas e Estudos]]` |
| `ai-memory` | `[[03 - Memoria da IA/_MOC\|MOC Memória da IA]]` |

Quando a nota está em uma sub-área (`Projetos/`, `Diario/`, `Bibliotecas/`, etc.),
prefira linkar ao MOC da sub-área em vez do MOC da área. Ex: uma nota em
`00 - Pessoal/Diario/2026-04-15.md` deve linkar para `[[Diario/_MOC|MOC Diário]]`,
não para o MOC Pessoal root.

## Onde adicionar o link

Se a nota **não tem link nenhum para MOC** e o bibliotecário decide adicionar:

- Procure uma seção `## Relacionado` no footer.
- Se existir, adicione o wiki-link como item de lista.
- Se não existir, crie a seção no final do arquivo com 1 item.

```markdown
## Relacionado

- [[Diario/_MOC|MOC Diário]]
```

**Nunca** adicione no topo ou no meio do conteúdo — o link estrutural mora no footer.

## Backlinks explícitos: não fazer

Não crie listas manuais de "notas que linkam pra mim". O Obsidian mostra isso no painel
de backlinks nativamente. O único link estrutural explícito é o para o MOC.

## Aliases e wiki-links

Se a nota tem aliases (`aliases: [X, Y]` no frontmatter), outras notas podem usar
`[[X]]` ou `[[Y]]` para linkar. O Obsidian resolve automaticamente.

O librarian **nunca** adiciona aliases sozinho — aliases são decisão do humano.

## Linking para sub-MOCs vs MOCs root

Escala de especificidade:

1. Mais específico é melhor. Prefira sub-MOC sobre MOC de área.
2. MOC de área sobre nada.

Exemplo: uma nota `01 - Profissional/Projetos/Migrar Backend.md` linka para:
- `[[Projetos/_MOC|MOC Projetos]]` (bom — sub-MOC)
- Não precisa linkar para `[[01 - Profissional/_MOC|MOC Profissional]]` também — o
  sub-MOC já linka pra lá.

## Quando uma nota **não** cabe em nenhuma área

Se o `area:` está vazio ou com valor não-canônico, **não invente**. Escale:

> "Nota `X.md` não tem area válida. As opções canônicas são: pessoal, profissional,
> pesquisa, ai-memory. Qual se aplica?"

## Sugestão de wiki-links no corpo (opcional — v0.2)

No MVP, o librarian **não** sugere wiki-links dentro do corpo da nota (ex: identificar
"DDD" e sugerir `[[Domain-Driven Design]]`). Isso fica para a skill futura
`obsidian-linker`. Por quê:

- Requer análise semântica — menos determinístico.
- Risco de poluir notas com links falsos positivos.
- Melhor feito com confirmação explícita do usuário.

## Caso especial: notas geradas pela IA

Skills que escrevem pesquisa/memória devem já incluir wiki-links relevantes no corpo
(ex: uma nota de pesquisa sobre Rust linka `[[Rust]]`, `[[Memory Safety]]`, etc.). O
librarian não muda o corpo — só valida que existe pelo menos 1 link estrutural (pra
MOC) e adiciona se faltar.
