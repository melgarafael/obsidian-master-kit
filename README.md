# obsidian-master-kit

**Transforma uma pasta vazia no seu segundo cérebro em 5 minutos.**

Você roda um comando, responde 7 perguntinhas, e pronto — você tem uma estrutura
profissional do Obsidian com pastas, templates e um "bibliotecário" de inteligência
artificial que organiza tudo pra você sozinho, pra sempre.

---

## O que você ganha

- Uma pasta do Obsidian já **organizada do jeito certo**, sem precisar pensar em
  estrutura: tem espaço pra suas anotações pessoais, trabalho, pesquisas e memória
  de projetos.
- **Um assistente que cura suas notas sozinho.** Sempre que você (ou uma outra IA)
  escrever alguma coisa no seu Obsidian, ele revisa, põe etiquetas, conecta com
  outras notas, e mantém um índice sempre atualizado.
- **Templates prontos** pra cada tipo de anotação: diário, reflexão pessoal,
  pesquisa, projeto de trabalho, contexto de software que você está construindo.
- Um arquivo de **doutrina** (`CLAUDE.md`) que explica pra qualquer IA que for usar
  seu Obsidian depois: "as regras da casa são essas aqui". Qualquer skill
  respeita automaticamente.

Tudo em português. Você não precisa saber nada sobre Obsidian pra começar.

---

## O que você vai precisar antes

Duas coisas, nada mais:

