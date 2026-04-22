# Spec — `obsidian-forge` (v1.1 do obsidian-master-kit)

**Data**: 2026-04-22
**Status**: design aprovado, aguarda implementation plan
**Autor**: Rafael Melgaço + Claude
**Precedente descartado**: `obsidian-pulse` (v1.0.0) — stack inchada, UX opaca, user não encontrou utilidade.

---

## 1. Visão

Adicionar uma skill nova (`obsidian-forge`) ao `obsidian-master-kit` que transforma o vault do usuário em um sistema operacional de execução de negócio. Inspirada na metodologia da aula "IA não é um negócio, é uma ferramenta" (3 Ps → Precificação → Matemática do Resultado → Ações Macro), opera em 3 módulos integrados:

1. **Scanner de contexto** — varre pastas informadas pelo user e mapeia projetos ativos como notas atômicas.
2. **Arquiteto de negócio** — conduz entrevista dos 4 passos e gera plano estruturado.
3. **Dashboard executor** — HTML estático local que lê o vault via File System Access API e permite registrar progresso com cliques.

Skill única dentro do kit, com 3 sub-comandos (`forge-scan`, `forge-plan`, `forge-dash`). Stack: Python (pipeline) + HTML estático vanilla (dashboard). Zero cloud, zero daemon, 100% local.

## 2. Decisões de design (aprovadas em brainstorm)

| # | Decisão | Escolha |
|---|---|---|
| Q1 | Reusar/evoluir o pulse? | Não — pulse descartado, zero reaproveitamento. Referência estética é o Tino. |
| Q2 | Granularidade | Skill única dentro do `obsidian-master-kit` com 3 sub-comandos. |
| Q3 | Quando o scanner roda | On-demand + hook `SessionStart` opt-in. |
| Q4 | O que o clique no dashboard faz | Atualiza vault + abre nota no Obsidian via `obsidian://`. |
| Q5 | Stack | Python no pipeline + HTML estático + File System Access API no browser. Sem FastAPI, sem HTMX, sem Node. |
| Q6 | Metodologia | Hardcoded (4 passos da aula). Flexibilização vira v2 se demanda aparecer. |
| Q7 | Escopo v1 | Big bang — os 3 sub-comandos funcionando minimamente no mesmo release. |

## 3. Arquitetura

### 3.1 Estrutura de arquivos da skill

```
skills/obsidian-forge/
├── SKILL.md                         # doutrina (pt-BR)
├── scripts/
│   ├── forge.py                     # CLI entry; despacha sub-comandos
│   ├── scan_context.py              # Módulo 1
│   ├── plan_business.py             # Módulo 2
│   ├── dash_refresh.py              # Módulo 3 (agregação pra CLI)
│   ├── dashboard.html               # single-file dashboard (vanilla JS + CSS)
│   └── templates/
│       ├── plano.md
│       ├── metas.md
│       ├── contexto.md
│       ├── config_scan.md
│       ├── progresso_day.md
│       └── acoes/
│           ├── 01-segundo-cerebro.md
│           ├── 02-plano-de-negocio.md
│           ├── 03-captacao-conteudo.md
│           ├── 04-captacao-venda.md
│           ├── 05-script-reuniao.md
│           ├── 06-processo-entrega.md
│           └── 07-admin-financeiro.md
├── references/
│   ├── metodologia-aula.md          # 4 passos + 7 ações
│   └── schema-vault.md              # schema dos 6 tipos de nota
└── tests/                           # (roots em tests/ do kit)
```

### 3.2 Estrutura nova no vault

```
<vault>/
├── 04 - Negocio/                    # área nova
│   ├── _plano.md                    # 3 Ps + precificação
│   ├── _metas.md                    # funil + contadores vivos
│   ├── _contexto.md                 # agregado do scanner
│   ├── _config-scan.md              # config do scanner
│   ├── .forge-state.json            # estado parcial da entrevista (git-ignored)
│   ├── contexto/
│   │   └── <slug>.md                # 1 por projeto ativo detectado
│   ├── progresso/
│   │   └── YYYY-MM-DD.md            # 1 por dia com eventos
│   └── acoes/
│       ├── 01-segundo-cerebro.md   # os 7 arquivos canônicos
│       ├── 02-plano-de-negocio.md
│       ├── 03-captacao-conteudo.md
│       ├── 04-captacao-venda.md
│       ├── 05-script-reuniao.md
│       ├── 06-processo-entrega.md
│       └── 07-admin-financeiro.md
```

