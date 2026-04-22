# obsidian-forge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Adicionar a skill `obsidian-forge` ao obsidian-master-kit (v1.1), entregando 3 sub-comandos (`forge-scan`, `forge-plan`, `forge-dash`) que transformam o vault num sistema operacional de execução de negócio baseado na metodologia "IA como ferramenta".

**Architecture:** Skill Python única com 3 módulos (scanner de contexto, arquiteto de negócio, dashboard executor). Pipeline em Python, dashboard em HTML estático vanilla + File System Access API. Zero daemon, zero cloud, localhost-only. Escreve apenas em `04 - Negocio/` do vault.

**Tech Stack:** Python 3.10+, pytest, PyYAML (nova dep), HTML/CSS/JS vanilla (**sem** uso de `.innerHTML` — rendering via `createElement` + `textContent` + `replaceChildren`), Python `http.server` stdlib, File System Access API (Chromium-only), Playwright (testes opcionais).

**Spec de referência:** `docs/superpowers/specs/2026-04-22-obsidian-forge-design.md`

---

## Mapa de arquivos

### Novos na skill

```
skills/obsidian-forge/
├── SKILL.md
├── scripts/
│   ├── __init__.py
│   ├── forge.py                    # CLI dispatcher
│   ├── frontmatter.py              # YAML read/write utils
│   ├── math_funil.py               # funnel math + validation + aggregation
│   ├── scan_context.py             # Módulo 1
│   ├── plan_business.py            # Módulo 2 (interview driver)
│   ├── dash_refresh.py             # Módulo 3 CLI helper
│   ├── dashboard.html              # single-file dashboard (~800 linhas)
│   └── templates/
│       ├── plano.md
│       ├── metas.md
│       ├── contexto.md
│       ├── config_scan.md
│       ├── _area_readme.md
│       └── acoes/
│           ├── 01-segundo-cerebro.md
│           ├── 02-plano-de-negocio.md
│           ├── 03-captacao-conteudo.md
│           ├── 04-captacao-venda.md
│           ├── 05-script-reuniao.md
│           ├── 06-processo-entrega.md
│           └── 07-admin-financeiro.md
└── references/
    ├── metodologia-aula.md
    └── schema-vault.md
```

### Testes novos

```
tests/
├── test_forge_frontmatter.py
├── test_forge_math.py
├── test_forge_scan.py
├── test_forge_plan_state.py
├── test_forge_templates.py
├── test_forge_dash_refresh.py
├── test_forge_integration.py
└── fixtures/
    └── forge/
        └── projetos-fake/
            ├── repo-ativo-python/
            ├── repo-ativo-node/
            └── repo-velho/
```

### Modificações em código existente

- `skills/obsidian-init/scripts/*` — pergunta opcional "ativar 04 - Negocio?"
- `skills/obsidian-init/assets/vault-template/CLAUDE.md` — bloco sobre forge
- `skills/obsidian-librarian/scripts/*` — honrar `frontmatter.protected: true` + aprender 7 tipos
- `pyproject.toml` — `pyyaml>=6.0` (deps de produção); `playwright>=1.40` (dev, opcional)
- `commands/` — 3 arquivos `forge-scan.md`, `forge-plan.md`, `forge-dash.md`
- `plugin.json` — registrar skill + 3 commands
- `README.md`, `docs/ROADMAP.md`, `CHANGELOG.md`, `docs/forge-quickstart.md`

---

# Wave 0 — Foundation (scaffolding, não-TDD)

### Task 0.1: Criar estrutura de pastas + SKILL.md

**Files:**
- Create: `skills/obsidian-forge/SKILL.md`
- Create: `skills/obsidian-forge/scripts/__init__.py`
- Create: `skills/obsidian-forge/scripts/templates/acoes/` (diretório)
- Create: `skills/obsidian-forge/references/` (diretório)

- [ ] **Step 1: Criar pastas**

```bash
mkdir -p skills/obsidian-forge/scripts/templates/acoes
mkdir -p skills/obsidian-forge/references
touch skills/obsidian-forge/scripts/__init__.py
```

- [ ] **Step 2: Escrever SKILL.md**

`skills/obsidian-forge/SKILL.md`:

````markdown
---
name: obsidian-forge
description: Use quando o usuario diz "meu plano de negocio", "matematica do resultado", "abre o painel do negocio", "scanear projetos", "registrar progresso", ou invoca `/obsidian-master-kit:forge-scan|plan|dash`. Conduz entrevista dos 4 passos (3 Ps, precificacao, matematica, 7 acoes macro) conforme metodologia da aula "IA como ferramenta"; mapeia projetos ativos do PC como notas atomicas; sobe dashboard HTML estatico em localhost:4712 com File System Access API para cliques executores. 100% local, zero cloud, zero daemon.
---

# obsidian-forge

Skill de execucao de negocio. Transforma o vault num sistema operacional
pessoal pra empreender usando IA como ferramenta.

## Quando usar

- Usuario digita `/obsidian-master-kit:forge-plan`, `forge-scan` ou `forge-dash`.
- Usuario fala "plano de negocio", "matematica do resultado", "abre painel".
- Usuario quer registrar progresso nas metas.

## Quando **nao** usar

- Vault sem `obsidian-init` rodado (requer estrutura base).

## Fluxo canonico

### Passo 1: Detecte o vault

Walk ancestrais procurando `.obsidian-master/marker.json`. Senao,
pede `--vault PATH`.

### Passo 2: Escolha o sub-comando

| Intencao | Sub-comando |
|---|---|
| "Varrer projetos no PC" | `scan` |
| "Fazer plano de negocio" | `plan` |
| "Abrir painel" | `dash` |

### Passo 3: Invoque

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/obsidian-forge/scripts/forge.py \
  <sub-comando> [--vault PATH] [flags]
```

## Invariantes duros

1. **Territorialidade**: so escreve em `04 - Negocio/`. Nunca em outras areas.
2. **Zero aritmetica no LLM**: contas em Python/JS, validadas por teste.
3. **Zero daemon**: so CLI on-demand + hook `SessionStart` opt-in.
4. **Localhost-only**: `http.server` em `127.0.0.1`.
5. **Zero LLM no dashboard runtime**: "proximo passo" e deterministico.
6. **pt-BR hardcoded** em templates, entrevista, dashboard.
7. **Metodologia hardcoded** (4 passos + 7 acoes da aula).
8. **Dashboard requer Chromium** pra edicao. Outros browsers: read-only.
9. **Dashboard usa DOM APIs seguras**: sem `.innerHTML` com conteudo de
   arquivo; tudo via `createElement` + `textContent` + `replaceChildren`.
````

- [ ] **Step 3: Commit**

```bash
git add skills/obsidian-forge/
git commit -m "feat(forge): scaffold skill (SKILL.md + estrutura de pastas)"
```

---

### Task 0.2: Adicionar PyYAML ao pyproject

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Adicionar dep**

No `pyproject.toml`, em `[project] dependencies`:

```toml
dependencies = [
    "model2vec>=0.8.1",
    "sqlite-vec>=0.1.3",
    "networkx>=3.3",
    "scipy>=1.11",
    "scikit-learn>=1.3",
    "numpy>=1.26.4",
    "pyyaml>=6.0",
]
```

E em `[project.optional-dependencies.dev]`:

```toml
dev = [
    "pytest>=8.0",
    "pytest-cov>=4.1",
    "playwright>=1.40",
]
```

- [ ] **Step 2: Instalar**

```bash
pip install -e ".[dev]"
```

Expected: instala sem erro; `import yaml` funciona.

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "chore(deps): add pyyaml + playwright para skill forge"
```

---

### Task 0.3: Templates markdown dos 5 docs master

**Files:**
- Create: `skills/obsidian-forge/scripts/templates/plano.md`
- Create: `skills/obsidian-forge/scripts/templates/metas.md`
- Create: `skills/obsidian-forge/scripts/templates/contexto.md`
- Create: `skills/obsidian-forge/scripts/templates/config_scan.md`
- Create: `skills/obsidian-forge/scripts/templates/_area_readme.md`

- [ ] **Step 1: `plano.md`**

```markdown
---
tipo: plano
protected: true
atualizado: {{atualizado}}
ciclo: {{ciclo}}
produto: "{{produto}}"
problema: "{{problema}}"
pessoa: "{{pessoa}}"
precificacao:
  valor_unitario: {{valor_unitario}}
  moeda: BRL
  base:
    resultado_potencial: "{{resultado_potencial}}"
    tempo_economizado: "{{tempo_economizado}}"
    esforco_reduzido: "{{esforco_reduzido}}"
    producao_aumentada: "{{producao_aumentada}}"
status: ativo
---

# Plano — ciclo {{ciclo}}

## 3 Ps

### Produto
{{produto_prosa}}

### Problema
{{problema_prosa}}

### Pessoa (ICP)
{{pessoa_prosa}}

## Precificação — raciocínio

Preço unitário: **R$ {{valor_unitario}}**.

- Resultado potencial: {{resultado_potencial}}
- Tempo economizado: {{tempo_economizado}}
- Esforço reduzido: {{esforco_reduzido}}
- Produção aumentada: {{producao_aumentada}}
```

- [ ] **Step 2: `metas.md`**

```markdown
---
tipo: metas
protected: true
atualizado: {{atualizado}}
ciclo: {{ciclo}}
objetivo:
  titulo: "{{objetivo_titulo}}"
  valor_alvo: {{valor_alvo}}
  valor_atual: 0
  moeda: BRL
  prazo: {{prazo}}
funil:
  - etapa: clientes
    alvo: {{clientes_alvo}}
    atual: 0
    valor_unitario: {{valor_unitario}}
  - etapa: reunioes
    alvo: {{reunioes_alvo}}
    atual: 0
    taxa_conversao: {{reunioes_taxa}}
  - etapa: leads
    alvo: {{leads_alvo}}
    atual: 0
    taxa_conversao: {{leads_taxa}}
  - etapa: alcance
    alvo: {{alcance_alvo}}
    atual: 0
    fonte: {{alcance_fonte}}
---

# Metas — ciclo {{ciclo}}

## Matemática do resultado

- Objetivo: **{{objetivo_titulo}}** ({{valor_alvo}} BRL).
- Dividido por **R$ {{valor_unitario}}/cliente** = **{{clientes_alvo}} clientes**.
- Taxa reuniao→cliente **{{reunioes_taxa_pct}}%** = **{{reunioes_alvo}} reuniões**.
- Taxa lead→reuniao **{{leads_taxa_pct}}%** = **{{leads_alvo}} leads**.
- Alcance ({{alcance_fonte}}): **{{alcance_alvo}}**.
```

- [ ] **Step 3: `contexto.md`**

```markdown
---
tipo: contexto
atualizado: {{atualizado}}
projetos_ativos: {{projetos_ativos}}
---

# Contexto vivo

Agregado do scanner. Atualizado em {{atualizado}}.

## Projetos em construção

{{projetos_lista}}

## Stack em uso

{{stacks_lista}}
```

- [ ] **Step 4: `config_scan.md`**

```markdown
---
tipo: config_scan
pastas_observadas: []
janela_ativo_dias: 30
limite_profundidade: 3
hook_sessionstart_ativo: false
timeout_hook_s: 5
ignore:
  - node_modules
  - .venv
  - __pycache__
  - dist
  - build
  - .next
  - target
---

# Config do scanner

Edite `pastas_observadas` pra mudar o que o forge vigia.
```

- [ ] **Step 5: `_area_readme.md`**

```markdown
# 04 - Negocio (forge)

Esta área é território do módulo `obsidian-forge`.

## Arquivos

- `_plano.md` — 3 Ps + precificação (protegido: só forge escreve)
- `_metas.md` — matemática do resultado + contadores (protegido)
- `_contexto.md` — agregado do scanner
- `_config-scan.md` — config do scanner
- `contexto/` — notas atômicas de projetos
- `progresso/` — eventos diários
- `acoes/` — 7 ações macro canônicas

## Comandos

- `/obsidian-master-kit:forge-plan`
- `/obsidian-master-kit:forge-scan`
- `/obsidian-master-kit:forge-dash`
```

- [ ] **Step 6: Commit**

```bash
git add skills/obsidian-forge/scripts/templates/
git commit -m "feat(forge): 5 templates dos docs master"
```

---

### Task 0.4: Templates das 7 ações macro

**Files:**
- Create: `skills/obsidian-forge/scripts/templates/acoes/01-segundo-cerebro.md`
- Create: `skills/obsidian-forge/scripts/templates/acoes/02-plano-de-negocio.md`
- Create: `skills/obsidian-forge/scripts/templates/acoes/03-captacao-conteudo.md`
- Create: `skills/obsidian-forge/scripts/templates/acoes/04-captacao-venda.md`
- Create: `skills/obsidian-forge/scripts/templates/acoes/05-script-reuniao.md`
- Create: `skills/obsidian-forge/scripts/templates/acoes/06-processo-entrega.md`
- Create: `skills/obsidian-forge/scripts/templates/acoes/07-admin-financeiro.md`

- [ ] **Step 1: `01-segundo-cerebro.md`**

```markdown
---
tipo: acao
slug: segundo-cerebro
ordem: 1
titulo: "Segundo Cérebro (vault ativo)"
status: concluido
tarefas_totais: 3
tarefas_feitas: 3
atualizado: {{atualizado}}
---

# 01. Segundo Cérebro

Ter um vault Obsidian estruturado onde a IA pode acessar seu contexto.

## Checklist

- [x] Vault criado via `obsidian-init`
- [x] Librarian ativo
- [x] Área `04 - Negocio` criada
```

- [ ] **Step 2: `02-plano-de-negocio.md`**

```markdown
---
tipo: acao
slug: plano-de-negocio
ordem: 2
titulo: "Plano de Negócio (3 Ps + Precificação)"
status: em_andamento
tarefas_totais: 4
tarefas_feitas: 0
atualizado: {{atualizado}}
---

# 02. Plano de Negócio

Definir Produto, Problema, Pessoa e Precificação.

## Checklist

- [ ] Produto definido em uma frase
- [ ] Problema específico identificado
- [ ] Pessoa (ICP) descrita
- [ ] Precificação com 4 bases documentada
```

- [ ] **Step 3: `03-captacao-conteudo.md`**

```markdown
---
tipo: acao
slug: captacao-conteudo
ordem: 3
titulo: "Captação via Conteúdo"
status: pendente
tarefas_totais: 5
tarefas_feitas: 0
atualizado: {{atualizado}}
---

# 03. Captação via Conteúdo

Alcance orgânico que vira lead.

## Checklist

- [ ] Canal principal escolhido
- [ ] Pauta de 10 temas baseada nas dores do ICP
- [ ] Frequência definida
- [ ] Primeiro conteúdo publicado
- [ ] Métrica inicial de alcance registrada
```

