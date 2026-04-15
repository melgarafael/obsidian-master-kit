# obsidian-master-kit

> Um plugin Claude Code que transforma uma pasta vazia num vault Obsidian profissional —
> **segundo cérebro** para você + **memória persistente** para a IA.

Em menos de 5 minutos, saindo de uma pasta vazia, você tem um vault com:

- **4 áreas opinionadas** (Pessoal, Profissional, Pesquisas, Memória da IA)
- **Templates, MOCs e schema de frontmatter** consistentes
- **Um `CLAUDE.md` mestre** que orienta qualquer IA que escrever no vault depois
- **Um `_INDEX.md` vivo** que se atualiza sozinho toda vez que algo é adicionado
- **Um bibliotecário automático** que valida, normaliza tags, mantém links pros MOCs
  e garante que nada fica órfão

Tudo em português, sem depender de plugins do Obsidian.

---

## Por que existe

Obsidian é uma pasta de markdown. Isso é libertador — e é um convite ao caos.
Skills de IA (pesquisa autônoma, learning, etc.) escrevem notas lindas individualmente,
mas sem um contrato compartilhado elas acabam criando um mosaico desorganizado.

Este kit resolve o problema com dois contratos:

1. **`CLAUDE.md` na raiz do vault** — doutrina que toda skill deve ler antes de escrever.
2. **`obsidian-librarian`** — skill que é invocada automaticamente depois de toda escrita
   via hook `PostToolUse`, valida o que foi escrito e corrige desvios determinísticos.

Resultado: você escreve quando quer. A IA escreve o tempo todo. O vault permanece
navegável, linkado e coerente.

---

## Instalação

Claude Code gerencia plugins via sistema de marketplaces. Qualquer repo GitHub pode
ser adicionado como marketplace customizado — não é necessário estar no marketplace
oficial da Anthropic. Este repo já traz o `.claude-plugin/marketplace.json`
declarando-se como marketplace de 1 plugin.

### Fluxo canônico (2 comandos dentro do Claude Code)

```
/plugin marketplace add melgarafael/obsidian-master-kit
/plugin install obsidian-master-kit@obsidian-master-kit
```

Primeiro comando registra o repo como fonte. Segundo instala o plugin dali. O
Claude Code cacheia em `~/.claude/plugins/cache/<marketplace-name>/<plugin>/<version>/`
e registra em `~/.claude/plugins/installed_plugins.json`.

### Instalação em modo desenvolvimento (local)

Para hackear o plugin localmente sem passar pelo GitHub:

```
/plugin marketplace add /caminho/local/para/obsidian-master-kit
/plugin install obsidian-master-kit@obsidian-master-kit
```

O source `source: "directory"` no `known_marketplaces.json` aponta direto pro
diretório local, então mudanças refletem sem commit/push.

### Estrutura esperada pelo Claude Code

```
repo-root/
├── .claude-plugin/
│   ├── marketplace.json    # declara o repo como marketplace
│   └── plugin.json         # manifest do plugin (hooks, metadata)
├── skills/
├── hooks/
├── commands/
└── ...
```

---

## Quickstart

### 1. Crie (ou escolha) a pasta do seu vault

```bash
mkdir -p ~/Documents/MeuSegundoCerebro
cd ~/Documents/MeuSegundoCerebro
```

### 2. Rode o init dentro dessa pasta

```bash
# Dentro do Claude Code, na pasta do vault:
/obsidian-master-kit:init
```

A skill vai rodar uma entrevista curta em português (nome, profissão, áreas principais,
projetos ativos, idioma do journaling, fuso, tom) e já preenche o vault com essas
informações.

### 3. Abra no Obsidian

Aponte o Obsidian para a pasta. Pronto — vault navegável desde o primeiro segundo.

### 4. Use normalmente

A partir daqui, qualquer skill que escrever no vault (o `obsidian-master-kit` ou skills
de terceiros que você já usa) aciona o bibliotecário automaticamente. Você não precisa
fazer nada — o `_INDEX.md` se mantém vivo sozinho.

Se quiser forçar uma curadoria manual (por exemplo, depois de editar várias notas à mão):

```bash
/obsidian-master-kit:sync
```

---

## O que este kit inclui (v0.1.0-mvp)

| Skill | Quando usar |
|---|---|
| `obsidian-init` | Uma vez por vault. Scaffolda a estrutura + entrevista. |
| `obsidian-librarian` | Automática (via hook) depois de cada escrita. Também invocável manualmente. |

E mais um roadmap documentado em [`docs/ROADMAP.md`](docs/ROADMAP.md) com 7 skills
previstas para v0.2+ (daily-note, moc-builder, search, linker, archiver, graph-audit,
export).

---

## Estrutura do vault gerado

```
<seu-vault>/
├── CLAUDE.md                     # doutrina (você edita quando quer mudar regras)
├── _INDEX.md                     # índice vivo (o bibliotecário reescreve)
├── README.md                     # como navegar este vault
├── .obsidian-master/
│   └── marker.json               # identifica o vault como obsidian-master-kit
├── 00 - Pessoal/
│   ├── _MOC.md
│   ├── Perfil.md
│   ├── Journaling/
│   ├── Diario/
│   └── _templates/
├── 01 - Profissional/
│   ├── _MOC.md
│   ├── Projetos/
│   ├── Areas/
│   └── _templates/
├── 02 - Pesquisas e Estudos/
│   ├── _MOC.md
│   ├── Ativas/
│   ├── Arquivadas/
│   └── _templates/
└── 03 - Memoria da IA/
    ├── _MOC.md
    ├── Projetos de Codigo/
    ├── Bibliotecas/
    ├── Referencias/
    └── _templates/
```

---

## FAQ

**Preciso saber usar Obsidian pra usar isso?**
Não. O kit assume zero conhecimento. Se você nunca usou Obsidian, ele instala o
Obsidian, aponta pra pasta que o init criou e começa a navegar — os MOCs já te levam
pra onde é útil.

**E se eu já tenho um vault com conteúdo?**
O `obsidian-init` é idempotente: se a pasta tem conteúdo, ele só preenche buracos
(nunca sobrescreve). Mas ainda assim rode com cuidado e tenha backup — o padrão é
começar numa pasta nova.

**Esse kit substitui o Obsidian Sync?**
Não. Sincronização é problema do Obsidian (ou Syncthing, iCloud, Git, etc.). Este kit
só cuida da estrutura e curadoria do conteúdo.

**Funciona em inglês?**
No MVP, não. Templates, entrevista e doutrina são pt-br. Localização está no roadmap
para v1.x.

**Como desinstalo?**
`/plugin uninstall obsidian-master-kit`. O plugin some. O vault continua — é só uma
pasta de markdown, não depende mais do kit depois de criado.

---

## Contribuindo

Issues e PRs bem-vindos em
[github.com/melgarafael/obsidian-master-kit/issues](https://github.com/melgarafael/obsidian-master-kit/issues).

## Licença

MIT — veja [`LICENSE`](LICENSE).