1. **[Claude Code](https://claude.com/claude-code) instalado** no seu computador
   (Mac, Windows ou Linux).
2. **[Obsidian](https://obsidian.md) instalado** — é grátis.

Se você já tem os dois, pula pra instalação.

---

## Instalação em 2 passos

A instalação é feita **dentro do próprio Claude Code**, usando o sistema de
plugins dele. Você não precisa clonar nada no terminal, nem saber onde os
arquivos vão parar — o Claude Code cuida de tudo.

### Passo 1 — Adicione o kit como "fonte" (marketplace) do seu Claude Code

Dentro do Claude Code, digite:

```
/plugin marketplace add melgarafael/obsidian-master-kit
```

O que isso faz: diz pro seu Claude Code "olha, esse repositório do GitHub tem
plugins que você pode instalar". É uma só vez — depois disso, o Claude Code sabe
onde achar o kit.

### Passo 2 — Instale o plugin

Ainda dentro do Claude Code:

```
/plugin install obsidian-master-kit@obsidian-master-kit
```

Pronto. O Claude Code baixa o plugin, registra as skills, commands e hook. Em
alguns segundos os comandos já aparecem no autocomplete.

### Confirmando que funcionou

Digite `/` no Claude Code e veja se aparecem na lista:

- `/obsidian-master-kit:init`
- `/obsidian-master-kit:sync`

Se aparecerem, **tá instalado**. Pula pro próximo bloco.

Se **não apareceram**, vai pra seção [Problemas comuns](#problemas-comuns).

---

## Primeiro uso — criando seu segundo cérebro

### 1. Escolha onde seu Obsidian vai morar

No Terminal, crie uma pasta nova (ou use uma que você já tem em mente):

```bash
mkdir -p ~/Documents/MeuSegundoCerebro
cd ~/Documents/MeuSegundoCerebro
```

Esse comando cria a pasta `MeuSegundoCerebro` dentro dos seus Documentos e
entra nela. Você pode mudar o nome se quiser.

### 2. Rode o init dentro do Claude Code

Abra o Claude Code nessa pasta (a maioria dos sistemas deixa você clicar com botão
direito na pasta e escolher "Abrir no Claude Code"). Depois digite:

```
/obsidian-master-kit:init
```

O kit vai te fazer **7 perguntinhas rápidas**, todas em português:

1. Seu nome
2. Sua profissão ou função
3. Suas áreas principais de trabalho (ex: "Backend; Mentoria")
4. Seus projetos ativos agora
5. Idioma que você prefere pra escrever sobre você mesmo
6. Seu fuso horário
7. Como prefere que a IA fale com você — formal ou casual

Responde cada uma. Não tem resposta certa ou errada — é só pra IA te conhecer.

### 3. Pronto — abre no Obsidian

Quando as perguntas terminam, sua pasta está cheia de arquivos organizados. Abre o
Obsidian, vai em **File > Open Vault > Open folder as vault**, aponta pra pasta
que você criou no passo 1.

Boa-vinda ao seu segundo cérebro.

---

## Como seu vault está organizado

Seu Obsidian agora tem 4 grandes áreas:

| Pasta | Pra que serve |
|---|---|
| **00 - Pessoal** | Quem você é. Diário, reflexões, seu perfil. |
| **01 - Profissional** | Seu trabalho. Projetos, áreas de responsabilidade. |
| **02 - Pesquisas e Estudos** | Onde vai tudo que você (ou a IA) pesquisa e estuda. |
| **03 - Memoria da IA** | Contexto pra quando você está construindo software com IA. |

E dois arquivos especiais na raiz:

- **CLAUDE.md** — as regras da casa. **Você edita quando quer.** Qualquer IA que
  for mexer no seu Obsidian lê ele primeiro.
- **_INDEX.md** — o índice vivo. **Não edite à mão** — é o bibliotecário que mantém
  atualizado sozinho.

---

## O que acontece depois

Depois que seu vault existe, o kit trabalha pra você automaticamente.

Toda vez que você (ou uma skill de IA, tipo um pesquisador automático) adicionar
uma nota nova, o **bibliotecário** entra em ação:

- Confere se a nota está bem formada (tem título, data, etiquetas corretas)
- Conecta a nota com as outras notas relacionadas
- Atualiza o índice `_INDEX.md` com as novidades
- Avisa se alguma coisa está estranha (nota órfã, etiqueta desconhecida)

Você não precisa chamar o bibliotecário — ele aparece sozinho.

Se quiser forçar uma arrumação manual (por exemplo, depois de editar várias notas
de uma vez), digita dentro do Claude Code:

```
/obsidian-master-kit:sync
```

---

## Perguntas frequentes

### Preciso pagar alguma coisa?

**Não.** O Obsidian é grátis pra uso pessoal. O Git é grátis. O kit é MIT
(você pode usar, modificar, distribuir). O Claude Code tem planos gratuitos e
pagos — se você já usa, está pronto.

### O que é o Obsidian, na prática?

É um app grátis que abre pastas de arquivos `.md` (texto simples) como se fosse
um wiki pessoal. Os arquivos ficam **no seu computador**, não na internet. Você
pode linkar notas entre si e visualizar tudo em um grafo.

### Minhas notas vão pra internet?

**Não.** Tudo fica na pasta local que você criou. Nada sai do seu computador a
menos que você use um serviço de sincronização (iCloud, Syncthing, Obsidian Sync,
etc.) separadamente. O kit não sincroniza nada.

### Funciona no Windows e no Linux, ou só no Mac?

Funciona nos três. Os comandos do Terminal são iguais em qualquer sistema (no
Windows, use o PowerShell).

### Já tenho um vault do Obsidian com minhas coisas. Posso usar o kit sem perder nada?

Pode. O kit é **idempotente** — ele só preenche buracos, nunca sobrescreve nada que
já existe. Mas ainda assim, antes de rodar em vault que você já usa, faz um
**backup** (copia a pasta toda pra outro lugar). Por precaução.

### Não gostei. Como apago?

Dentro do Claude Code, roda:

```
/plugin uninstall obsidian-master-kit
```

Isso remove o kit. Sua pasta do Obsidian **continua intacta** — ela é só uma
pasta de arquivos de texto, independe do kit.

Se quiser também tirar a "fonte" do Claude Code:

```
/plugin marketplace remove obsidian-master-kit
```

### Posso personalizar as pastas e regras?

Pode. O arquivo `CLAUDE.md` dentro do seu vault é seu — edite quando quiser.
Se você mudar, por exemplo, o nome de uma pasta, o bibliotecário vai respeitar
isso na próxima sincronização. Só não apaga o `.obsidian-master/` escondido
dentro do vault — é o marcador que diz "esse vault tem o kit ativo".

---

## Problemas comuns

### "Os comandos `/obsidian-master-kit:init` e `/obsidian-master-kit:sync` não aparecem"

Três coisas pra checar, em ordem:

1. **A instalação terminou de verdade?** Dentro do Claude Code, roda
   `/plugin list`. Se `obsidian-master-kit` aparece na lista, está instalado. Se
   não aparece, o `/plugin install` falhou — repete a instalação.
2. **Você adicionou o marketplace primeiro?** O comando
   `/plugin marketplace add melgarafael/obsidian-master-kit` precisa ter rodado
   **antes** do install. Se pulou, volta ao Passo 1.
3. **Seu Claude Code é recente o suficiente?** O sistema de plugins é
   relativamente novo. Atualiza pra versão mais recente e tenta de novo.

### Erros comuns na instalação

- **"marketplace not found"** → o comando `/plugin marketplace add` não chegou a
  ser executado. Roda ele antes do install.
- **"plugin already installed"** → você já instalou uma vez. Se quer reinstalar
  do zero, roda `/plugin uninstall obsidian-master-kit` primeiro.
- **"network error"** → verifique sua conexão e tente novamente. O Claude Code
  precisa baixar do GitHub.

### "O Obsidian não abre minha pasta"

O Obsidian precisa que você aponte pra ele via **File > Open Vault**. Não é só
arrastar a pasta. Se mesmo assim não abrir, confirma que a pasta tem arquivos
`.md` dentro — se não tiver, o `init` não rodou como deveria.

### Ainda com problema?

Abre uma issue em
[github.com/melgarafael/obsidian-master-kit/issues](https://github.com/melgarafael/obsidian-master-kit/issues)
descrevendo:

- O que você tentou fazer
- O que aconteceu em vez (copia e cola a mensagem de erro)
- Seu sistema operacional

---

## O que vem depois deste MVP

O kit vai crescer com mais skills — diário automático, busca semântica, arquivador
de notas antigas, auditor do grafo. A lista completa está em
[`docs/ROADMAP.md`](docs/ROADMAP.md).

Se você é desenvolvedor e quer entender como o kit funciona por dentro, tem
documentação técnica em [`docs/DEV.md`](docs/DEV.md).

---

## Licença

[MIT](LICENSE). Usa, modifica, compartilha, vende, o que quiser. Só não bota meu
nome em problema.