- [ ] **Step 4: `04-captacao-venda.md`**

```markdown
---
tipo: acao
slug: captacao-venda
ordem: 4
titulo: "Captação e Venda (estrutura)"
status: pendente
tarefas_totais: 5
tarefas_feitas: 0
atualizado: {{atualizado}}
---

# 04. Captação e Venda

Converter alcance em reunião agendada.

## Checklist

- [ ] Landing ou formulário de captação
- [ ] Lead magnet
- [ ] Fluxo de qualificação
- [ ] Agenda conectada (Calendly ou similar)
- [ ] Primeira reunião agendada
```

- [ ] **Step 5: `05-script-reuniao.md`**

```markdown
---
tipo: acao
slug: script-reuniao
ordem: 5
titulo: "Script de Reunião de Vendas"
status: pendente
tarefas_totais: 4
tarefas_feitas: 0
atualizado: {{atualizado}}
---

# 05. Script de Reunião

Roteiro que transforma reunião em cliente.

## Checklist

- [ ] Abertura (rapport + contexto)
- [ ] Diagnóstico (dor + custo da dor)
- [ ] Oferta (solução + preço + resultado)
- [ ] Tratativa de objeções canônicas
```

- [ ] **Step 6: `06-processo-entrega.md`**

```markdown
---
tipo: acao
slug: processo-entrega
ordem: 6
titulo: "Processo de Entrega"
status: pendente
tarefas_totais: 4
tarefas_feitas: 0
atualizado: {{atualizado}}
---

# 06. Processo de Entrega

Como operar depois que o cliente fecha.

## Checklist

- [ ] Onboarding documentado
- [ ] Playbook de implementação
- [ ] Cadência de acompanhamento
- [ ] Critério de "entrega concluída"
```

- [ ] **Step 7: `07-admin-financeiro.md`**

```markdown
---
tipo: acao
slug: admin-financeiro
ordem: 7
titulo: "Administração e Controle"
status: pendente
tarefas_totais: 3
tarefas_feitas: 0
atualizado: {{atualizado}}
---

# 07. Administração e Controle

Separar pessoal de empresa.

## Checklist

- [ ] Conta bancária separada
- [ ] Controle de caixa (entradas/saídas)
- [ ] Pró-labore definido
```

- [ ] **Step 8: Commit**

```bash
git add skills/obsidian-forge/scripts/templates/acoes/
git commit -m "feat(forge): templates das 7 acoes macro"
```

---

### Task 0.5: Refs docs

**Files:**
- Create: `skills/obsidian-forge/references/metodologia-aula.md`
- Create: `skills/obsidian-forge/references/schema-vault.md`

- [ ] **Step 1: `metodologia-aula.md`**

```markdown
# Metodologia — IA é ferramenta, não produto

## Princípio central

IA é martelo, não casa. Quem enriquece usa IA pra resolver dor específica
de mercado específico e cobra pelo resultado.

## Os 4 Passos

### 1. 3 Ps
- Produto: solução oferecida
- Problema: dor resolvida
- Pessoa: público atendido

### 2. Precificação (4 bases de valor)
- Resultado potencial
- Tempo economizado
- Esforço reduzido
- Produção aumentada

### 3. Matemática do Resultado
Funil invertido: Objetivo → clientes → reuniões → leads → alcance.

Exemplo: R$ 10.000 → R$ 2.500/cliente → 4 clientes → 40 reuniões → 400 leads → 4.000 alcance.

### 4. Ações Macro (7 frentes)
1. Segundo Cérebro
2. Plano de Negócio
3. Captação via Conteúdo
4. Captação/Venda (estrutura)
5. Script de Reunião
6. Processo de Entrega
7. Administração e Controle

## Eventos válidos de progresso

- `lead_captado` — funil leads
- `reuniao_realizada` — funil reuniões
- `cliente_fechado` — funil clientes + valor_total
- `conteudo_publicado` — funil alcance (+1)
- `alcance_manual` — funil alcance (quantidade explícita)
```

- [ ] **Step 2: `schema-vault.md`**

```markdown
# Schema das notas em `04 - Negocio/`

7 tipos. Frontmatter YAML em todos.

## 1. plano (1 — `_plano.md`)
Campos: tipo, ciclo, produto, problema, pessoa, precificacao.*, status, protected: true.

## 2. metas (1 — `_metas.md`)
Campos: tipo, ciclo, objetivo.{titulo,valor_alvo,valor_atual,prazo}, funil[].{etapa,alvo,atual}, protected: true.

Etapas fixas: clientes, reunioes, leads, alcance.

## 3. contexto (1 — `_contexto.md`)
Campos: tipo, atualizado, projetos_ativos.

## 4. config_scan (1 — `_config-scan.md`)
Campos: pastas_observadas, janela_ativo_dias, limite_profundidade, hook_sessionstart_ativo, timeout_hook_s, ignore.

## 5. contexto_projeto (N — `contexto/<slug>.md`)
Campos: tipo, nome, caminho, stack, status, ultimo_commit, atualizado.

## 6. progresso (N — `progresso/YYYY-MM-DD.md`)
Campos: tipo, data, eventos.
Body: linhas `- HH:MM — tipo (detalhes)`.

## 7. acao (7 fixos — `acoes/XX-<slug>.md`)
Campos: tipo, slug, ordem, titulo, status, tarefas_totais, tarefas_feitas, atualizado.
Status: pendente | em_andamento | concluido.
```

- [ ] **Step 3: Commit**

```bash
git add skills/obsidian-forge/references/
git commit -m "docs(forge): references (metodologia + schema)"
```

---

# Wave 1 — Shared utils (TDD)

### Task 1.1: `frontmatter.py` — read/write YAML

**Files:**
- Create: `skills/obsidian-forge/scripts/frontmatter.py`
- Test: `tests/test_forge_frontmatter.py`

- [ ] **Step 1: Escrever testes**

`tests/test_forge_frontmatter.py`:

```python
"""Testes de frontmatter.py."""
from __future__ import annotations

import sys
from pathlib import Path

FORGE_DIR = Path(__file__).parent.parent / "skills" / "obsidian-forge" / "scripts"
sys.path.insert(0, str(FORGE_DIR))

from frontmatter import read_frontmatter, write_frontmatter, parse_frontmatter, serialize_frontmatter  # noqa: E402


def test_read_frontmatter_simple(tmp_path: Path) -> None:
    p = tmp_path / "n.md"
    p.write_text("---\ntipo: plano\nstatus: ativo\n---\n\n# Body\n", encoding="utf-8")
    meta, body = read_frontmatter(p)
    assert meta["tipo"] == "plano"
    assert meta["status"] == "ativo"
    assert body.strip() == "# Body"


def test_read_frontmatter_nested(tmp_path: Path) -> None:
    p = tmp_path / "m.md"
    p.write_text("---\nobjetivo:\n  titulo: 'R$ 10k'\n  valor_alvo: 10000\n---\n", encoding="utf-8")
    meta, _ = read_frontmatter(p)
    assert meta["objetivo"]["valor_alvo"] == 10000


def test_read_frontmatter_list_of_dicts(tmp_path: Path) -> None:
    p = tmp_path / "m.md"
    p.write_text(
        "---\nfunil:\n  - etapa: clientes\n    alvo: 4\n  - etapa: reunioes\n    alvo: 40\n---\n",
        encoding="utf-8",
    )
    meta, _ = read_frontmatter(p)
    assert len(meta["funil"]) == 2
    assert meta["funil"][0]["etapa"] == "clientes"
    assert meta["funil"][1]["alvo"] == 40


def test_write_roundtrip(tmp_path: Path) -> None:
    p = tmp_path / "o.md"
    meta = {"tipo": "acao", "slug": "x", "ordem": 3, "tarefas_feitas": 2}
    body = "# T\n\n- [ ] task\n"
    write_frontmatter(p, meta, body)
    meta2, body2 = read_frontmatter(p)
    assert meta2 == meta
    assert body2.strip() == body.strip()


def test_write_preserves_body(tmp_path: Path) -> None:
    p = tmp_path / "o.md"
    body = "linha 1\n\n- [x] feita\n- [ ] pendente\n"
    write_frontmatter(p, {"tipo": "acao"}, body)
    assert body in p.read_text(encoding="utf-8")


def test_read_no_frontmatter(tmp_path: Path) -> None:
    p = tmp_path / "plain.md"
    p.write_text("# so body\n", encoding="utf-8")
    meta, body = read_frontmatter(p)
    assert meta == {}
    assert "# so body" in body
```

- [ ] **Step 2: Rodar, confirmar falha**

```bash
pytest tests/test_forge_frontmatter.py -v
```

Expected: FAIL com `ModuleNotFoundError`.

- [ ] **Step 3: Implementar**

`skills/obsidian-forge/scripts/frontmatter.py`:

```python
"""Read/write YAML frontmatter em notas markdown."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Tuple

import yaml

_FRONTMATTER_RE = re.compile(
    r"\A---\s*\n(.*?)^---\s*\n?(.*)\Z", re.DOTALL | re.MULTILINE
)


def parse_frontmatter(text: str) -> Tuple[dict, str]:
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    raw, body = m.group(1), m.group(2)
    meta = yaml.safe_load(raw) or {}
    if not isinstance(meta, dict):
        return {}, text
    return meta, body


def read_frontmatter(path: Path) -> Tuple[dict, str]:
    return parse_frontmatter(Path(path).read_text(encoding="utf-8"))


def serialize_frontmatter(meta: dict, body: str) -> str:
    if not meta:
        return body
    dumped = yaml.safe_dump(
        meta, allow_unicode=True, sort_keys=False, default_flow_style=False,
    ).rstrip("\n")
    return f"---\n{dumped}\n---\n\n{body.lstrip()}"


def write_frontmatter(path: Path, meta: dict, body: str) -> None:
    Path(path).write_text(serialize_frontmatter(meta, body), encoding="utf-8")
```

- [ ] **Step 4: Rodar, passar**

```bash
pytest tests/test_forge_frontmatter.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add skills/obsidian-forge/scripts/frontmatter.py tests/test_forge_frontmatter.py
git commit -m "feat(forge): frontmatter.py read/write + 6 testes"
```

---

### Task 1.2: `math_funil.py` — derivar/validar/agregar

**Files:**
- Create: `skills/obsidian-forge/scripts/math_funil.py`
- Test: `tests/test_forge_math.py`

- [ ] **Step 1: Teste**

```python
"""Testes de math_funil."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

FORGE_DIR = Path(__file__).parent.parent / "skills" / "obsidian-forge" / "scripts"
sys.path.insert(0, str(FORGE_DIR))

from math_funil import derivar_funil, validar_funil, FunilInvalido, agregar_progresso  # noqa: E402


def test_derivar_canonico() -> None:
    f = derivar_funil(valor_alvo=10000, valor_unitario=2500,
                      reunioes_taxa=0.10, leads_taxa=0.10, alcance_multiplicador=10)
    assert f == {"clientes": 4, "reunioes": 40, "leads": 400, "alcance": 4000}


def test_derivar_arredonda_para_cima() -> None:
    f = derivar_funil(valor_alvo=10000, valor_unitario=3000,
                      reunioes_taxa=0.15, leads_taxa=0.10, alcance_multiplicador=10)
    assert f["clientes"] == 4   # ceil(3.33)


def test_validar_ok() -> None:
    f = [
        {"etapa": "clientes", "alvo": 4, "valor_unitario": 2500},
        {"etapa": "reunioes", "alvo": 40, "taxa_conversao": 0.10},
        {"etapa": "leads", "alvo": 400, "taxa_conversao": 0.10},
        {"etapa": "alcance", "alvo": 4000, "fonte": "conteudo"},
    ]
    validar_funil(f, valor_alvo=10000)


def test_validar_falha_quando_valor_nao_bate() -> None:
    f = [
        {"etapa": "clientes", "alvo": 3, "valor_unitario": 2500},
        {"etapa": "reunioes", "alvo": 40, "taxa_conversao": 0.10},
        {"etapa": "leads", "alvo": 400, "taxa_conversao": 0.10},
        {"etapa": "alcance", "alvo": 4000, "fonte": "conteudo"},
    ]
    with pytest.raises(FunilInvalido, match="clientes"):
        validar_funil(f, valor_alvo=10000)


def test_agregar_eventos() -> None:
    eventos = [
        {"tipo": "cliente_fechado", "valor": 2500},
        {"tipo": "cliente_fechado", "valor": 2500},
        {"tipo": "reuniao_realizada"},
        {"tipo": "lead_captado"},
        {"tipo": "lead_captado"},
        {"tipo": "lead_captado"},
        {"tipo": "conteudo_publicado"},
    ]
    a = agregar_progresso(eventos)
    assert a == {"clientes": 2, "reunioes": 1, "leads": 3, "alcance": 1, "valor_total": 5000.0}


def test_agregar_alcance_manual() -> None:
    e = [{"tipo": "alcance_manual", "quantidade": 120},
         {"tipo": "conteudo_publicado"}]
    assert agregar_progresso(e)["alcance"] == 121
```

- [ ] **Step 2: Rodar, falhar**

```bash
pytest tests/test_forge_math.py -v
```

Expected: FAIL.

- [ ] **Step 3: Implementar**

`skills/obsidian-forge/scripts/math_funil.py`:

```python
"""Matematica do funil — deriva, valida, agrega. Zero LLM."""
from __future__ import annotations

import math
from typing import Any


class FunilInvalido(ValueError):
    pass


def derivar_funil(*, valor_alvo: float, valor_unitario: float,
                  reunioes_taxa: float, leads_taxa: float,
                  alcance_multiplicador: float) -> dict[str, int]:
    if valor_unitario <= 0 or reunioes_taxa <= 0 or leads_taxa <= 0:
        raise FunilInvalido("Parametros devem ser positivos.")
    clientes = math.ceil(valor_alvo / valor_unitario)
    reunioes = math.ceil(clientes / reunioes_taxa)
    leads = math.ceil(reunioes / leads_taxa)
    alcance = math.ceil(leads * alcance_multiplicador)
    return {"clientes": clientes, "reunioes": reunioes, "leads": leads, "alcance": alcance}


def validar_funil(funil: list[dict[str, Any]], *, valor_alvo: float) -> None:
    etapas = {e["etapa"]: e for e in funil}
    for nome in ("clientes", "reunioes", "leads", "alcance"):
        if nome not in etapas:
            raise FunilInvalido(f"Etapa '{nome}' ausente.")

    c = etapas["clientes"]["alvo"]
    vu = etapas["clientes"]["valor_unitario"]
    if c * vu != valor_alvo:
        raise FunilInvalido(f"clientes ({c}) * valor_unitario ({vu}) != valor_alvo ({valor_alvo}).")

    r = etapas["reunioes"]["alvo"]
    rt = etapas["reunioes"]["taxa_conversao"]
    if r != math.ceil(c / rt):
        raise FunilInvalido(f"reunioes.alvo={r}, esperado {math.ceil(c / rt)}.")

    l = etapas["leads"]["alvo"]
    lt = etapas["leads"]["taxa_conversao"]
    if l != math.ceil(r / lt):
        raise FunilInvalido(f"leads.alvo={l}, esperado {math.ceil(r / lt)}.")


_TIPO_PARA_ETAPA = {
    "cliente_fechado": "clientes",
    "reuniao_realizada": "reunioes",
    "lead_captado": "leads",
    "conteudo_publicado": "alcance",
    "alcance_manual": "alcance",
}


def agregar_progresso(eventos: list[dict[str, Any]]) -> dict[str, Any]:
    a = {"clientes": 0, "reunioes": 0, "leads": 0, "alcance": 0, "valor_total": 0.0}
    for ev in eventos:
        t = ev.get("tipo")
        e = _TIPO_PARA_ETAPA.get(t)
        if e is None:
            continue
        if t == "alcance_manual":
            a["alcance"] += int(ev.get("quantidade", 0))
        else:
            a[e] += 1
        if t == "cliente_fechado":
            a["valor_total"] += float(ev.get("valor", 0))
    return a
```

