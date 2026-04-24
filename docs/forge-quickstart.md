# forge — guia rápido (5 min)

## Pré-requisito

Vault criado via `obsidian-init`. A área `04 - Negocio` é criada
automaticamente quando você roda `forge-plan` ou `forge-scan --init`.

## 1. Fazer o plano

```
/obsidian-master-kit:forge-plan
```

~15 min de entrevista conduzida pelo Claude Code:

1. **3 Ps** — Produto, Problema, Pessoa (uma frase + prosa)
2. **Precificação** — valor unitário + 4 bases (resultado, tempo, esforço, produção)
3. **Matemática do Resultado** — objetivo → funil (clientes → reuniões → leads → alcance)
4. **7 Ações Macro** — arquivos em `acoes/01..07`, criados automaticamente

Gera: `04 - Negocio/_plano.md`, `_metas.md`, 7 `acoes/*.md`.

## 2. Escanear projetos

```
/obsidian-master-kit:forge-scan
```

Primeira vez pergunta quais pastas vigiar. Gera notas atômicas em
`04 - Negocio/contexto/<slug>.md` + agregado em `_contexto.md`.

## 3. Abrir o painel

```
/obsidian-master-kit:forge-dash
```

Abre http://localhost:4712 no Chrome/Arc/Edge/Brave. Clique
"Escolher meu vault Obsidian" (primeira vez).

Cinco seções:

- 3 Ps
- Matemática do resultado (barras de progresso)
- 7 Ações macro (checkbox marca tarefa → atualiza status)
- Próximo passo sugerido (determinístico)
- Contexto vivo (projetos ativos)

Botão **+ registrar progresso**: abre modal → tipo + quantidade → escreve
evento em `progresso/YYYY-MM-DD.md` → recomputa `_metas.md` → barras sobem.

## Eventos de progresso

- `lead_captado` — funil leads (+1)
- `reuniao_realizada` — funil reuniões (+1)
- `cliente_fechado` — funil clientes (+1) + valor_total (valor do evento)
- `conteudo_publicado` — funil alcance (+1)
- `alcance_manual` — funil alcance (+quantidade explícita)

## Invariantes

- 100% local. Zero cloud, zero daemon.
- Dashboard: só Chromium (Chrome, Arc, Edge, Brave) pra edição completa.
- `_plano.md` e `_metas.md` têm `protected: true` — só o forge escreve neles.
- Metodologia da aula hardcoded em v1. Extensibilidade em v2+.

## Arquivos no vault após forge-plan

```
04 - Negocio/
├── _plano.md           # 3 Ps + precificação (protegido)
├── _metas.md           # matemática + contadores vivos (protegido)
├── _contexto.md        # agregado do scanner
├── _config-scan.md     # config de pastas vigiadas
├── contexto/           # 1 .md por projeto ativo
├── progresso/          # YYYY-MM-DD.md com eventos
└── acoes/              # 01..07 ações macro
```
