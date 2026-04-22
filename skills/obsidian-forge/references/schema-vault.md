# Schema das notas em `04 - Negocio/`

7 tipos. Frontmatter YAML em todos.

## 1. plano (1 — `_plano.md`)

Campos: `tipo`, `ciclo`, `produto`, `problema`, `pessoa`,
`precificacao.valor_unitario`, `precificacao.base.*`, `status`, `protected: true`.

## 2. metas (1 — `_metas.md`)

Campos: `tipo`, `ciclo`, `objetivo.{titulo, valor_alvo, valor_atual, prazo}`,
`funil[].{etapa, alvo, atual}`, `protected: true`.

Etapas fixas do funil: `clientes`, `reunioes`, `leads`, `alcance`.

## 3. contexto (1 — `_contexto.md`)

Agregado do scanner. Campos: `tipo`, `atualizado`, `projetos_ativos`.

## 4. config_scan (1 — `_config-scan.md`)

Config do scanner. Campos: `pastas_observadas`, `janela_ativo_dias`,
`limite_profundidade`, `hook_sessionstart_ativo`, `timeout_hook_s`, `ignore`.

## 5. contexto_projeto (N — `contexto/<slug>.md`)

1 por projeto ativo. Campos: `tipo`, `nome`, `caminho`, `stack`, `status`,
`ultimo_commit`, `atualizado`.

## 6. progresso (N — `progresso/YYYY-MM-DD.md`)

1 por dia. Campos: `tipo`, `data`, `eventos`.
Corpo: linhas `- HH:MM — tipo_evento (detalhes)`.

Tipos válidos: `lead_captado`, `reuniao_realizada`, `cliente_fechado`,
`conteudo_publicado`, `alcance_manual`.

## 7. acao (7 fixos — `acoes/XX-<slug>.md`)

Campos: `tipo`, `slug`, `ordem`, `titulo`, `status`, `tarefas_totais`,
`tarefas_feitas`, `atualizado`.

Status: `pendente` | `em_andamento` | `concluido`.