- [ ] **Step 4: Rodar, passar**

```bash
pytest tests/test_forge_math.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add skills/obsidian-forge/scripts/math_funil.py tests/test_forge_math.py
git commit -m "feat(forge): math_funil derivar/validar/agregar + 6 testes"
```

---

# Wave 2 — Módulo 1 Scanner

### Task 2.1: Fixtures de projetos fake

**Files:**
- Create: `tests/fixtures/forge/projetos-fake/repo-ativo-python/.git/HEAD`
- Create: `tests/fixtures/forge/projetos-fake/repo-ativo-python/pyproject.toml`
- Create: `tests/fixtures/forge/projetos-fake/repo-ativo-python/README.md`
- Create: `tests/fixtures/forge/projetos-fake/repo-ativo-node/.git/HEAD`
- Create: `tests/fixtures/forge/projetos-fake/repo-ativo-node/package.json`
- Create: `tests/fixtures/forge/projetos-fake/repo-ativo-node/README.md`
- Create: `tests/fixtures/forge/projetos-fake/repo-velho/.git/HEAD`
- Create: `tests/fixtures/forge/projetos-fake/repo-velho/README.md`

- [ ] **Step 1: Criar estrutura**

```bash
cd /Users/rafaelmelgaco/obsidian-master
mkdir -p tests/fixtures/forge/projetos-fake/repo-ativo-python/.git
mkdir -p tests/fixtures/forge/projetos-fake/repo-ativo-node/.git
mkdir -p tests/fixtures/forge/projetos-fake/repo-velho/.git
```

- [ ] **Step 2: Conteúdo dos fixtures**

`tests/fixtures/forge/projetos-fake/repo-ativo-python/.git/HEAD`:
```
ref: refs/heads/main
```

`tests/fixtures/forge/projetos-fake/repo-ativo-python/pyproject.toml`:
```toml
[project]
name = "repo-ativo-python"
version = "0.1.0"
```

`tests/fixtures/forge/projetos-fake/repo-ativo-python/README.md`:
```markdown
# repo-ativo-python

Primeiros 500 chars do README. Deve aparecer na nota atomica gerada.
```

`tests/fixtures/forge/projetos-fake/repo-ativo-node/.git/HEAD`: `ref: refs/heads/main`

`tests/fixtures/forge/projetos-fake/repo-ativo-node/package.json`:
```json
{"name":"repo-ativo-node","version":"1.0.0"}
```

`tests/fixtures/forge/projetos-fake/repo-ativo-node/README.md`:
```markdown
# repo-ativo-node

Fake Node.
```

`tests/fixtures/forge/projetos-fake/repo-velho/.git/HEAD`: `ref: refs/heads/main`

`tests/fixtures/forge/projetos-fake/repo-velho/README.md`: `# repo-velho\n\nInativo.`

- [ ] **Step 3: Commit**

```bash
git add tests/fixtures/forge/
git commit -m "test(forge): fixtures de projetos fake"
```

---

### Task 2.2: `scan_context.py` — detecção de repos

**Files:**
- Create: `skills/obsidian-forge/scripts/scan_context.py`
- Test: `tests/test_forge_scan.py`

- [ ] **Step 1: Teste (parte 1 — detecção e stack)**

`tests/test_forge_scan.py`:

```python
"""Testes do scanner."""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

FORGE_DIR = Path(__file__).parent.parent / "skills" / "obsidian-forge" / "scripts"
sys.path.insert(0, str(FORGE_DIR))

from scan_context import detectar_repos, detectar_stack, ler_readme_resumo  # noqa: E402

FIX = Path(__file__).parent / "fixtures" / "forge" / "projetos-fake"


@pytest.fixture
def fixture_atualizar_mtime() -> None:
    agora = time.time()
    velho = agora - (60 * 86400)
    for r in [FIX / "repo-ativo-python", FIX / "repo-ativo-node"]:
        for f in r.rglob("*"):
            if f.is_file() and ".git" not in f.parts:
                os.utime(f, (agora, agora))
    for f in (FIX / "repo-velho").rglob("*"):
        if f.is_file() and ".git" not in f.parts:
            os.utime(f, (velho, velho))


def test_detectar_repos_filtra_mtime(fixture_atualizar_mtime: None) -> None:
    repos = detectar_repos(pastas=[FIX], janela_ativo_dias=30, limite_profundidade=3, ignore=[])
    nomes = {r["nome"] for r in repos}
    assert "repo-ativo-python" in nomes
    assert "repo-ativo-node" in nomes
    assert "repo-velho" not in nomes


def test_detectar_repos_profundidade(tmp_path: Path) -> None:
    deep = tmp_path / "a" / "b" / "c" / "d" / "repo-deep"
    (deep / ".git").mkdir(parents=True)
    (deep / "README.md").write_text("# d")
    (deep / ".git" / "HEAD").write_text("ref:")
    repos = detectar_repos(pastas=[tmp_path], janela_ativo_dias=999,
                           limite_profundidade=3, ignore=[])
    assert not any(r["nome"] == "repo-deep" for r in repos)


def test_detectar_repos_ignore(tmp_path: Path) -> None:
    (tmp_path / "node_modules" / "algo" / ".git").mkdir(parents=True)
    (tmp_path / "node_modules" / "algo" / ".git" / "HEAD").write_text("ref:")
    repos = detectar_repos(pastas=[tmp_path], janela_ativo_dias=999,
                           limite_profundidade=5, ignore=["node_modules"])
    assert repos == []


def test_detectar_stack_python() -> None:
    assert "python" in detectar_stack(FIX / "repo-ativo-python")


def test_detectar_stack_node() -> None:
    assert "node" in detectar_stack(FIX / "repo-ativo-node")


def test_readme_resumo() -> None:
    t = ler_readme_resumo(FIX / "repo-ativo-python")
    assert t is not None
    assert len(t) <= 500
    assert "repo-ativo-python" in t


def test_readme_ausente(tmp_path: Path) -> None:
    assert ler_readme_resumo(tmp_path) is None
```

- [ ] **Step 2: Rodar, falhar**

```bash
pytest tests/test_forge_scan.py -v
```

Expected: FAIL.

- [ ] **Step 3: Implementar `scan_context.py`**

`skills/obsidian-forge/scripts/scan_context.py`:

```python
"""Scanner de contexto — detecta projetos ativos + gera notas atomicas."""
from __future__ import annotations

import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any


def detectar_repos(*, pastas: list[Path], janela_ativo_dias: int,
                   limite_profundidade: int, ignore: list[str]) -> list[dict[str, Any]]:
    repos: list[dict[str, Any]] = []
    agora = time.time()
    janela_commit = janela_ativo_dias * 86400
    janela_file = 7 * 86400

    for pasta in pastas:
        pasta = Path(pasta).resolve()
        if not pasta.exists():
            continue
        for git_dir in _walk_git_dirs(pasta, limite_profundidade, ignore):
            repo_path = git_dir.parent
            if _ativo(repo_path, agora, janela_commit, janela_file):
                repos.append({"nome": repo_path.name, "caminho": str(repo_path)})
    return repos[:30]


def _walk_git_dirs(root: Path, max_depth: int, ignore: list[str]):
    def rec(path: Path, depth: int):
        if depth > max_depth:
            return
        if path.name in ignore:
            return
        try:
            for child in path.iterdir():
                if not child.is_dir():
                    continue
                if child.name == ".git":
                    yield child
                    return
                if child.name.startswith("."):
                    continue
                if child.name in ignore:
                    continue
                yield from rec(child, depth + 1)
        except (PermissionError, OSError):
            return
    yield from rec(root, 0)


def _ativo(repo_path: Path, agora: float, janela_commit: float, janela_file: float) -> bool:
    ts = _ultimo_commit_ts(repo_path)
    if ts and (agora - ts) <= janela_commit:
        return True
    for f in repo_path.rglob("*"):
        if not f.is_file() or ".git" in f.parts:
            continue
        try:
            if (agora - f.stat().st_mtime) <= janela_file:
                return True
        except OSError:
            continue
    return False


def _ultimo_commit_ts(repo_path: Path) -> float | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(repo_path), "log", "-1", "--format=%ct"],
            capture_output=True, text=True, timeout=2,
        )
        if out.returncode == 0 and out.stdout.strip():
            return float(out.stdout.strip())
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


def detectar_stack(repo_path: Path) -> list[str]:
    s: list[str] = []
    if (repo_path / "pyproject.toml").exists() or (repo_path / "requirements.txt").exists():
        s.append("python")
    if (repo_path / "package.json").exists():
        s.append("node")
    if (repo_path / "Cargo.toml").exists():
        s.append("rust")
    if (repo_path / "go.mod").exists():
        s.append("go")
    return s


def ler_readme_resumo(repo_path: Path, max_chars: int = 500) -> str | None:
    for nome in ("README.md", "readme.md", "Readme.md"):
        p = repo_path / nome
        if p.exists():
            try:
                return p.read_text(encoding="utf-8")[:max_chars]
            except OSError:
                return None
    return None
```

- [ ] **Step 4: Rodar, passar**

```bash
pytest tests/test_forge_scan.py -v
```

Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add skills/obsidian-forge/scripts/scan_context.py tests/test_forge_scan.py
git commit -m "feat(forge): scan_context.detectar_repos/stack/readme + 7 testes"
```

---

### Task 2.3: `scan_context.py` — gerar notas + agregado

**Files:**
- Modify: `skills/obsidian-forge/scripts/scan_context.py`
- Modify: `tests/test_forge_scan.py`

- [ ] **Step 1: Apender testes**

Adicionar ao `tests/test_forge_scan.py`:

```python
from scan_context import gerar_nota_atomica, gerar_contexto_agregado  # noqa: E402


def test_gerar_nota_atomica(tmp_path: Path, fixture_atualizar_mtime: None) -> None:
    vault = tmp_path / "vault"
    (vault / "04 - Negocio" / "contexto").mkdir(parents=True)
    gerar_nota_atomica(vault_root=vault, repo_info={
        "nome": "repo-ativo-python",
        "caminho": str(FIX / "repo-ativo-python"),
    })
    nota = vault / "04 - Negocio" / "contexto" / "repo-ativo-python.md"
    assert nota.exists()
    from frontmatter import read_frontmatter
    meta, body = read_frontmatter(nota)
    assert meta["tipo"] == "contexto_projeto"
    assert meta["nome"] == "repo-ativo-python"
    assert "python" in meta["stack"]
    assert "repo-ativo-python" in body


def test_gerar_contexto_agregado(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    (vault / "04 - Negocio" / "contexto").mkdir(parents=True)
    gerar_contexto_agregado(
        vault_root=vault,
        repos=[{"nome": "a", "caminho": "/x/a"}, {"nome": "b", "caminho": "/x/b"}],
        fontes=[{"tipo": "pasta", "caminho": "/x", "ultima_varredura": "2026-04-22T14:00"}],
    )
    nota = vault / "04 - Negocio" / "_contexto.md"
    assert nota.exists()
    from frontmatter import read_frontmatter
    meta, body = read_frontmatter(nota)
    assert meta["projetos_ativos"] == 2
    assert "a" in body and "b" in body
```

- [ ] **Step 2: Implementar (apender ao `scan_context.py`)**

```python
import sys
sys.path.insert(0, str(Path(__file__).parent))
from frontmatter import write_frontmatter  # noqa: E402


def _ultimo_commit_detalhes(repo_path: Path) -> tuple[str, str, str] | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(repo_path), "log", "-1", "--format=%h|%s|%cI"],
            capture_output=True, text=True, timeout=2,
        )
        if out.returncode == 0 and out.stdout.strip():
            parts = out.stdout.strip().split("|", 2)
            if len(parts) == 3:
                return parts[0], parts[1], parts[2]
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


def gerar_nota_atomica(*, vault_root: Path, repo_info: dict[str, Any]) -> Path:
    repo_path = Path(repo_info["caminho"])
    stack = detectar_stack(repo_path)
    readme = ler_readme_resumo(repo_path)
    commit = _ultimo_commit_detalhes(repo_path)
    agora = datetime.now().isoformat(timespec="seconds")

    meta: dict[str, Any] = {
        "tipo": "contexto_projeto",
        "nome": repo_info["nome"],
        "caminho": str(repo_path),
        "stack": stack,
        "status": "ativo",
        "atualizado": agora,
    }
    if commit:
        meta["ultimo_commit"] = commit[2]
        meta["ultimo_commit_hash"] = commit[0]

    body_parts = [f"# {repo_info['nome']}\n"]
    if readme:
        body_parts.append(f"## O que é\n\n{readme.strip()}\n")
    if stack:
        body_parts.append(f"## Stack detectada\n\n{', '.join(stack)}.\n")
    if commit:
        body_parts.append(f"## Último commit\n\n`{commit[0]}` — {commit[1]}\n")
    body = "\n".join(body_parts)

    alvo = vault_root / "04 - Negocio" / "contexto" / f"{repo_info['nome']}.md"
    alvo.parent.mkdir(parents=True, exist_ok=True)
    write_frontmatter(alvo, meta, body)
    return alvo


def gerar_contexto_agregado(*, vault_root: Path, repos: list[dict], fontes: list[dict]) -> Path:
    agora = datetime.now().isoformat(timespec="seconds")
    meta = {
        "tipo": "contexto",
        "atualizado": agora,
        "fontes": fontes,
        "projetos_ativos": len(repos),
    }
    lista = "\n".join(f"- [[{r['nome']}]] — `{r['caminho']}`" for r in repos)
    stacks: set[str] = set()
    for r in repos:
        stacks.update(detectar_stack(Path(r["caminho"])))
    stacks_line = ", ".join(sorted(stacks)) if stacks else "—"
    body = f"# Contexto vivo\n\nAtualizado em {agora}.\n\n## Projetos em construção\n\n{lista}\n\n## Stack em uso\n\n{stacks_line}\n"
    alvo = vault_root / "04 - Negocio" / "_contexto.md"
    alvo.parent.mkdir(parents=True, exist_ok=True)
    write_frontmatter(alvo, meta, body)
    return alvo
