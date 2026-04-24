# Roadmap — `obsidian-master-kit`

## Skills entregues

### v1.0 (2026-04-21)
- `obsidian-init`, `obsidian-librarian`, `obsidian-expand`, `obsidian-organizer`, `obsidian-migrate`, `obsidian-pulse`

### v1.1 (2026-04-24)
- `obsidian-forge` — plano de negócio + scanner de contexto + dashboard executor (3 sub-comandos)

---

Este documento lista as skills previstas para versões futuras. O MVP (v0.1.0-mvp)
entrega apenas `obsidian-init` e `obsidian-librarian`. As skills abaixo são aditivas:
cada uma depende do bibliotecário já existir, mas não altera sua superfície.

## Princípio de extensibilidade

Toda skill futura que escreve no vault deve:
1. Ler o `CLAUDE.md` do vault antes de escrever (doutrina é soberana).
2. Gravar suas notas seguindo o schema de frontmatter e hierarquia de tags.
3. Invocar `obsidian-librarian` ao final (ou deixar o hook `PostToolUse` fazê-lo).
4. Nunca editar `CLAUDE.md` do vault — território humano.

## Skills v0.2+ previstas

### `obsidian-daily-note`
- **O que faz**: cria/abre a nota diária no fuso e idioma do owner, com prompt curto
  de reflexão no topo (baseado no tom definido na entrevista do init).
- **Depende do librarian**: usa o schema `type: diario` e grava em
  `00 - Pessoal/Diario/YYYY-MM-DD.md`.
- **Complexidade**: baixa.

### `obsidian-moc-builder`
- **O que faz**: detecta clusters de notas órfãs (sem link pra MOC) via similaridade
  de tags + co-ocorrência de termos, e propõe um novo MOC cobrindo o cluster.
- **Depende do librarian**: reusa o scanner de órfãs já presente no `update_index.py`.
- **Complexidade**: média.

### `obsidian-search`
- **O que faz**: busca semântica local no vault. Wrapper em Omnisearch (plugin do
  Obsidian) quando disponível, com fallback para grep estruturado por frontmatter.
- **Depende do librarian**: não escreve, só lê. Mas usa o índice do `_INDEX.md` como
  ponto de partida para boost de relevância.
- **Complexidade**: média.

### `obsidian-linker`
- **O que faz**: sugere backlinks automáticos para uma nota recém-escrita, baseado em
  co-ocorrência de termos significativos com notas existentes.
- **Depende do librarian**: chamado no fluxo normal pós-escrita. Propõe, não impõe.
- **Complexidade**: média.

### `obsidian-archiver`
- **O que faz**: identifica notas com `status: ativo` cujo `updated` é antigo (limiar
  configurável, ex: 90 dias) e move para `Arquivadas/` da respectiva área.
- **Depende do librarian**: usa o schema de status e atualiza o `_INDEX.md`.
- **Complexidade**: baixa.

### `obsidian-graph-audit`
- **O que faz**: identifica ilhas no grafo do vault (clusters de notas só linkadas
  entre si, sem ponte para o resto) e sugere notas-ponte.
- **Depende do librarian**: reusa o scanner de links.
- **Complexidade**: média-alta.

### `obsidian-export`
- **O que faz**: exporta uma área/projeto como bundle de markdown (zip ou pasta),
  pronto para alimentar contexto de IA externa, com um índice agregado.
- **Depende do librarian**: usa o schema de areas/types para filtrar.
- **Complexidade**: baixa.

## Ideias que precisam amadurecer antes de virar skill

- Integração com Templater para notas que mudam com o tempo (ex: review semanal).
- Integração com Dataview para queries dinâmicas nos MOCs (hoje os MOCs são estáticos
  para não depender de plugin do Obsidian — v1.x pode adicionar variante Dataview).
- Sincronização bidirecional com um grafo externo (Logseq, Roam) — exploratório.
- Versionamento semântico por nota com rollback ponto-a-ponto.

## Não vai ser feito (fora de escopo)

- Substituir Obsidian por um editor próprio.
- Hospedar/sincronizar o vault em nuvem (isso é Obsidian Sync ou Syncthing).
- Mobile nativo.