### 3.3 Sub-comandos expostos

| Slash command | Script | Descrição curta |
|---|---|---|
| `/obsidian-master-kit:forge-scan` | `forge.py scan` | Varre pastas e gera notas atômicas de contexto. |
| `/obsidian-master-kit:forge-plan` | `forge.py plan` | Entrevista dos 4 passos; grava `_plano.md`, `_metas.md`, 7 `acoes/*.md`. |
| `/obsidian-master-kit:forge-dash` | `forge.py dash` | Sobe http.server em `localhost:4712`, abre dashboard no browser. |

## 4. Schema do vault (6 tipos de nota)

### 4.1 `_plano.md`

```yaml
---
tipo: plano
atualizado: 2026-04-22
ciclo: 2026-Q2
produto: "<uma frase>"
problema: "<dor específica>"
pessoa: "<ICP: quem, segmento>"
precificacao:
  valor_unitario: 2500
  moeda: BRL
  base:
    resultado_potencial: "..."
    tempo_economizado: "..."
    esforco_reduzido: "..."
    producao_aumentada: "..."
status: ativo       # ativo | pausado | arquivado
---

## 3 Ps
### Produto
### Problema
### Pessoa

## Precificação — raciocínio
```

### 4.2 `_metas.md`

```yaml
---
tipo: metas
atualizado: 2026-04-22
ciclo: 2026-Q2
objetivo:
  titulo: "R$ 10.000 em MRR"
  valor_alvo: 10000
  valor_atual: 0
  moeda: BRL
  prazo: 2026-06-30
funil:
  - etapa: clientes
    alvo: 4
    atual: 0
    valor_unitario: 2500
  - etapa: reunioes
    alvo: 40
    atual: 0
    taxa_conversao: 0.10
  - etapa: leads
    alvo: 400
    atual: 0
    taxa_conversao: 0.10
  - etapa: alcance
    alvo: 4000
    atual: 0
    fonte: trafego_ou_conteudo
---

## Matemática do resultado
(prosa derivando o funil)
```

### 4.3 `_contexto.md`

```yaml
---
tipo: contexto
atualizado: 2026-04-22
fontes:
  - tipo: pasta
    caminho: /Users/rafaelmelgaco/obsidian-master
    ultima_varredura: 2026-04-22T14:30
projetos_ativos: 3
---

## Projetos em construção (links)
## Stack em uso
```

### 4.4 `_config-scan.md`

```yaml
---
tipo: config_scan
pastas_observadas:
  - /Users/rafaelmelgaco/obsidian-master
  - /Users/rafaelmelgaco/tino-ai
janela_ativo_dias: 30
limite_profundidade: 3
hook_sessionstart_ativo: true
timeout_hook_s: 5
ignore:
  - node_modules
  - .venv
  - __pycache__
  - dist
  - build
---
```

### 4.5 `contexto/<slug>.md`

```yaml
---
tipo: contexto_projeto
nome: obsidian-master-kit
caminho: /Users/rafaelmelgaco/obsidian-master
stack: [python]
status: ativo
ultimo_commit: 2026-04-22T14:15:00
ultima_atividade: 2026-04-22
atualizado: 2026-04-22T14:30
---

## O que é
## Stack detectada
## Último commit
## Sinais recentes
```

### 4.6 `progresso/YYYY-MM-DD.md`

```yaml
---
tipo: progresso
data: 2026-04-22
eventos: 3
---

- 14:30 — conteudo_publicado (meta: conteudo_semana → 3/5)
- 15:12 — reuniao_realizada (meta: reunioes → 4/40)
- 18:20 — cliente_fechado (meta: clientes → 1/4, valor: R$ 2.500)
```

**Vocabulário de tipos de evento (hardcoded no v1):**

