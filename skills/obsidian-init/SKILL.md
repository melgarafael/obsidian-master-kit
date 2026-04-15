---
name: obsidian-init
description: Esta skill deve ser usada quando o usuario quer iniciar um vault Obsidian do zero, criar um segundo cerebro, gerar a estrutura de pastas opinionada do obsidian-master-kit, ou quando ele invoca /obsidian-master-kit:init. Conduz uma entrevista curta em pt-br (nome, profissao, areas, projetos, fuso, tom) e scaffolda um vault completo com doutrina CLAUDE.md, _INDEX.md vivo, MOCs e templates. Idempotente: nunca sobrescreve arquivos existentes. Nao executar sem explicita intencao do usuario de criar um vault Obsidian.
---

# obsidian-init

Scaffolda um vault Obsidian completo seguindo o padrao `obsidian-master-kit`: 4 areas,
CLAUDE.md doutrina, `_INDEX.md` vivo, MOCs por area, templates por tipo de nota.

## Quando usar

- Usuario diz: "quero criar meu segundo cerebro", "inicia meu vault Obsidian",
  "scaffolda um Obsidian pra mim", "cria a estrutura de pastas do Obsidian"
- Usuario invoca `/obsidian-master-kit:init` (slash command)
- Usuario aponta para uma pasta vazia e quer transformar em vault

## Quando **nao** usar

- Usuario ja tem um vault funcionando e so quer adicionar notas (use outras skills)
- Usuario quer editar o CLAUDE.md do vault (ele mesmo edita, nao a IA)
- Usuario quer sincronizar um vault existente (use `obsidian-librarian`)

## Como usar — fluxo canonico

### Passo 1: Determine o diretorio-alvo

Pergunte onde scaffoldar. Candidatos comuns:
- Pasta atual (pwd) — se o usuario ja fez `cd` para la
- `~/Documents/<NomeDoVault>` — escolha dele
- Um `--path` explicito que ele pode ter passado

Sempre confirme antes de prosseguir. **Nao scaffolda em `~` ou em pasta com codigo**.

### Passo 2: Cheque estado do alvo

Se a pasta tem arquivos:
- Tem `.obsidian-master/marker.json`? Ja e um vault-master — aborte e sugira
  `/obsidian-master-kit:sync` em vez disso.
- Tem outros arquivos? Confirme com o usuario antes de prosseguir. O script preserva
  arquivos existentes (so preenche buracos), mas avise.

### Passo 3: Conduza a entrevista

Siga o roteiro em `references/interview-script.md`. Sao 7 perguntas curtas em pt-br.
Se o usuario passou `--profile <arquivo>`, leia o arquivo e pule perguntas ja cobertas.

### Passo 4: Invoque o script

Use o script `scripts/scaffold_vault.py` passando todas as respostas via flags. Exemplo:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/obsidian-init/scripts/scaffold_vault.py \
  --path "/Users/nome/Documents/MeuVault" \
  --owner-name "Nome Sobrenome" \
  --owner-profession "Desenvolvedor de software" \
  --owner-areas "Backend; DevOps; Mentoria" \
  --owner-projects "Projeto A; Projeto B" \
  --owner-lang "pt-br" \
  --owner-timezone "America/Sao_Paulo" \
  --owner-tone "casual" \
  --vault-name "Meu Segundo Cerebro"
```

O script:
1. Copia a arvore de `assets/vault-template/` para o alvo.
2. Interpola placeholders (`{{OWNER_NAME}}`, `{{DATE_TODAY}}`, etc.).
3. Gera stubs por projeto em `01 - Profissional/Projetos/`.
4. Gera stubs por area em `01 - Profissional/Areas/`.
5. Escreve `.obsidian-master/marker.json` com a versao do kit.
6. Imprime relatorio: arquivos criados, projetos stubados, proximos passos.

**Nunca sobrescreve arquivos existentes.** Use `--dry-run` antes se incerto.

### Passo 5: Reporte proximos passos

Depois que o script termina:

- Diga ao usuario para abrir a pasta no Obsidian (File > Open Vault).
- Sugira revisar `00 - Pessoal/Perfil.md` e ajustar a bio.
- Sugira criar a primeira entrada de diario usando o template.
- Mencione que daqui pra frente o bibliotecario cuida do `_INDEX.md` sozinho.

## Flags do script — referencia rapida

| Flag | Obrigatoria? | Default | Descricao |
|---|---|---|---|
| `--path` | nao | pwd | Onde scaffoldar o vault |
| `--owner-name` | sim | — | Nome do dono |
| `--owner-profession` | sim | — | Funcao / profissao |
| `--owner-areas` | nao | "" | Areas separadas por `;` |
| `--owner-projects` | nao | "" | Projetos separados por `;` |
| `--owner-lang` | nao | pt-br | Idioma do journaling |
| `--owner-timezone` | nao | America/Sao_Paulo | Fuso |
| `--owner-tone` | nao | casual | `casual` ou `formal` |
| `--vault-name` | nao | basename do path | Nome humano do vault |
| `--profile` | nao | — | YAML/JSON com todas as respostas |
| `--dry-run` | nao | false | Imprime plano, nao escreve |
| `--force` | nao | false | Permite escrever em pasta ja com conteudo |

## Guardrails

- **Nunca** rode o script sem confirmar path com o usuario.
- **Nunca** rode em `$HOME`, `/`, `/Users`, `/tmp` (sem `--force`) ou em pasta com `.git`
  que nao seja um vault-master.
- **Nunca** sobrescreve arquivos existentes (o script ja protege, mas confirme antes).
- Se a pasta tem `.obsidian-master/marker.json`, nao rode init — use o librarian.

## O que este skill NAO faz

- Nao instala o Obsidian (app). Isso e manual.
- Nao configura plugins do Obsidian (Dataview, Templater, etc.). Ver roadmap.
- Nao sincroniza com nuvem. Ver FAQ do README principal.
- Nao edita o CLAUDE.md do vault depois de criado — isso e territorio humano.