```

- [ ] **Step 3: Rodar, passar**

```bash
pytest tests/test_forge_scan.py -v
```

Expected: 9 passed.

- [ ] **Step 4: Commit**

```bash
git add skills/obsidian-forge/scripts/scan_context.py tests/test_forge_scan.py
git commit -m "feat(forge): gerar_nota_atomica + gerar_contexto_agregado"
```

---

### Task 2.4: `scan_context.py` — `scan()` orquestrador + `init_config`

**Files:**
- Modify: `skills/obsidian-forge/scripts/scan_context.py`
- Modify: `tests/test_forge_scan.py`

- [ ] **Step 1: Apender testes**

```python
from scan_context import scan, init_config  # noqa: E402


def test_scan_end_to_end(tmp_path: Path, fixture_atualizar_mtime: None) -> None:
    vault = tmp_path / "vault"
    (vault / "04 - Negocio").mkdir(parents=True)
    init_config(vault_root=vault, pastas=[str(FIX)])
    result = scan(vault_root=vault, silent=True)
    assert result["projetos_ativos"] >= 2
    assert (vault / "04 - Negocio" / "_contexto.md").exists()


def test_init_config_grava(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    (vault / "04 - Negocio").mkdir(parents=True)
    init_config(vault_root=vault, pastas=["/a", "/b"])
    cfg = vault / "04 - Negocio" / "_config-scan.md"
    from frontmatter import read_frontmatter
    meta, _ = read_frontmatter(cfg)
    assert meta["pastas_observadas"] == ["/a", "/b"]
    assert meta["janela_ativo_dias"] == 30
```

- [ ] **Step 2: Implementar (apender ao `scan_context.py`)**

```python
from frontmatter import read_frontmatter  # noqa: E402


def init_config(*, vault_root: Path, pastas: list[str]) -> Path:
    meta = {
        "tipo": "config_scan",
        "pastas_observadas": pastas,
        "janela_ativo_dias": 30,
        "limite_profundidade": 3,
        "hook_sessionstart_ativo": False,
        "timeout_hook_s": 5,
        "ignore": ["node_modules", ".venv", "__pycache__", "dist", "build", ".next", "target"],
    }
    body = "# Config do scanner\n\nEdite `pastas_observadas`.\n"
    alvo = vault_root / "04 - Negocio" / "_config-scan.md"
    alvo.parent.mkdir(parents=True, exist_ok=True)
    write_frontmatter(alvo, meta, body)
    return alvo


def _ler_config(vault_root: Path) -> dict[str, Any] | None:
    cfg = vault_root / "04 - Negocio" / "_config-scan.md"
    if not cfg.exists():
        return None
    meta, _ = read_frontmatter(cfg)
    return meta


def scan(*, vault_root: Path, silent: bool = False, quick: bool = False) -> dict[str, Any]:
    config = _ler_config(vault_root)
    if config is None:
        raise FileNotFoundError(
            f"_config-scan.md ausente em {vault_root}. Rode `forge scan --init`."
        )
    pastas = [Path(p).expanduser() for p in config.get("pastas_observadas", [])]
    repos = detectar_repos(
        pastas=pastas,
        janela_ativo_dias=int(config.get("janela_ativo_dias", 30)),
        limite_profundidade=int(config.get("limite_profundidade", 3)),
        ignore=list(config.get("ignore", [])),
    )
    for r in repos:
        gerar_nota_atomica(vault_root=vault_root, repo_info=r)
    fontes = [{"tipo": "pasta", "caminho": str(p),
               "ultima_varredura": datetime.now().isoformat(timespec="seconds")}
              for p in pastas]
    gerar_contexto_agregado(vault_root=vault_root, repos=repos, fontes=fontes)
    resumo = {"projetos_ativos": len(repos), "repos": [r["nome"] for r in repos]}
    if not silent:
        print(f"[forge-scan] {len(repos)} projetos ativos.")
        for r in repos:
            print(f"  · {r['nome']}  ({r['caminho']})")
    return resumo
```

- [ ] **Step 3: Rodar, passar**

```bash
pytest tests/test_forge_scan.py -v
```

Expected: 11 passed.

- [ ] **Step 4: Commit**

```bash
git add skills/obsidian-forge/scripts/scan_context.py tests/test_forge_scan.py
git commit -m "feat(forge): scan() orquestrador + init_config"
```

---

### Task 2.5: `forge.py` — dispatcher + subcomando `scan`

**Files:**
- Create: `skills/obsidian-forge/scripts/forge.py`

- [ ] **Step 1: Implementar**

```python
#!/usr/bin/env python3
"""CLI entry do obsidian-forge."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _detectar_vault(start: Path | None = None) -> Path:
    p = (start or Path.cwd()).resolve()
    for cand in [p, *p.parents]:
        if (cand / ".obsidian-master" / "marker.json").exists():
            return cand
    raise FileNotFoundError("Vault nao encontrado. Use --vault PATH.")


def cmd_scan(args: argparse.Namespace) -> int:
    sys.path.insert(0, str(Path(__file__).parent))
    from scan_context import scan, init_config
    vault = Path(args.vault).resolve() if args.vault else _detectar_vault()

    if args.init:
        print("Quais pastas o forge deve vigiar? (ENTER duplo termina)")
        pastas: list[str] = []
        while True:
            try:
                linha = input("> ").strip()
            except EOFError:
                break
            if not linha:
                break
            p = Path(linha).expanduser()
            if not p.exists():
                print(f"  pasta inexistente: {p}")
                continue
            pastas.append(str(p))
        if not pastas:
            print("Nenhuma pasta. Abortado.")
            return 1
        cfg = init_config(vault_root=vault, pastas=pastas)
        print(f"Config salvo: {cfg}")
        return 0

    if args.add:
        from frontmatter import read_frontmatter, write_frontmatter
        cfg_path = vault / "04 - Negocio" / "_config-scan.md"
        if not cfg_path.exists():
            print("Rode --init antes.")
            return 1
        meta, body = read_frontmatter(cfg_path)
        pastas = list(meta.get("pastas_observadas", []))
        if args.add not in pastas:
            pastas.append(args.add)
            meta["pastas_observadas"] = pastas
            write_frontmatter(cfg_path, meta, body)
            print(f"Adicionado: {args.add}")
        return 0

    try:
        scan(vault_root=vault, silent=args.silent, quick=args.quick)
        return 0
    except FileNotFoundError as e:
        print(f"Erro: {e}")
        return 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="forge")
    p.add_argument("--vault")
    sub = p.add_subparsers(dest="cmd", required=True)
    ps = sub.add_parser("scan")
    ps.add_argument("--init", action="store_true")
    ps.add_argument("--silent", action="store_true")
    ps.add_argument("--quick", action="store_true")
    ps.add_argument("--add")
    ps.set_defaults(func=cmd_scan)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Testar help**

```bash
python3 skills/obsidian-forge/scripts/forge.py scan --help
```

Expected: mostra flags `--init`, `--silent`, `--quick`, `--add`.

- [ ] **Step 3: Commit**

```bash
git add skills/obsidian-forge/scripts/forge.py
git commit -m "feat(forge): forge.py dispatcher + subcomando scan"
```

---

# Wave 3 — Módulo 2 Arquiteto

### Task 3.1: `plan_business.py` — state management

**Files:**
- Create: `skills/obsidian-forge/scripts/plan_business.py`
- Test: `tests/test_forge_plan_state.py`

- [ ] **Step 1: Teste**

```python
"""State management da entrevista plan_business."""
from __future__ import annotations

import sys
from pathlib import Path

FORGE_DIR = Path(__file__).parent.parent / "skills" / "obsidian-forge" / "scripts"
sys.path.insert(0, str(FORGE_DIR))

from plan_business import ler_estado, salvar_estado, limpar_estado, proximo_passo  # noqa: E402


def test_estado_vazio(tmp_path: Path) -> None:
    assert proximo_passo(tmp_path) == 1


def test_salvar_e_ler(tmp_path: Path) -> None:
    salvar_estado(tmp_path, {"passo_atual": 2, "resp_1": {"produto": "x"}})
    e = ler_estado(tmp_path)
    assert e["passo_atual"] == 2
    assert e["resp_1"]["produto"] == "x"


def test_proximo_passo_apos_2(tmp_path: Path) -> None:
    salvar_estado(tmp_path, {"passo_atual": 2})
    assert proximo_passo(tmp_path) == 3


def test_limpar(tmp_path: Path) -> None:
    salvar_estado(tmp_path, {"passo_atual": 3})
    limpar_estado(tmp_path)
    assert proximo_passo(tmp_path) == 1
```

- [ ] **Step 2: Implementar**

`skills/obsidian-forge/scripts/plan_business.py`:

```python
"""Modulo 2 — arquiteto de negocio."""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))


def _state_path(vault_root: Path) -> Path:
    return vault_root / "04 - Negocio" / ".forge-state.json"


def ler_estado(vault_root: Path) -> dict[str, Any]:
    p = _state_path(vault_root)
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def salvar_estado(vault_root: Path, estado: dict[str, Any]) -> None:
    p = _state_path(vault_root)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(estado, indent=2, ensure_ascii=False), encoding="utf-8")


def limpar_estado(vault_root: Path) -> None:
    p = _state_path(vault_root)
    if p.exists():
        p.unlink()


def proximo_passo(vault_root: Path) -> int:
    return min(int(ler_estado(vault_root).get("passo_atual", 0)) + 1, 5)
```

- [ ] **Step 3: Rodar, passar**

```bash
pytest tests/test_forge_plan_state.py -v
```

Expected: 4 passed.

- [ ] **Step 4: Commit**

```bash
git add skills/obsidian-forge/scripts/plan_business.py tests/test_forge_plan_state.py
git commit -m "feat(forge): plan_business state + 4 testes"
```

---

### Task 3.2: `plan_business.py` — render templates

**Files:**
- Modify: `skills/obsidian-forge/scripts/plan_business.py`
- Test: `tests/test_forge_templates.py`

- [ ] **Step 1: Teste**

```python
"""Testes de render de templates."""
from __future__ import annotations

import sys
from pathlib import Path

FORGE_DIR = Path(__file__).parent.parent / "skills" / "obsidian-forge" / "scripts"
sys.path.insert(0, str(FORGE_DIR))

from plan_business import renderizar_plano, renderizar_metas, renderizar_acoes  # noqa: E402
from frontmatter import read_frontmatter  # noqa: E402


def test_renderizar_plano(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    (vault / "04 - Negocio").mkdir(parents=True)
    renderizar_plano(vault_root=vault, respostas={
        "ciclo": "2026-Q2", "produto": "P", "problema": "Q", "pessoa": "R",
        "produto_prosa": "p", "problema_prosa": "p", "pessoa_prosa": "p",
        "valor_unitario": 2500,
        "resultado_potencial": "a", "tempo_economizado": "b",
        "esforco_reduzido": "c", "producao_aumentada": "d",
    })
    meta, body = read_frontmatter(vault / "04 - Negocio" / "_plano.md")
    assert meta["produto"] == "P"
    assert meta["protected"] is True
    assert "P" in body


def test_renderizar_metas(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    (vault / "04 - Negocio").mkdir(parents=True)
    renderizar_metas(vault_root=vault, respostas={
        "ciclo": "2026-Q2", "objetivo_titulo": "R$ 10k", "valor_alvo": 10000,
        "prazo": "2026-06-30", "valor_unitario": 2500,
        "clientes_alvo": 4, "reunioes_alvo": 40, "reunioes_taxa": 0.10,
        "leads_alvo": 400, "leads_taxa": 0.10,
        "alcance_alvo": 4000, "alcance_fonte": "conteudo",
    })
    meta, _ = read_frontmatter(vault / "04 - Negocio" / "_metas.md")
    assert meta["funil"][0]["etapa"] == "clientes"
    assert meta["funil"][0]["alvo"] == 4
    assert meta["objetivo"]["valor_atual"] == 0


def test_renderizar_acoes_cria_7(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    (vault / "04 - Negocio" / "acoes").mkdir(parents=True)
    renderizar_acoes(vault_root=vault)
    arquivos = sorted((vault / "04 - Negocio" / "acoes").glob("*.md"))
    assert len(arquivos) == 7
    assert any("01-segundo-cerebro" in a.name for a in arquivos)
    assert any("07-admin-financeiro" in a.name for a in arquivos)
```

- [ ] **Step 2: Implementar (apender ao `plan_business.py`)**

```python
from frontmatter import read_frontmatter, write_frontmatter, serialize_frontmatter  # noqa: E402

TEMPLATES_DIR = Path(__file__).parent / "templates"


def _render_template(template_path: Path, ctx: dict[str, Any]) -> str:
    text = template_path.read_text(encoding="utf-8")
    for k, v in ctx.items():
        text = text.replace("{{" + k + "}}", str(v))
    return text


def renderizar_plano(*, vault_root: Path, respostas: dict[str, Any]) -> Path:
    ctx = {**respostas, "atualizado": datetime.now().isoformat(timespec="seconds")}
    text = _render_template(TEMPLATES_DIR / "plano.md", ctx)
    alvo = vault_root / "04 - Negocio" / "_plano.md"
    alvo.parent.mkdir(parents=True, exist_ok=True)
    alvo.write_text(text, encoding="utf-8")
    return alvo


def renderizar_metas(*, vault_root: Path, respostas: dict[str, Any]) -> Path:
    ctx = {
        **respostas,
        "atualizado": datetime.now().isoformat(timespec="seconds"),
        "reunioes_taxa_pct": int(respostas["reunioes_taxa"] * 100),
        "leads_taxa_pct": int(respostas["leads_taxa"] * 100),
    }
    text = _render_template(TEMPLATES_DIR / "metas.md", ctx)
    alvo = vault_root / "04 - Negocio" / "_metas.md"
    alvo.parent.mkdir(parents=True, exist_ok=True)
    alvo.write_text(text, encoding="utf-8")
    return alvo


def renderizar_acoes(*, vault_root: Path) -> list[Path]:
    agora = datetime.now().isoformat(timespec="seconds")
    src_dir = TEMPLATES_DIR / "acoes"
    alvo_dir = vault_root / "04 - Negocio" / "acoes"
    alvo_dir.mkdir(parents=True, exist_ok=True)
    criados: list[Path] = []
    for src in sorted(src_dir.glob("*.md")):
        text = _render_template(src, {"atualizado": agora})
        alvo = alvo_dir / src.name
        alvo.write_text(text, encoding="utf-8")
        criados.append(alvo)
    return criados
```

- [ ] **Step 3: Rodar, passar**

```bash
pytest tests/test_forge_templates.py -v
```

Expected: 3 passed.

- [ ] **Step 4: Commit**

```bash
git add skills/obsidian-forge/scripts/plan_business.py tests/test_forge_templates.py
git commit -m "feat(forge): renderizar plano/metas/acoes + 3 testes"
```

---

### Task 3.3: `forge.py` — subcomando `plan` + `plan-save-*`

**Files:**
- Modify: `skills/obsidian-forge/scripts/forge.py`

- [ ] **Step 1: Apender commands ao `forge.py`** (antes de `build_parser`)

```python
def cmd_plan(args: argparse.Namespace) -> int:
    sys.path.insert(0, str(Path(__file__).parent))
    from plan_business import ler_estado, limpar_estado
    vault = Path(args.vault).resolve() if args.vault else _detectar_vault()

    if args.status:
        plano = vault / "04 - Negocio" / "_plano.md"
        if not plano.exists():
            print("Nenhum plano ativo. Rode `forge plan`.")
            return 0
        from frontmatter import read_frontmatter
        meta, _ = read_frontmatter(plano)
        print(f"Plano · ciclo {meta.get('ciclo')} · {meta.get('status')}")
        print(f"  Produto: {meta.get('produto')}")
        print(f"  Problema: {meta.get('problema')}")
        print(f"  Pessoa: {meta.get('pessoa')}")
        return 0

    if args.new_cycle:
        import shutil
        from datetime import datetime
        area = vault / "04 - Negocio"
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        arq = area / "acoes" / "_arquivados" / stamp
        arq.mkdir(parents=True, exist_ok=True)
        for f in ["_plano.md", "_metas.md"]:
            src = area / f
            if src.exists():
                shutil.move(str(src), str(arq / f))
        for f in (area / "acoes").glob("[0-9]*.md"):
            shutil.move(str(f), str(arq / f.name))
        limpar_estado(vault)
        print(f"Ciclo arquivado em {arq}.")
        return 0

    estado = ler_estado(vault)
    passo = estado.get("passo_atual", 0) + 1
    print(f"Estado: passo_atual={estado.get('passo_atual', 0)}. Proximo: {passo}.")
    print("Use --save-plano, --save-metas, --save-acoes (o Claude Code conduz o chat).")
    return 0


def cmd_plan_save_plano(args: argparse.Namespace) -> int:
    sys.path.insert(0, str(Path(__file__).parent))
    from plan_business import renderizar_plano, ler_estado, salvar_estado
    vault = Path(args.vault).resolve() if args.vault else _detectar_vault()
    respostas = json.loads(Path(args.respostas).read_text(encoding="utf-8"))
    renderizar_plano(vault_root=vault, respostas=respostas)
    e = ler_estado(vault)
    e["passo_atual"] = 2
    e["resp_plano"] = respostas
    salvar_estado(vault, e)
    print("OK _plano.md.")
    return 0


def cmd_plan_save_metas(args: argparse.Namespace) -> int:
    sys.path.insert(0, str(Path(__file__).parent))
    from plan_business import renderizar_metas, ler_estado, salvar_estado
    from math_funil import validar_funil, FunilInvalido
    vault = Path(args.vault).resolve() if args.vault else _detectar_vault()
    r = json.loads(Path(args.respostas).read_text(encoding="utf-8"))
    funil = [
        {"etapa": "clientes", "alvo": r["clientes_alvo"], "valor_unitario": r["valor_unitario"]},
        {"etapa": "reunioes", "alvo": r["reunioes_alvo"], "taxa_conversao": r["reunioes_taxa"]},
        {"etapa": "leads", "alvo": r["leads_alvo"], "taxa_conversao": r["leads_taxa"]},
        {"etapa": "alcance", "alvo": r["alcance_alvo"], "fonte": r["alcance_fonte"]},
    ]
    try:
        validar_funil(funil, valor_alvo=r["valor_alvo"])
    except FunilInvalido as exc:
        print(f"Validacao falhou: {exc}")
        return 1
    renderizar_metas(vault_root=vault, respostas=r)
    e = ler_estado(vault)
    e["passo_atual"] = 3
    e["resp_metas"] = r
    salvar_estado(vault, e)
    print("OK _metas.md.")
    return 0


def cmd_plan_save_acoes(args: argparse.Namespace) -> int:
    sys.path.insert(0, str(Path(__file__).parent))
    from plan_business import renderizar_acoes, ler_estado, salvar_estado
    vault = Path(args.vault).resolve() if args.vault else _detectar_vault()
    criados = renderizar_acoes(vault_root=vault)
    e = ler_estado(vault)
    e["passo_atual"] = 4
    salvar_estado(vault, e)
    print(f"OK {len(criados)} acoes criadas.")
    return 0
```

E em `build_parser`:

```python
    pp = sub.add_parser("plan")
    pp.add_argument("--status", action="store_true")
    pp.add_argument("--new-cycle", action="store_true")
    pp.set_defaults(func=cmd_plan)

    for nome, fn in [("plan-save-plano", cmd_plan_save_plano),
                     ("plan-save-metas", cmd_plan_save_metas),
                     ("plan-save-acoes", cmd_plan_save_acoes)]:
        sp = sub.add_parser(nome)
        if nome != "plan-save-acoes":
            sp.add_argument("--respostas", required=True)
        sp.set_defaults(func=fn)
```

- [ ] **Step 2: Testar help**

```bash
python3 skills/obsidian-forge/scripts/forge.py plan --help
python3 skills/obsidian-forge/scripts/forge.py plan-save-plano --help
```

- [ ] **Step 3: Commit**

```bash
git add skills/obsidian-forge/scripts/forge.py
git commit -m "feat(forge): subcomandos plan + plan-save-{plano,metas,acoes}"
```

---

### Task 3.4: Documentar entrevista no `SKILL.md`

**Files:**
- Modify: `skills/obsidian-forge/SKILL.md`

- [ ] **Step 1: Apender**

Ao final do `SKILL.md`:

````markdown

## Fluxo da entrevista `forge-plan` (Claude Code conduz no chat)

### Passo 1+2 — 3 Ps + Precificacao

1. Ler `_contexto.md` (se existir) pra personalizar.
2. Perguntar: Produto (1 frase), Problema, Pessoa.
3. Perguntar prosa estendida de cada um.
4. Perguntar valor unitario + 4 bases de precificacao.
5. Montar JSON e chamar:

```bash
python3 forge.py plan-save-plano --respostas /tmp/respostas-plano.json
```

### Passo 3 — Matematica

1. Perguntar: objetivo (titulo, valor_alvo, prazo), taxas de conversao, fonte de alcance.
2. Chamar `math_funil.derivar_funil` via script para obter funil calculado.
3. Mostrar funil ao user; se aprovado → chamar:

```bash
python3 forge.py plan-save-metas --respostas /tmp/respostas-metas.json
```

Se `validar_funil` retornar erro, Claude re-pergunta o que nao bate.

### Passo 4 — Acoes Macro

```bash
python3 forge.py plan-save-acoes
```

Cria os 7 arquivos. Claude pode depois ler cada um e sugerir personalizacoes.

### Estado parcial

`04 - Negocio/.forge-state.json` guarda `passo_atual` e respostas. Ao
re-executar, Claude le esse arquivo pra retomar.
````

- [ ] **Step 2: Commit**

```bash
git add skills/obsidian-forge/SKILL.md
git commit -m "docs(forge): SKILL.md com fluxo da entrevista"
```

---

# Wave 4 — Módulo 3 Dashboard

### Task 4.1: `dashboard.html` — esqueleto + CSS

**Files:**
- Create: `skills/obsidian-forge/scripts/dashboard.html`

- [ ] **Step 1: Criar arquivo com HTML + CSS + script placeholder**

```html
<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>forge · painel</title>
<link rel="preconnect" href="https://fonts.googleapis.com" />
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
<link href="https://fonts.googleapis.com/css2?family=Newsreader:wght@400;500;600&family=Inter:wght@400;500;600&display=swap" rel="stylesheet" />
<style>
  :root {
    --bg: #13110f; --bg-elev: #1a1815; --bg-card: #181613;
    --text: #eae3d2; --text-dim: #9a9186; --text-faint: #6a6359;
    --accent: #d4a24c; --accent-dim: #8a6c34;
    --border: #2a2620; --ok: #8fb174;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  html, body { background: var(--bg); color: var(--text); font-family: 'Inter', system-ui, sans-serif; font-size: 15px; line-height: 1.55; }
  button { font: inherit; color: var(--accent); background: none; border: 1px solid var(--accent-dim); padding: 8px 14px; border-radius: 3px; cursor: pointer; }
  button:hover { background: var(--accent); color: var(--bg); }
  .container { max-width: 900px; margin: 0 auto; padding: 48px 32px; }
  header.topo { padding-bottom: 32px; border-bottom: 1px solid var(--border); margin-bottom: 48px; }
  .brand { font-family: 'Newsreader', serif; font-style: italic; font-size: 42px; letter-spacing: -0.02em; }
  .brand::after { content: '.'; color: var(--accent); }
  .status-linha { color: var(--text-dim); font-size: 14px; margin-top: 6px; }
  section.card { background: var(--bg-card); border: 1px solid var(--border); border-radius: 6px; padding: 28px; margin-bottom: 24px; }
  section.card h2 { font-family: 'Newsreader', serif; font-weight: 500; font-size: 22px; margin-bottom: 18px; }
  .onboarding { text-align: center; padding: 80px 32px; }
  .onboarding h1 { font-family: 'Newsreader', serif; font-style: italic; font-size: 56px; margin-bottom: 12px; }
  .onboarding h1::after { content: '.'; color: var(--accent); }
  .onboarding p { color: var(--text-dim); margin-bottom: 32px; max-width: 480px; margin-left: auto; margin-right: auto; }
  .barra { display: flex; align-items: center; gap: 14px; margin: 10px 0; font-size: 14px; }
  .barra .trilho { flex: 1; height: 8px; background: var(--bg-elev); border-radius: 4px; overflow: hidden; }
  .barra .preenchido { height: 100%; background: var(--accent); }
  .acao { display: flex; align-items: center; gap: 12px; padding: 12px 0; border-bottom: 1px solid var(--border); }
  .acao:last-child { border-bottom: 0; }
  .acao .check { font-size: 18px; color: var(--text-faint); cursor: pointer; user-select: none; }
  .acao .check.ok { color: var(--ok); }
  .acao .titulo { flex: 1; }
  .acao .progresso { color: var(--text-dim); font-size: 13px; font-feature-settings: 'tnum'; }
  .modal-bg { position: fixed; inset: 0; background: rgba(0,0,0,.7); display: none; align-items: center; justify-content: center; }
  .modal-bg.ativo { display: flex; }
  .modal { background: var(--bg-elev); border: 1px solid var(--border); border-radius: 6px; padding: 32px; min-width: 400px; max-width: 560px; }
  .modal h3 { font-family: 'Newsreader', serif; margin-bottom: 18px; }
  .modal label { display: block; margin-bottom: 12px; color: var(--text-dim); font-size: 13px; }
  .modal input, .modal select { width: 100%; padding: 8px 10px; background: var(--bg); color: var(--text); border: 1px solid var(--border); border-radius: 3px; font: inherit; margin-top: 4px; }
  .modal .botoes { display: flex; gap: 12px; justify-content: flex-end; margin-top: 22px; }
  strong { font-weight: 600; color: var(--text); }
  em { color: var(--text-dim); }
</style>
</head>
<body>
  <div id="onboarding" class="onboarding">
    <h1>forge</h1>
    <p>Painel de execucao de negocio. Le seu vault Obsidian localmente. Zero nuvem.</p>
    <button id="btn-escolher-vault">Escolher meu vault Obsidian</button>
  </div>

  <div id="app" class="container" style="display:none">
    <header class="topo">
      <div class="brand">forge</div>
      <div class="status-linha" id="status-linha">carregando...</div>
    </header>
    <section class="card" id="s-3ps"><h2>Os 3 Ps</h2><div id="conteudo-3ps"></div></section>
    <section class="card" id="s-metas"><h2>Matematica do resultado</h2><div id="conteudo-metas"></div><button id="btn-registrar">+ registrar progresso</button></section>
    <section class="card" id="s-acoes"><h2>Acoes macro</h2><div id="conteudo-acoes"></div></section>
    <section class="card" id="s-next"><h2>Proximo passo sugerido</h2><div id="conteudo-next"></div></section>
    <section class="card" id="s-contexto"><h2>Contexto vivo</h2><div id="conteudo-contexto"></div></section>
  </div>

  <div class="modal-bg" id="modal-bg">
    <div class="modal">
      <h3>Registrar progresso</h3>
      <label>Tipo<select id="modal-tipo">
        <option value="lead_captado">Lead captado</option>
        <option value="reuniao_realizada">Reuniao realizada</option>
        <option value="cliente_fechado">Cliente fechado</option>
        <option value="conteudo_publicado">Conteudo publicado</option>
        <option value="alcance_manual">Alcance manual</option>
      </select></label>
      <label>Quantidade / valor (opcional)<input type="number" id="modal-qtd" value="1" /></label>
      <label>Nota (opcional)<input type="text" id="modal-nota" /></label>
      <div class="botoes"><button id="modal-cancelar">Cancelar</button><button id="modal-salvar">Salvar</button></div>
    </div>
  </div>

  <script>/* preenchido na proxima task */
    document.getElementById('btn-escolher-vault').addEventListener('click', () => {
      alert('FS Access ainda nao ativo. Proxima task implementa.');
    });
  </script>
</body>
</html>
```

- [ ] **Step 2: Testar visual**

```bash
python3 -m http.server 4712 --directory skills/obsidian-forge/scripts &
open http://localhost:4712/dashboard.html
# conferir layout, matar server
kill %1
```

- [ ] **Step 3: Commit**

```bash
git add skills/obsidian-forge/scripts/dashboard.html
git commit -m "feat(forge): dashboard.html skeleton (onboarding + 5 cards)"
```

---

### Task 4.2: `dashboard.html` — JS: FS Access + leitura + render seguro

**Files:**
- Modify: `skills/obsidian-forge/scripts/dashboard.html`

Nota importante: **todo render usa `createElement` + `textContent` + `replaceChildren`**. Zero `.innerHTML`. Zero strings HTML construídas de conteúdo de arquivo.

- [ ] **Step 1: Substituir o bloco `<script>` placeholder pelo completo**

No dashboard.html, trocar o bloco `<script>...</script>` atual por:

```html
<script>
/* ========= Config ========= */
const AREA = '04 - Negocio';
const DB_NAME = 'forge-vault';
const DB_KEY = 'dirHandle';

/* ========= IndexedDB ========= */
function openDb() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, 1);
    req.onupgradeneeded = () => req.result.createObjectStore('store');
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}
async function saveHandle(h) {
  const db = await openDb();
  const tx = db.transaction('store', 'readwrite');
  tx.objectStore('store').put(h, DB_KEY);
  return new Promise((r) => tx.oncomplete = r);
}
async function loadHandle() {
  const db = await openDb();
  const tx = db.transaction('store', 'readonly');
  return new Promise((resolve) => {
    const r = tx.objectStore('store').get(DB_KEY);
    r.onsuccess = () => resolve(r.result || null);
  });
}

/* ========= FS Access ========= */
async function pickVault() {
  const handle = await window.showDirectoryPicker({ id: 'forge-vault', mode: 'readwrite' });
  await saveHandle(handle);
  return handle;
}
async function ensurePermission(handle) {
  const o = { mode: 'readwrite' };
  if ((await handle.queryPermission(o)) === 'granted') return true;
  return (await handle.requestPermission(o)) === 'granted';
}
async function getArea(vault) { return vault.getDirectoryHandle(AREA); }
async function readText(dir, name) {
  try {
    const fh = await dir.getFileHandle(name);
    const f = await fh.getFile();
    return await f.text();
  } catch { return null; }
}
async function writeText(dir, name, text) {
  const fh = await dir.getFileHandle(name, { create: true });
  const w = await fh.createWritable();
  await w.write(text);
  await w.close();
}

/* ========= Frontmatter parse/serialize ========= */
function parseFrontmatter(text) {
  const m = (text || '').match(/^---\s*\n([\s\S]*?)^---\s*\n?([\s\S]*)$/m);
  if (!m) return { meta: {}, body: text || '' };
  try { return { meta: parseYaml(m[1]), body: m[2] }; }
  catch { return { meta: {}, body: text || '' }; }
}

function parseYaml(raw) {
  const lines = raw.split('\n').filter(l => l.trim() !== '' && !l.trim().startsWith('#'));
  const root = {};
  const stack = [{ indent: -1, obj: root, lastKey: null }];
  for (const line of lines) {
    const indent = line.length - line.trimStart().length;
    const trimmed = line.trim();
    while (stack[stack.length - 1].indent >= indent) stack.pop();
    const top = stack[stack.length - 1];
    if (trimmed.startsWith('- ')) {
      const rest = trimmed.slice(2);
      if (rest.includes(':') && !rest.startsWith('"')) {
        const [k, ...v] = rest.split(':');
        const obj = { [k.trim()]: coerce(v.join(':').trim()) };
        if (!Array.isArray(top.obj[top.lastKey])) top.obj[top.lastKey] = [];
        top.obj[top.lastKey].push(obj);
        stack.push({ indent, obj, lastKey: k.trim() });
      } else {
        if (!Array.isArray(top.obj[top.lastKey])) top.obj[top.lastKey] = [];
        top.obj[top.lastKey].push(coerce(rest));
      }
    } else {
      const colon = trimmed.indexOf(':');
      const k = trimmed.slice(0, colon).trim();
      const v = trimmed.slice(colon + 1).trim();
      top.lastKey = k;
      if (v === '') {
        top.obj[k] = {};
        stack.push({ indent, obj: top.obj[k], lastKey: null });
      } else {
        top.obj[k] = coerce(v);
      }
    }
  }
  return root;
}

function coerce(v) {
  if (v === '' || v == null) return null;
  if (v === 'true') return true;
  if (v === 'false') return false;
  if (/^-?\d+$/.test(v)) return parseInt(v, 10);
  if (/^-?\d+\.\d+$/.test(v)) return parseFloat(v);
  if ((v.startsWith('"') && v.endsWith('"')) || (v.startsWith("'") && v.endsWith("'"))) return v.slice(1, -1);
  return v;
}

function serializeFrontmatter(meta, body) {
  return `---\n${dumpYaml(meta)}---\n\n${(body || '').trimStart()}`;
}
function dumpYaml(obj, indent = 0) {
  const pad = '  '.repeat(indent);
  let out = '';
  for (const k of Object.keys(obj)) {
    const v = obj[k];
    if (Array.isArray(v)) {
      out += `${pad}${k}:\n`;
      for (const item of v) {
        if (typeof item === 'object' && item !== null) {
          const ks = Object.keys(item);
          out += `${pad}  - ${ks[0]}: ${fmtScalar(item[ks[0]])}\n`;
          for (let i = 1; i < ks.length; i++) out += `${pad}    ${ks[i]}: ${fmtScalar(item[ks[i]])}\n`;
        } else {
          out += `${pad}  - ${fmtScalar(item)}\n`;
        }
      }
    } else if (typeof v === 'object' && v !== null) {
      out += `${pad}${k}:\n${dumpYaml(v, indent + 1)}`;
    } else {
      out += `${pad}${k}: ${fmtScalar(v)}\n`;
    }
  }
  return out;
}
function fmtScalar(v) {
  if (v == null) return '';
  if (typeof v === 'string' && /[:#\[\]{},]/.test(v)) return `"${v.replace(/"/g, '\\"')}"`;
  return String(v);
}

/* ========= Render (DOM seguro) ========= */
const $ = (id) => document.getElementById(id);

function makeDiv(cls, text) {
  const d = document.createElement('div');
  if (cls) d.className = cls;
  if (text != null) d.textContent = text;
  return d;
}
function makeSpan(cls, text) {
  const s = document.createElement('span');
  if (cls) s.className = cls;
  if (text != null) s.textContent = text;
  return s;
}
function appendLabelValue(parent, label, value) {
  const row = makeDiv();
  row.appendChild(makeSpan(null, label + ': '));
  const strong = document.createElement('strong');
  strong.textContent = value || '—';
  row.appendChild(strong);
  parent.appendChild(row);
}

function render3Ps(el, d) {
  el.replaceChildren();
  const p = d.plano.meta;
  if (!p.produto) {
    const em = document.createElement('em');
    em.textContent = 'Rode `forge plan` pra definir.';
    el.appendChild(em);
    return;
  }
  appendLabelValue(el, 'Produto', p.produto);
  appendLabelValue(el, 'Problema', p.problema);
  appendLabelValue(el, 'Pessoa', p.pessoa);
}

function renderMetas(el, d) {
  el.replaceChildren();
  const m = d.metas.meta;
  if (!m.funil) {
    const em = document.createElement('em');
    em.textContent = 'Sem metas definidas.';
    el.appendChild(em);
    return;
  }
  const ag = agregarProgresso(d.progressoEventos);
  for (const e of m.funil) {
    const atual = ag[e.etapa] ?? 0;
    const alvo = e.alvo || 0;
    const pct = Math.min(100, (atual / Math.max(alvo, 1)) * 100);
    const row = makeDiv('barra');
    row.appendChild(makeSpan(null, e.etapa));
    const trilho = makeDiv('trilho');
    const pre = makeDiv('preenchido');
    pre.style.width = pct + '%';
    trilho.appendChild(pre);
    row.appendChild(trilho);
    row.appendChild(makeSpan(null, `${atual}/${alvo}`));
    el.appendChild(row);
  }
}

function renderAcoes(el, d) {
  el.replaceChildren();
  for (const a of d.acoes) {
    const row = makeDiv('acao');
    const check = makeSpan('check' + (a.meta.status === 'concluido' ? ' ok' : ''),
                           a.meta.status === 'concluido' ? '✓' : '☐');
    check.dataset.slug = a.meta.slug || '';
    row.appendChild(check);
    row.appendChild(makeSpan('titulo', `${a.meta.ordem}. ${a.meta.titulo || ''}`));
    row.appendChild(makeSpan('progresso', `${a.meta.tarefas_feitas || 0}/${a.meta.tarefas_totais || 0}`));
    el.appendChild(row);
  }
}

function renderProximoPasso(el, d) {
  el.replaceChildren();
  const row = makeDiv();
  for (const a of d.acoes) {
    if (a.meta.status === 'em_andamento') {
      const m = (a.body || '').match(/- \[ \] (.+)/);
      if (m) {
        const strong = document.createElement('strong');
        strong.textContent = (a.meta.titulo || '') + ': ';
        row.appendChild(strong);
        row.appendChild(document.createTextNode(m[1]));
        el.appendChild(row);
        return;
      }
    }
  }
  for (const a of d.acoes) {
    if (a.meta.status === 'pendente') {
      const m = (a.body || '').match(/- \[ \] (.+)/);
      if (m) {
        const strong = document.createElement('strong');
        strong.textContent = (a.meta.titulo || '') + ': ';
        row.appendChild(strong);
        row.appendChild(document.createTextNode(m[1]));
        el.appendChild(row);
        return;
      }
    }
  }
  row.textContent = 'Todos os marcos feitos. Inicie novo ciclo.';
  el.appendChild(row);
}

function renderContexto(el, d) {
  el.replaceChildren();
  const n = d.contexto.meta.projetos_ativos || 0;
  el.appendChild(makeDiv(null, `${n} projetos ativos detectados.`));
  const pequeno = makeDiv();
  pequeno.style.color = 'var(--text-dim)';
  pequeno.style.fontSize = '13px';
  pequeno.style.marginTop = '8px';
  const primeirasLinhas = (d.contexto.body || '').split('\n').slice(0, 10);
  for (const linha of primeirasLinhas) {
    const p = document.createElement('div');
    p.textContent = linha;
    pequeno.appendChild(p);
  }
  el.appendChild(pequeno);
}

function statusLinha(d) {
  const ciclo = d.plano.meta.ciclo || '—';
  const vAtual = d.metas.meta.objetivo?.valor_atual ?? 0;
  const vAlvo = d.metas.meta.objetivo?.valor_alvo ?? 0;
  return `Ciclo ${ciclo} · R$ ${vAtual} / R$ ${vAlvo}`;
}

function agregarProgresso(eventos) {
  const c = { clientes: 0, reunioes: 0, leads: 0, alcance: 0 };
  for (const ev of eventos) {
    if (ev.tipo === 'cliente_fechado') c.clientes++;
    else if (ev.tipo === 'reuniao_realizada') c.reunioes++;
    else if (ev.tipo === 'lead_captado') c.leads++;
    else if (ev.tipo === 'conteudo_publicado') c.alcance++;
    else if (ev.tipo === 'alcance_manual') {
      const m = (ev.detalhes || '').match(/(\d+)/);
      c.alcance += m ? parseInt(m[1], 10) : 0;
    }
  }
  return c;
}

/* ========= Carga + boot ========= */
async function carregarDados(area) {
  const plano = parseFrontmatter(await readText(area, '_plano.md') || '');
  const metas = parseFrontmatter(await readText(area, '_metas.md') || '');
  const contexto = parseFrontmatter(await readText(area, '_contexto.md') || '');

  const acoesDir = await area.getDirectoryHandle('acoes').catch(() => null);
  const acoes = [];
  if (acoesDir) {
    for await (const [name, h] of acoesDir.entries()) {
      if (h.kind !== 'file' || !name.match(/^\d{2}-.+\.md$/)) continue;
      const { meta, body } = parseFrontmatter(await readText(acoesDir, name));
      acoes.push({ filename: name, meta, body });
    }
    acoes.sort((a, b) => a.filename.localeCompare(b.filename));
  }

  const progressoDir = await area.getDirectoryHandle('progresso').catch(() => null);
  const progressoEventos = [];
  if (progressoDir) {
    for await (const [name, h] of progressoDir.entries()) {
      if (h.kind !== 'file' || !name.match(/^\d{4}-\d{2}-\d{2}\.md$/)) continue;
      const { body } = parseFrontmatter(await readText(progressoDir, name));
      for (const linha of (body || '').split('\n')) {
        const m = linha.match(/^- \d{2}:\d{2} — (\w+)(?:\s*\((.*)\))?/);
        if (m) progressoEventos.push({ tipo: m[1], detalhes: m[2] });
      }
    }
  }

  return { plano, metas, contexto, acoes, progressoEventos };
}

async function renderApp(vault) {
  $('onboarding').style.display = 'none';
  $('app').style.display = 'block';
  const area = await getArea(vault);
  const dados = await carregarDados(area);
  $('status-linha').textContent = statusLinha(dados);
  render3Ps($('conteudo-3ps'), dados);
  renderMetas($('conteudo-metas'), dados);
  renderAcoes($('conteudo-acoes'), dados);
  renderProximoPasso($('conteudo-next'), dados);
  renderContexto($('conteudo-contexto'), dados);
  window._vault = vault;
  window._area = area;
}

async function bootstrap() {
  let handle = await loadHandle();
  if (handle && await ensurePermission(handle)) {
    await renderApp(handle);
  }
  $('btn-escolher-vault').addEventListener('click', async () => {
    handle = await pickVault();
    await renderApp(handle);
  });
}
bootstrap();
</script>
```

- [ ] **Step 2: Testar manualmente com vault vazio**

```bash
mkdir -p /tmp/forge-vault/.obsidian-master /tmp/forge-vault/"04 - Negocio"
echo '{}' > /tmp/forge-vault/.obsidian-master/marker.json
python3 -m http.server 4712 --directory skills/obsidian-forge/scripts &
open http://localhost:4712/dashboard.html
# Escolher /tmp/forge-vault quando solicitado
# Conferir renderizacao sem erros no console
kill %1
```

Expected: página carrega; após escolher pasta, mostra cards com "—" ou "Rode forge plan pra definir."

- [ ] **Step 3: Commit**

```bash
git add skills/obsidian-forge/scripts/dashboard.html
git commit -m "feat(forge): dashboard leitura FS Access + render DOM seguro"
```

---

### Task 4.3: `dashboard.html` — modal registrar progresso

**Files:**
- Modify: `skills/obsidian-forge/scripts/dashboard.html`

- [ ] **Step 1: Apender JS ao `<script>` (antes de `bootstrap();`)**

```javascript
/* ========= Modal progresso ========= */
function abrirModal() { $('modal-bg').classList.add('ativo'); }
function fecharModal() { $('modal-bg').classList.remove('ativo'); }

async function salvarProgresso() {
  const tipo = $('modal-tipo').value;
  const qtd = parseInt($('modal-qtd').value, 10) || 1;
  const nota = $('modal-nota').value.trim();
  const agora = new Date();
  const hh = String(agora.getHours()).padStart(2, '0');
  const mm = String(agora.getMinutes()).padStart(2, '0');
  const data = agora.toISOString().slice(0, 10);

  const area = window._area;
  const progDir = await area.getDirectoryHandle('progresso', { create: true });
  const filename = `${data}.md`;
  let text = await readText(progDir, filename);
  if (!text) text = `---\ntipo: progresso\ndata: ${data}\neventos: 0\n---\n\n`;
  const { meta, body } = parseFrontmatter(text);
  const det = [];
  if (tipo === 'cliente_fechado') det.push(`valor: R$ ${qtd}`);
  if (tipo === 'alcance_manual') det.push(`quantidade: ${qtd}`);
  if (nota) det.push(`nota: ${nota}`);
  const sufx = det.length ? ` (${det.join(', ')})` : '';
  const linha = `- ${hh}:${mm} — ${tipo}${sufx}`;
  meta.eventos = (meta.eventos || 0) + 1;
  const novoBody = (body || '').trim() + '\n' + linha + '\n';
  await writeText(progDir, filename, serializeFrontmatter(meta, novoBody));

  await recomputarMetas();
  fecharModal();
  await renderApp(window._vault);
}

async function recomputarMetas() {
  const area = window._area;
  const metasText = await readText(area, '_metas.md');
  if (!metasText) return;
  const { meta, body } = parseFrontmatter(metasText);
  const progDir = await area.getDirectoryHandle('progresso', { create: true });
  const eventos = [];
  for await (const [name, h] of progDir.entries()) {
    if (h.kind !== 'file' || !name.match(/^\d{4}-\d{2}-\d{2}\.md$/)) continue;
    const { body: b } = parseFrontmatter(await readText(progDir, name));
    for (const linha of (b || '').split('\n')) {
      const m = linha.match(/^- \d{2}:\d{2} — (\w+)(?:\s*\((.*)\))?/);
      if (m) eventos.push({ tipo: m[1], detalhes: m[2] });
    }
  }
  const ag = agregarProgresso(eventos);
  if (Array.isArray(meta.funil)) {
    for (const e of meta.funil) { e.atual = ag[e.etapa] ?? 0; }
  }
  let valorTotal = 0;
  for (const ev of eventos) {
    if (ev.tipo === 'cliente_fechado') {
      const m = (ev.detalhes || '').match(/valor:\s*R?\$?\s*(\d+(?:\.\d+)?)/);
      valorTotal += m ? parseFloat(m[1]) : (meta.funil?.find(x => x.etapa === 'clientes')?.valor_unitario || 0);
    }
  }
  if (meta.objetivo) meta.objetivo.valor_atual = valorTotal;
  await writeText(area, '_metas.md', serializeFrontmatter(meta, body));
}

$('btn-registrar').addEventListener('click', abrirModal);
$('modal-cancelar').addEventListener('click', fecharModal);
$('modal-salvar').addEventListener('click', salvarProgresso);
$('modal-bg').addEventListener('click', (e) => { if (e.target.id === 'modal-bg') fecharModal(); });
```

- [ ] **Step 2: Smoke test manual**

Abrir dashboard, clicar "+ registrar progresso", escolher tipo e qtd, salvar. Conferir:
- `04 - Negocio/progresso/YYYY-MM-DD.md` foi criado com a linha
- `_metas.md` teve `funil[].atual` incrementado

- [ ] **Step 3: Commit**

```bash
git add skills/obsidian-forge/scripts/dashboard.html
git commit -m "feat(forge): dashboard modal registrar progresso + recompute"
```

---

### Task 4.4: `dashboard.html` — checkbox em ação

**Files:**
- Modify: `skills/obsidian-forge/scripts/dashboard.html`

- [ ] **Step 1: Apender ao `<script>`**

```javascript
/* ========= Checkbox acoes ========= */
document.addEventListener('click', async (e) => {
  if (!e.target.classList.contains('check')) return;
  const slug = e.target.dataset.slug;
  if (!slug) return;
  const area = window._area;
  const acoesDir = await area.getDirectoryHandle('acoes');
  let filename = null;
  for await (const [name] of acoesDir.entries()) {
    if (name.includes(slug)) { filename = name; break; }
  }
  if (!filename) return;
  const { meta, body } = parseFrontmatter(await readText(acoesDir, filename));
  const novoBody = (body || '').replace(/- \[ \]/, '- [x]');
  if (novoBody === body) return;
  meta.tarefas_feitas = (meta.tarefas_feitas || 0) + 1;
  if (meta.tarefas_feitas >= meta.tarefas_totais) meta.status = 'concluido';
  else if (meta.status === 'pendente') meta.status = 'em_andamento';
  meta.atualizado = new Date().toISOString().slice(0, 19);
  await writeText(acoesDir, filename, serializeFrontmatter(meta, novoBody));
  await renderApp(window._vault);
});
```

- [ ] **Step 2: Smoke test**

Clicar em uma checkbox de ação. Conferir arquivo `acoes/*.md` atualizado.

- [ ] **Step 3: Commit**

```bash
git add skills/obsidian-forge/scripts/dashboard.html
git commit -m "feat(forge): dashboard checkbox marca tarefa + atualiza status"
```

---

### Task 4.5: `forge.py` — subcomando `dash`

**Files:**
- Modify: `skills/obsidian-forge/scripts/forge.py`

- [ ] **Step 1: Apender ao `forge.py`**

```python
def cmd_dash(args: argparse.Namespace) -> int:
    import http.server
    import socketserver
    import threading
    import webbrowser

    sys.path.insert(0, str(Path(__file__).parent))
    vault = Path(args.vault).resolve() if args.vault else _detectar_vault()
    scripts_dir = Path(__file__).parent

    if args.refresh:
        from dash_refresh import recomputar
        recomputar(vault_root=vault)
        print("OK _metas.md recalculado.")
        return 0

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(scripts_dir), **kw)
        def log_message(self, *a, **kw):
            if args.verbose:
                super().log_message(*a, **kw)
        def do_POST(self):
            if self.path == '/scan':
                try:
                    from scan_context import scan
                    result = scan(vault_root=vault, silent=True, quick=True)
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps(result).encode())
                except Exception as e:
                    self.send_error(500, str(e))
            else:
                self.send_error(404)

    class LocalOnly(socketserver.TCPServer):
        allow_reuse_address = True

    port = args.port
    with LocalOnly(('127.0.0.1', port), Handler) as srv:
        url = f'http://127.0.0.1:{port}/dashboard.html'
        print(f'forge dash · {url}')
        print(f'  vault: {vault}')
        print('  Ctrl-C pra parar.')
        if not args.no_browser:
            threading.Timer(0.5, lambda: webbrowser.open(url)).start()
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            print('\nparando.')
    return 0
```

E em `build_parser`:

```python
    pd = sub.add_parser("dash")
    pd.add_argument("--port", type=int, default=4712)
    pd.add_argument("--no-browser", action="store_true")
    pd.add_argument("--refresh", action="store_true")
    pd.add_argument("--verbose", action="store_true")
    pd.set_defaults(func=cmd_dash)
```

- [ ] **Step 2: Criar `dash_refresh.py`**

`skills/obsidian-forge/scripts/dash_refresh.py`:

```python
"""Recomputa _metas.md em Python (mirror da logica do dashboard.html)."""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from frontmatter import read_frontmatter, write_frontmatter   # noqa: E402
from math_funil import agregar_progresso   # noqa: E402

LINHA_RE = re.compile(r"^- \d{2}:\d{2} — (\w+)(?:\s*\((.*)\))?")


def _parse_eventos(body: str) -> list[dict]:
    eventos = []
    for linha in (body or "").split("\n"):
        m = LINHA_RE.match(linha)
        if not m:
            continue
        tipo = m.group(1)
        det = m.group(2) or ""
        ev = {"tipo": tipo}
        vm = re.search(r"valor:\s*R?\$?\s*(\d+(?:\.\d+)?)", det)
        if vm:
            ev["valor"] = float(vm.group(1))
        qm = re.search(r"quantidade:\s*(\d+)", det)
        if qm:
            ev["quantidade"] = int(qm.group(1))
        eventos.append(ev)
    return eventos


def recomputar(*, vault_root: Path) -> None:
    area = vault_root / "04 - Negocio"
    metas_path = area / "_metas.md"
    if not metas_path.exists():
        return
    meta, body = read_frontmatter(metas_path)
    prog_dir = area / "progresso"
    eventos = []
    if prog_dir.exists():
        for p in prog_dir.glob("*.md"):
            _, b = read_frontmatter(p)
            eventos.extend(_parse_eventos(b))
    atual = agregar_progresso(eventos)
    if "funil" in meta:
        for e in meta["funil"]:
            e["atual"] = atual.get(e.get("etapa"), 0)
    if "objetivo" in meta:
        meta["objetivo"]["valor_atual"] = atual.get("valor_total", 0)
    write_frontmatter(metas_path, meta, body)
```

- [ ] **Step 3: Testar dash help**

```bash
python3 skills/obsidian-forge/scripts/forge.py dash --help
```

Expected: mostra flags `--port`, `--no-browser`, `--refresh`, `--verbose`.

- [ ] **Step 4: Commit**

```bash
git add skills/obsidian-forge/scripts/forge.py skills/obsidian-forge/scripts/dash_refresh.py
git commit -m "feat(forge): subcomando dash + dash_refresh.py Python mirror"
```

---

### Task 4.6: Testes de `dash_refresh`

**Files:**
- Create: `tests/test_forge_dash_refresh.py`

- [ ] **Step 1: Teste**

```python
"""Paridade Python vs JS na agregação."""
from __future__ import annotations

import sys
from pathlib import Path

FORGE_DIR = Path(__file__).parent.parent / "skills" / "obsidian-forge" / "scripts"
sys.path.insert(0, str(FORGE_DIR))

from dash_refresh import recomputar, _parse_eventos  # noqa: E402
from frontmatter import read_frontmatter, write_frontmatter  # noqa: E402


def test_parse_eventos() -> None:
    body = """
- 14:00 — cliente_fechado (valor: R$ 2500, nota: primeiro)
- 15:00 — reuniao_realizada
- 16:00 — alcance_manual (quantidade: 120)
""".strip()
    e = _parse_eventos(body)
    assert len(e) == 3
    assert e[0]["tipo"] == "cliente_fechado"
    assert e[0]["valor"] == 2500.0
    assert e[2]["quantidade"] == 120


def test_recomputar(tmp_path: Path) -> None:
    area = tmp_path / "04 - Negocio"
    (area / "progresso").mkdir(parents=True)
    metas = {
        "tipo": "metas",
        "objetivo": {"titulo": "x", "valor_alvo": 10000, "valor_atual": 0},
        "funil": [
            {"etapa": "clientes", "alvo": 4, "atual": 0, "valor_unitario": 2500},
            {"etapa": "reunioes", "alvo": 40, "atual": 0, "taxa_conversao": 0.10},
            {"etapa": "leads", "alvo": 400, "atual": 0, "taxa_conversao": 0.10},
            {"etapa": "alcance", "alvo": 4000, "atual": 0, "fonte": "conteudo"},
        ],
    }
    write_frontmatter(area / "_metas.md", metas, "# m")
    write_frontmatter(
        area / "progresso" / "2026-04-22.md",
        {"tipo": "progresso", "data": "2026-04-22", "eventos": 3},
        "- 14:00 — cliente_fechado (valor: R$ 2500)\n"
        "- 15:00 — reuniao_realizada\n"
        "- 16:00 — lead_captado\n",
    )
    recomputar(vault_root=tmp_path)
    meta2, _ = read_frontmatter(area / "_metas.md")
    etapas = {e["etapa"]: e for e in meta2["funil"]}
    assert etapas["clientes"]["atual"] == 1
    assert etapas["reunioes"]["atual"] == 1
    assert etapas["leads"]["atual"] == 1
    assert meta2["objetivo"]["valor_atual"] == 2500.0
```

- [ ] **Step 2: Rodar, passar**

```bash
pytest tests/test_forge_dash_refresh.py -v
```

Expected: 2 passed.

- [ ] **Step 3: Commit**

```bash
git add tests/test_forge_dash_refresh.py
git commit -m "test(forge): dash_refresh paridade Python-JS (2 testes)"
```

---

# Wave 5 — Integração

### Task 5.1: `plugin.json` + 3 commands

**Files:**
- Modify: `plugin.json`
- Create: `commands/forge-scan.md`
- Create: `commands/forge-plan.md`
- Create: `commands/forge-dash.md`

- [ ] **Step 1: Ler `plugin.json` atual**

```bash
cat plugin.json
```

- [ ] **Step 2: Adicionar skill forge + 3 commands**

No `plugin.json`, seguir o formato atual e adicionar:
- Uma entrada em `skills` apontando pra `skills/obsidian-forge`
- Três entradas em `commands` apontando pra `commands/forge-scan.md`, `commands/forge-plan.md`, `commands/forge-dash.md`

(Adaptar ao schema exato do arquivo — o engineer deve ler e encaixar sem quebrar.)

- [ ] **Step 3: `commands/forge-scan.md`**

```markdown
---
description: Detecta projetos ativos no PC e gera notas atomicas de contexto no vault
---

Invocar a skill `obsidian-forge` com sub-comando `scan`:

1. Detectar vault via marker.json
2. Se `_config-scan.md` ausente → rodar entrevista (`--init`)
3. Rodar scan, gerar notas em `04 - Negocio/contexto/`, atualizar `_contexto.md`
4. Invocar `obsidian-librarian` ao final
```

- [ ] **Step 4: `commands/forge-plan.md`**

```markdown
---
description: Conduz entrevista dos 4 passos (3 Ps, precificacao, matematica, 7 acoes)
---

Invocar a skill `obsidian-forge` com sub-comando `plan`:

1. Detectar vault
2. Ler `_contexto.md` pra personalizar as perguntas
3. Conduzir os 4 passos no chat:
   - Passo 1+2: `plan-save-plano`
   - Passo 3: `plan-save-metas` (com validacao aritmetica)
   - Passo 4: `plan-save-acoes`
4. Ao final: sugerir `forge-dash`

Ver `skills/obsidian-forge/SKILL.md` pra fluxo detalhado.
```

- [ ] **Step 5: `commands/forge-dash.md`**

```markdown
---
description: Abre painel executor em localhost:4712 (Chrome/Arc/Edge)
---

Invocar a skill `obsidian-forge` com sub-comando `dash`:

1. Validar que `_plano.md` e `_metas.md` existem
2. Iniciar `python3 -m http.server` em 127.0.0.1:4712
3. Abrir browser em `http://127.0.0.1:4712/dashboard.html`
4. Usuario escolhe pasta do vault via File System Access API (1x)
```

- [ ] **Step 6: Commit**

```bash
git add plugin.json commands/
git commit -m "feat(forge): registra skill + 3 slash commands"
```

---

### Task 5.2: `obsidian-init` — pergunta sobre 04

**Files:**
- Modify: arquivo(s) da entrevista do `obsidian-init` em `skills/obsidian-init/scripts/`

- [ ] **Step 1: Localizar arquivo da entrevista**

```bash
grep -rln "entrevista\|03 - Memoria\|init\|create_vault" skills/obsidian-init/scripts/ | head -5
```

- [ ] **Step 2: Adicionar pergunta**

No trecho que cria as 4 áreas, após criar `03 - Memoria da IA`, adicionar:

```python
resp = input(
    "Ativar area `04 - Negocio` e o modulo forge "
    "(plano de negocio + dashboard executor)? (s/N): "
).strip().lower()

if resp == "s":
    area_forge = vault_root / "04 - Negocio"
    for sub in ["", "contexto", "progresso", "acoes"]:
        (area_forge / sub).mkdir(parents=True, exist_ok=True)
    # copia _area_readme.md do forge (se disponivel)
    src = Path(__file__).resolve().parents[3] / "obsidian-forge" / "scripts" / "templates" / "_area_readme.md"
    if src.exists():
        (area_forge / "_README.md").write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
```

(Ajustar o path `parents[3]` conforme a estrutura real — o engineer deve verificar.)

- [ ] **Step 3: Smoke test manual**

Rodar `obsidian-init` em dir temporário; responder `s` na pergunta; conferir estrutura criada.

- [ ] **Step 4: Commit**

```bash
git add skills/obsidian-init/
git commit -m "feat(init): pergunta opcional sobre ativar 04 - Negocio (forge)"
```

---

### Task 5.3: `obsidian-librarian` — honrar `protected`

**Files:**
- Modify: arquivo(s) de escrita do librarian em `skills/obsidian-librarian/scripts/`

- [ ] **Step 1: Localizar funções de escrita**

```bash
grep -rln "write_frontmatter\|update_note\|escrev" skills/obsidian-librarian/scripts/ | head -5
```

- [ ] **Step 2: Guarda contra edição de notas `protected`**

No topo de qualquer função que **escreva** num arquivo do vault:

```python
from obsidian_forge_frontmatter import read_frontmatter   # ou caminho equivalente

meta, _ = read_frontmatter(path)
if meta.get("protected") is True:
    return   # nao edita notas protected
```

Se o librarian tem lista de tipos reconhecidos, apender:
`plano`, `metas`, `contexto`, `config_scan`, `contexto_projeto`, `progresso`, `acao`.

- [ ] **Step 3: Smoke test**

Criar nota com `protected: true` no vault de teste, rodar librarian, conferir que não foi modificada.

- [ ] **Step 4: Commit**

```bash
git add skills/obsidian-librarian/
git commit -m "feat(librarian): honra protected=true + aprende 7 tipos do forge"
```

---

### Task 5.4: CLAUDE.md do vault template

**Files:**
- Modify: `skills/obsidian-init/assets/vault-template/CLAUDE.md`

- [ ] **Step 1: Apender bloco**

Ao final do `CLAUDE.md`:

```markdown

## Area `04 - Negocio` (forge)

Territorio do modulo `obsidian-forge` (v1.1+ do kit).

- `_plano.md` e `_metas.md` tem `protected: true` — so o forge escreve.
- `acoes/*.md` pode ser editado livremente; `tarefas_feitas/totais` sao
  gerenciados pelo dashboard.
- `progresso/YYYY-MM-DD.md` e append-only (nunca editar historico).
- `contexto/*.md` e regenerado pelo scanner — edicao manual sera sobrescrita.
```

- [ ] **Step 2: Commit**

```bash
git add skills/obsidian-init/assets/vault-template/CLAUDE.md
git commit -m "docs(init): CLAUDE.md explica area 04 - Negocio"
```

---

### Task 5.5: Teste de integração end-to-end

**Files:**
- Create: `tests/test_forge_integration.py`

- [ ] **Step 1: Teste**

```python
"""Integration: scan + plan + progresso + refresh num vault temporario."""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

FORGE_DIR = Path(__file__).parent.parent / "skills" / "obsidian-forge" / "scripts"
sys.path.insert(0, str(FORGE_DIR))


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    v = tmp_path / "vault"
    (v / ".obsidian-master").mkdir(parents=True)
    (v / ".obsidian-master" / "marker.json").write_text("{}")
    (v / "04 - Negocio" / "contexto").mkdir(parents=True)
    (v / "04 - Negocio" / "progresso").mkdir(parents=True)
    (v / "04 - Negocio" / "acoes").mkdir(parents=True)
    return v


@pytest.fixture
def fixtures_mtime() -> None:
    fix = Path(__file__).parent / "fixtures" / "forge" / "projetos-fake"
    agora = time.time()
    for r in [fix / "repo-ativo-python", fix / "repo-ativo-node"]:
        for f in r.rglob("*"):
            if f.is_file() and ".git" not in f.parts:
                os.utime(f, (agora, agora))


def test_fluxo_completo(vault: Path, fixtures_mtime: None) -> None:
    from scan_context import init_config, scan
    from plan_business import renderizar_plano, renderizar_metas, renderizar_acoes
    from dash_refresh import recomputar
    from frontmatter import read_frontmatter, write_frontmatter

    fix = Path(__file__).parent / "fixtures" / "forge" / "projetos-fake"
    init_config(vault_root=vault, pastas=[str(fix)])
    result = scan(vault_root=vault, silent=True)
    assert result["projetos_ativos"] >= 2

    renderizar_plano(vault_root=vault, respostas={
        "ciclo": "2026-Q2",
        "produto": "p", "problema": "pb", "pessoa": "ps",
        "produto_prosa": "a", "problema_prosa": "a", "pessoa_prosa": "a",
        "valor_unitario": 2500,
        "resultado_potencial": "r", "tempo_economizado": "t",
        "esforco_reduzido": "e", "producao_aumentada": "pa",
    })
    renderizar_metas(vault_root=vault, respostas={
        "ciclo": "2026-Q2",
        "objetivo_titulo": "R$ 10k", "valor_alvo": 10000, "prazo": "2026-06-30",
        "valor_unitario": 2500,
        "clientes_alvo": 4, "reunioes_alvo": 40, "reunioes_taxa": 0.10,
        "leads_alvo": 400, "leads_taxa": 0.10,
        "alcance_alvo": 4000, "alcance_fonte": "conteudo",
    })
    renderizar_acoes(vault_root=vault)

    write_frontmatter(
        vault / "04 - Negocio" / "progresso" / "2026-04-22.md",
        {"tipo": "progresso", "data": "2026-04-22", "eventos": 2},
        "- 10:00 — cliente_fechado (valor: R$ 2500)\n- 11:00 — reuniao_realizada\n",
    )
    recomputar(vault_root=vault)

    meta, _ = read_frontmatter(vault / "04 - Negocio" / "_metas.md")
    etapas = {e["etapa"]: e for e in meta["funil"]}
    assert etapas["clientes"]["atual"] == 1
    assert etapas["reunioes"]["atual"] == 1
    assert meta["objetivo"]["valor_atual"] == 2500.0
    assert len(list((vault / "04 - Negocio" / "acoes").glob("*.md"))) == 7
```

- [ ] **Step 2: Rodar**

```bash
pytest tests/test_forge_integration.py -v
```

Expected: 1 passed.

- [ ] **Step 3: Commit**

```bash
git add tests/test_forge_integration.py
git commit -m "test(forge): integration end-to-end"
```

---

# Wave 6 — Docs, release, smoke

### Task 6.1: README.md

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Adicionar bloco sobre forge**

Após a seção de instalação/confirmação, inserir:

```markdown

### Novo na v1.1 — `forge` (execução de negócio)

3 sub-comandos que transformam seu vault num sistema operacional de negócio:

- `/obsidian-master-kit:forge-plan` — entrevista dos 4 passos (3 Ps, precificação, matemática, 7 ações macro). Gera `04 - Negocio/_plano.md`, `_metas.md`, 7 `acoes/*.md`.
- `/obsidian-master-kit:forge-scan` — varre pastas informadas, cria notas atômicas por projeto em `04 - Negocio/contexto/`.
- `/obsidian-master-kit:forge-dash` — abre painel em `localhost:4712` (Chrome/Arc/Edge). Barras de progresso do funil, 7 ações, botão "+ registrar progresso".

Baseado na metodologia "IA como ferramenta" — resolve dor específica, cobra pelo resultado.

Guia rápido: `docs/forge-quickstart.md`.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs(forge): README com bloco v1.1"
```

---

### Task 6.2: ROADMAP.md

**Files:**
- Modify: `docs/ROADMAP.md`

- [ ] **Step 1: Adicionar seção "Skills entregues"**

No topo do ROADMAP, inserir:

```markdown
## Skills entregues

### v1.0 (2026-04-21)
- obsidian-init, obsidian-librarian, obsidian-expand, obsidian-organizer, obsidian-migrate

### v1.1 (2026-04-22)
- `obsidian-forge` — plano de negócio + scanner de contexto + dashboard executor (3 sub-comandos)

---
```

- [ ] **Step 2: Commit**

```bash
git add docs/ROADMAP.md
git commit -m "docs(roadmap): forge shipped em v1.1"
```

---

### Task 6.3: CHANGELOG.md

**Files:**
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Apender entrada**

No topo:

```markdown
## [1.1.0] - 2026-04-22

### Added
- `obsidian-forge` skill com 3 sub-comandos:
  - `forge-plan`: entrevista dos 4 passos (3 Ps, precificação, matemática, 7 ações macro)
  - `forge-scan`: detecção de projetos ativos com git + mtime → notas atômicas
  - `forge-dash`: HTML estático + File System Access API em localhost:4712
- Área `04 - Negocio` opcional no `obsidian-init`.
- Nova dep: `pyyaml>=6.0`.

### Changed
- `obsidian-librarian` honra `frontmatter.protected: true`.
- CLAUDE.md do vault template ganhou bloco sobre área 04.
```

- [ ] **Step 2: Commit**

```bash
git add CHANGELOG.md
git commit -m "chore(release): CHANGELOG v1.1.0"
```

---

### Task 6.4: `docs/forge-quickstart.md`

**Files:**
- Create: `docs/forge-quickstart.md`

- [ ] **Step 1: Criar**

```markdown
# forge — guia rápido (5 min)

## Pré-requisito

Vault criado via `obsidian-init`. Se a área `04 - Negocio` não existe, o forge-plan cria.

## 1. Fazer o plano

```
/obsidian-master-kit:forge-plan
```

~15 min de entrevista. Gera `_plano.md`, `_metas.md`, 7 `acoes/*.md`.

## 2. Escanear projetos

```
/obsidian-master-kit:forge-scan
```

Primeira vez pergunta quais pastas vigiar. Gera `contexto/*.md` + `_contexto.md`.

## 3. Abrir o painel

```
/obsidian-master-kit:forge-dash
```

Abre http://localhost:4712 no Chrome. Clique "Escolher meu vault". Depois:

- Barras de progresso do funil
- Checkbox nas 7 ações (clique marca task)
- "+ registrar progresso" (modal → evento → contador sobe)

## Eventos de progresso

- `lead_captado`, `reuniao_realizada`, `cliente_fechado`, `conteudo_publicado`, `alcance_manual`.

## Invariantes

- 100% local. Zero cloud, zero daemon.
- Dashboard: só Chromium (Chrome/Arc/Edge/Brave).
- `_plano.md` e `_metas.md` protegidos do librarian.
- Metodologia da aula hardcoded em v1.
```

- [ ] **Step 2: Commit**

```bash
git add docs/forge-quickstart.md
git commit -m "docs(forge): quickstart de 5 minutos"
```

---

### Task 6.5: Smoke test + fixes

- [ ] **Step 1: Rodar todos os testes**

```bash
pytest tests/test_forge_*.py -v
```

Expected: todos passam.

- [ ] **Step 2: Smoke test real**

```bash
# Vault temp
mkdir -p /tmp/smoke/.obsidian-master /tmp/smoke/"04 - Negocio"/{contexto,progresso,acoes}
echo '{}' > /tmp/smoke/.obsidian-master/marker.json

cd /tmp/smoke
FORGE=~/obsidian-master/skills/obsidian-forge/scripts/forge.py

python3 $FORGE scan --init
# Responder: ~/obsidian-master (ENTER duplo)
python3 $FORGE scan
ls "04 - Negocio/contexto/"

cat > /tmp/rp.json <<'EOF'
{"ciclo":"2026-Q2","produto":"Smoke","problema":"s","pessoa":"s","produto_prosa":"p","problema_prosa":"p","pessoa_prosa":"p","valor_unitario":2500,"resultado_potencial":"r","tempo_economizado":"t","esforco_reduzido":"e","producao_aumentada":"pa"}
EOF
python3 $FORGE plan-save-plano --respostas /tmp/rp.json

cat > /tmp/rm.json <<'EOF'
{"ciclo":"2026-Q2","objetivo_titulo":"R$ 10k","valor_alvo":10000,"prazo":"2026-06-30","valor_unitario":2500,"clientes_alvo":4,"reunioes_alvo":40,"reunioes_taxa":0.10,"leads_alvo":400,"leads_taxa":0.10,"alcance_alvo":4000,"alcance_fonte":"conteudo"}
EOF
python3 $FORGE plan-save-metas --respostas /tmp/rm.json

python3 $FORGE plan-save-acoes
ls "04 - Negocio/acoes/"

# Dash (manual — abre browser)
python3 $FORGE dash
# No browser: escolher /tmp/smoke, verificar 5 seçöes, registrar progresso 2x, marcar checkbox
```

- [ ] **Step 3: Fix qualquer bug encontrado**

Cada bug vira commit `fix(forge): <descrição>`.

- [ ] **Step 4: Commit final**

Se smoke passou limpo:

```bash
git commit --allow-empty -m "chore(forge): v1.1 smoke ok"
```

---

## Notas de execução

- **Waves em ordem**: 0 → 1 → 2 → 3 → 4 → 5 → 6.
- **TDD estrito** nas Waves 1-3 e 5.5. Wave 4 (dashboard) é TDD só em `dash_refresh.py` — `dashboard.html` validado manualmente + integração.
- **Commits frequentes**: cada Task produz ≥1 commit.
- **Se um teste falhar, parar** e consertar antes de avançar.
- **Dashboard sem `.innerHTML`**: rigor na Task 4.2 — todo render via `createElement` + `textContent` + `replaceChildren`.

## Self-review aplicado

1. **Spec coverage**: cada seção 1-15 do spec mapeia pra ≥1 task concreta.
2. **Placeholders**: nenhum "TBD"/"implement later"; todo código completo.
3. **Consistência de tipos**: `read_frontmatter`, `renderizar_plano`, `agregar_progresso`, `recomputar` mantêm assinaturas idênticas em todas as menções (testes + impl + integração).
4. **Vocabulário de eventos** (do spec seção 4.6): enumerado em 3 lugares — `math_funil._TIPO_PARA_ETAPA`, `references/metodologia-aula.md`, modal do dashboard. Todos batem.
5. **Invariante "sem innerHTML"**: tech stack documenta; Task 4.1/4.2 implementam; Task 0.1 (SKILL.md) codifica como invariante #9.