| Tipo | Mapeia em `_metas.md` | Campos extras |
|---|---|---|
| `lead_captado` | `funil[leads].atual` | — |
| `reuniao_realizada` | `funil[reunioes].atual` | — |
| `cliente_fechado` | `funil[clientes].atual` + `objetivo.valor_atual` | `valor` (opcional, default = `precificacao.valor_unitario`) |
| `conteudo_publicado` | `funil[alcance].atual` (fonte=conteudo) | `canal` (opcional: linkedin/twitter/youtube) |
| `alcance_manual` | `funil[alcance].atual` | `quantidade` (obrigatório) |

Outros tipos ficam em v2. Modal do dashboard oferece apenas essa lista.

### 4.7 `acoes/<slug>.md`

```yaml
---
tipo: acao
slug: captacao-conteudo
ordem: 3
titulo: "Captação via conteúdo"
status: em_andamento    # pendente | em_andamento | concluido
tarefas_totais: 5
tarefas_feitas: 2
atualizado: 2026-04-22
---

## Escopo
## Checklist
- [x] Definir pauta da semana
- [x] Criar 3 posts iniciais
- [ ] Configurar frequência (3x/semana)
- [ ] Validar primeira métrica de alcance
- [ ] Iterar formato baseado em sinal
```

## 5. Módulo 1 — Scanner

### 5.1 O que faz / não faz

| Faz | Não faz |
|---|---|
| Detecta projetos ativos em pastas informadas | Lê código-fonte |
| Lê README, manifestos de stack | Lê `.env`, credenciais, histórico pessoal |
| Lê `git log -1` de cada repo | Monitora janelas em tempo real |
| Detecta arquivos modificados nos últimos 30 dias | Usa permissão de Accessibility do macOS |
| Gera 1 nota atômica por projeto | Escreve em `_plano.md` / `_metas.md` |

### 5.2 Algoritmo (zero LLM)

```
Para cada pasta em pastas_observadas:
    Encontra subpastas com .git/ (profundidade <= 3)
    Para cada repo:
        Se (último commit < janela_ativo_dias) OU (arquivo mtime < 7 dias):
            Ler: README.md (≤500 chars), pyproject.toml/package.json/Cargo.toml, git log -1
            slug = nome da pasta
            Escrever 04 - Negocio/contexto/<slug>.md
Atualizar 04 - Negocio/_contexto.md (agregado)
Invoke obsidian-librarian
```

### 5.3 "Janelas recentes"

- **macOS**: lê `~/Library/Application Support/com.apple.sharedfilelist/RecentDocuments.sfl2` (sem permissão especial), filtra paths dentro de `pastas_observadas`.
- **Linux**: lê `~/.local/share/recently-used.xbel`.
- **Windows**: skip no v1.
- **Fallback universal**: `find <pastas> -type f -mtime -7 -not -path '*/.*'`.

### 5.4 Hook opcional `SessionStart`

Primeira execução pergunta se ativa. Se sim, adiciona via `update-config` skill ao `~/.claude/settings.json`:

```json
{
  "hooks": {
    "SessionStart": [{
      "matcher": "",
      "hooks": [{
        "type": "command",
        "command": "timeout 5 python3 ${CLAUDE_PLUGIN_ROOT}/skills/obsidian-forge/scripts/forge.py scan --silent --quick"
      }]
    }]
  }
}
```

### 5.5 Limites hard-coded

1. Max 30 projetos ativos detectados (trunca o resto, loga).
2. Skip de pasta se `.gitignore` da raiz contém linha `obsidian-exclude`.
3. Ignore patterns embutidos: `.env*`, `*secret*`, `*token*`, `*credentials*`, `.ssh/`.
4. Nunca lê conteúdo fora de README, LICENSE, manifestos de stack, `.git/` metadata.

### 5.6 CLI

```bash
python3 forge.py scan --init                     # primeira vez: entrevista
python3 forge.py scan                            # scan completo, verboso
python3 forge.py scan --silent --quick           # para hook
python3 forge.py scan --add /path/novo-projeto   # adiciona pasta
python3 forge.py scan --mock                     # usa fixtures em tests/
```

## 6. Módulo 2 — Arquiteto

### 6.1 Fluxo da entrevista (4 passos)

```
Passo 1 — 3 Ps         → _plano.md (seções Produto/Problema/Pessoa)
Passo 2 — Precificação → bloco precificacao em _plano.md
Passo 3 — Matemática   → _metas.md (funil validado aritmeticamente)
Passo 4 — Ações Macro  → 7 arquivos acoes/*.md personalizados
```

### 6.2 Contexto como entrada da entrevista

Antes de cada pergunta, script lê `_contexto.md` e `contexto/*.md`, monta bloco de "fatos sobre o user", e o Claude usa pra personalizar. Sem contexto, entrevista é genérica — esse é o diferencial da skill.

### 6.3 Validação aritmética do Passo 3

Antes de gravar `_metas.md`, script checa:

- `objetivo.valor_alvo == funil[clientes].alvo * precificacao.valor_unitario`
- `funil[reunioes].alvo == funil[clientes].alvo / funil[reunioes].taxa_conversao`
- `funil[leads].alvo == funil[reunioes].alvo / funil[leads].taxa_conversao`

Se bate: grava. Se não: pede ajuste no passo específico. **Zero aritmética no LLM.**

### 6.4 Re-run / ciclos

Ao rodar `forge-plan` novamente com `_plano.md` existente:

1. **Refinar plano atual** — revisa passos específicos.
2. **Iniciar novo ciclo** — arquiva plano/metas/acoes em `acoes/_arquivados/<ciclo>/` e reinicia.
3. **Sair** — não-op.

### 6.5 Interruptibilidade

Estado parcial salvo em `04 - Negocio/.forge-state.json` após cada passo completo. Próxima execução detecta e pergunta "retomar do Passo N?".

### 6.6 Personalização dos 7 templates de ação

No Passo 4, Claude recebe prompt: "Dado produto/problema/pessoa/precificação, personalize cada uma das 7 ações macro com tasks específicas pro contexto do user." Ação 01 (segundo cérebro) vem pré-marcada como feita.

### 6.7 CLI

```bash
python3 forge.py plan                  # entrevista completa (retoma se houver estado)
python3 forge.py plan --step 3         # só re-roda passo 3
python3 forge.py plan --new-cycle      # arquiva atual, começa novo
python3 forge.py plan --status         # resumo do plano ativo
```

## 7. Módulo 3 — Dashboard

### 7.1 Stack

Single-file `dashboard.html` (~600-800 linhas, vanilla JS + CSS puro). Zero build, zero dependência runtime. Servido por `python3 -m http.server 4712` em `127.0.0.1`.

### 7.2 Porta

**4712** (vizinha do pulse morto, improvável de colidir, memorável).

### 7.3 File System Access API

- 1ª abertura: botão "Escolher meu vault Obsidian" → `window.showDirectoryPicker()` → user seleciona pasta → browser pede permissão leitura+escrita.
- Handle guardado em IndexedDB. Próximas aberturas só re-pedem permissão (não re-pedem pasta).
- Requer Chromium (Chrome 86+, Edge 86+, Arc, Brave). Firefox/Safari degradam pra read-only.

### 7.4 Layout (scroll único, 5 seções verticais)

```
┌─ Header: ciclo atual, dias até prazo, valor atual/alvo
├─ SEÇÃO 1 — 3 Ps (exibição)
├─ SEÇÃO 2 — Matemática do Resultado (funil com barras)
├─ SEÇÃO 3 — 7 Ações Macro (cards com progresso tarefas_feitas/totais)
├─ SEÇÃO 4 — Próximo Passo Sugerido (determinístico)
└─ SEÇÃO 5 — Contexto Vivo (projetos ativos)
```

Sem tabs. Uma leitura vertical. Paleta Tino-like (warm dark, accent dourado), fontes Newsreader (títulos) + Inter (corpo).

### 7.5 Interações com side-effect (apenas 4)

| Clique | Escreve em | Como |
|---|---|---|
| "+ registrar progresso" | `progresso/YYYY-MM-DD.md` | Modal: tipo + quantidade + nota opcional; JS appenda linha. |
| Checkbox em card de ação | `acoes/<slug>.md` | JS troca `- [ ]` por `- [x]`, incrementa `tarefas_feitas`. |
| "Feito" no próximo-passo | progresso + ações | Combinado: marca checkbox + cria evento. |
| "Re-escanear" em contexto | (via fetch) | `POST /scan` → http.server handler roda `forge.py scan --silent --quick`. |

Todos outros botões abrem notas via `obsidian://open?vault=X&file=Y` — zero efeito.

### 7.6 Recalculo dos contadores

Quando user registra progresso:

```
1. JS escreve linha em progresso/YYYY-MM-DD.md
2. JS re-lê TODOS os arquivos progresso/*.md
3. JS agrega eventos por tipo
4. JS re-escreve campo `atual` no frontmatter de _metas.md
5. JS re-renderiza barras
```

Mesma lógica espelhada em `forge.py dash --refresh` (agregação Python pro CLI ou quem não usa browser). Testado pra garantir paridade.

### 7.7 "Próximo passo sugerido" (algoritmo determinístico)

```javascript
for (const acao of acoesOrdenadas) {          // 01 → 07
    if (acao.status === 'em_andamento') {
        const tarefaPendente = primeiraTask(acao).naoMarcada();
        return `${acao.titulo}: ${tarefaPendente}`;
    }
}
return "Todos os marcos estão feitos. Revise metas ou inicie novo ciclo.";
```

Zero LLM no dashboard runtime. Previsível, auditável.

### 7.8 CLI

```bash
python3 forge.py dash                  # http.server + browser
python3 forge.py dash --refresh        # só recalcula contadores, sem browser
python3 forge.py dash --port 5000      # porta custom
python3 forge.py dash --no-browser     # serve sem abrir browser
```

## 8. Integração com skills existentes

### 8.1 `obsidian-init`

Duas mudanças:
1. Pergunta nova: **"Quer ativar a área `04 - Negocio` e o módulo forge?"** (default N).
2. Se sim: cria `04 - Negocio/` com subpastas vazias + `_README.md` explicando.

### 8.2 `obsidian-librarian`

Aprende os 7 tipos de nota (`plano`, `metas`, `contexto`, `config_scan`, `contexto_projeto`, `progresso`, `acao`). `_INDEX.md` passa a listar `04 - Negocio/` como 5ª área.

**Proteção contra edição**: `_plano.md` e `_metas.md` ganham campo `frontmatter.protected: true`. O librarian lê esse campo e, se presente, faz só leitura (indexação, tags, backlinks) — nunca reescreve corpo nem frontmatter. Forge é a única skill autorizada a escrever nesses dois arquivos. Demais arquivos (`contexto/*.md`, `progresso/*.md`, `acoes/*.md`) seguem a regra padrão do librarian.

### 8.3 CLAUDE.md do vault template

Ganha bloco novo: "Área `04 - Negocio` (forge) — território do forge; edição manual OK mas re-run de `forge-plan` pode sobrescrever."

## 9. Onboarding (primeira vez)

```
User digita: /obsidian-master-kit:forge-plan

Skill detecta ausência de 04 - Negocio/ → pergunta se cria estrutura.
Conduz entrevista dos 4 passos (~15 min).
Ao final: sugere forge-scan e forge-dash como próximos passos opcionais.
```

Sub-comandos **idempotentes** — podem rodar N vezes sem quebrar.

## 10. Testing

### 10.1 Unit

- `test_forge_frontmatter.py` — parse/write YAML dos 7 tipos.
- `test_forge_math.py` — matemática do funil (derivação + validação + agregação).
- `test_forge_scan.py` — detecção de projeto ativo com fixtures.
- `test_forge_plan_state.py` — interruptibilidade (salvar/retomar).
- `test_forge_templates.py` — render dos 7 `acoes/*.md`.

### 10.2 Integration

- `test_forge_e2e.py` — fluxo completo em vault temporário: `init → plan (respostas scripted) → scan (fixtures) → dash --refresh`. Valida arquivos finais.

### 10.3 Browser E2E (Playwright, condicional)

- Dashboard carrega, renderiza 5 seções.
- Checkbox marca ação → arquivo `acoes/*.md` atualizado.
- Modal registrar progresso → `progresso/YYYY-MM-DD.md` criado, barras sobem.
- Skip automático se Chromium ausente.

### 10.4 Mock mode

`forge.py scan --mock` usa fixtures em `tests/fixtures/projetos-fake/` — auditável linha a linha, offline, deterministic.

## 11. Invariantes globais (hard rules)

1. **Territorialidade**: só escreve em `04 - Negocio/`. Nunca `CLAUDE.md` do vault.
2. **Zero aritmética no LLM**: contas em Python/JS, com testes.
3. **Zero daemon / zero processo persistente**: só CLI on-demand + hook opt-in.
4. **Localhost-only**: http.server bind `127.0.0.1`.
5. **Zero LLM no dashboard runtime**: "próximo passo" é determinístico. Entrevista usa LLM (é conversa); dashboard não.
6. **Idempotência**: todo sub-comando roda N vezes sem quebrar.
7. **Interruptibilidade**: `forge-plan` salva estado parcial e retoma.
8. **Metodologia hardcoded**: 4 passos + 7 ações da aula, ponto final.
9. **pt-BR hardcoded**: templates, entrevista, dashboard — tudo português.
10. **Dashboard requer Chromium** pra edição completa. Outros browsers degradam pra read-only.

## 12. Fora de escopo (v1)

- Mobile / responsive mobile
- i18n ou outras metodologias
- Export pra PDF/PPTX/DOCX
- Cloud sync
- Integrações externas (Google Calendar, Slack, Stripe)
- Auth multi-usuário no dashboard
- Suporte Windows no scanner (macOS + Linux só)
- LLM gerando "próximo passo" contextualmente
- Skill separada de "aprendizado/estudo" — forge foca em negócio; estudo vira skill irmã em v2 se demandar.

## 13. Critério de "done" do v1

1. User novo roda `forge-plan`, completa 4 passos em ~15 min, gera `_plano.md` + `_metas.md` + 7 `acoes/*.md` corretos.
2. User roda `forge-scan`, vê ≥1 projeto ativo em `contexto/`.
3. User roda `forge-dash`, abre no Chrome, vê 5 seções com dados reais.
4. User clica "+ registrar progresso" 3 vezes → contador do funil sobe → re-abrir mantém estado.
5. Todos testes passam (pytest + Playwright opcional) em macOS + Linux.

## 14. Dependências e riscos

### 14.1 Dependências novas

- `pyyaml` (já no kit).
- Nenhuma nova dependência Python.
- Playwright (dev-only, opcional pros testes de browser) — já é dev dependency potencial.

### 14.2 Riscos identificados

| Risco | Impacto | Mitigação |
|---|---|---|
| Mesmo destino do pulse (UX opaca) | Alto | Layout scroll-único, sem tabs; design Tino-like validado por referência. |
| User não preencher `_config-scan.md` corretamente | Médio | Entrevista guiada no `--init` + validação de paths. |
| LLM errar matemática do Passo 3 | Alto | Validação aritmética no Python antes de gravar. Zero LLM em conta. |
| File System Access API requer Chrome | Médio | Banner explica; Firefox/Safari usam read-only como fallback. |
| Scanner ser lento em pastas grandes | Médio | Profundidade máx 3, timeout hook 5s, patterns ignore embutidos. |
| Metodologia hardcoded virar rígida demais | Baixo (por ora) | v2 pode introduzir templating se demanda aparecer. |

## 15. Docs a criar/atualizar

| Arquivo | Novo/Update |
|---|---|
| `skills/obsidian-forge/SKILL.md` | novo |
| `skills/obsidian-forge/references/metodologia-aula.md` | novo |
| `skills/obsidian-forge/references/schema-vault.md` | novo |
| `docs/forge-quickstart.md` | novo |
| `README.md` (kit) | update: bloco v1.1 |
| `docs/ROADMAP.md` | update: forge shipped em v1.1 |
| `CHANGELOG.md` | update: entrada v1.1.0 |
