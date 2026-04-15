# Roteiro de entrevista — obsidian-init

7 perguntas curtas, uma por vez, em pt-br. Tom conversacional. Respostas alimentam o
scaffold do vault.

## Como conduzir

- Uma pergunta por mensagem. Não faça questionário inteiro de uma vez.
- Se o usuário passou `--profile arquivo.md` ou similar, leia o arquivo primeiro e
  pule as perguntas já cobertas (confirme no final "li X, Y, Z do perfil — confirma?").
- Respostas curtas são bem-vindas. Se a pessoa der uma resposta ambígua, peça
  clarificação só se realmente necessário pro scaffold.
- No final, mostre um resumo das respostas e peça confirmação antes de rodar o script.

## Perguntas (nesta ordem)

### 1. Nome

> "Qual nome você quer que apareça no vault como dono? (pode ser primeiro nome, apelido,
> ou nome completo — o que você preferir ver no seu `Perfil.md`)"

Salva em: `--owner-name`

### 2. Profissão / função

> "Como você descreveria sua função ou profissão em uma linha? (ex: 'Engenheira de
> software', 'Psicóloga clínica', 'Estudante de medicina', 'Fundador de startup')"

Salva em: `--owner-profession`

### 3. Áreas principais de trabalho

> "Quais são suas 2-4 áreas principais de trabalho/interesse? Coisas que você
> considera *responsabilidades contínuas* (não projetos com prazo). Separa com `;`.
> (ex: 'Backend; DevOps; Mentoria de juniores')"

Salva em: `--owner-areas`

Regra: se o usuário der mais de 5, pergunte quais são os mais importantes — áreas
demais diluem o vault.

### 4. Projetos ativos agora

> "Quais projetos você está tocando ativamente agora? 1-5 projetos com começo e fim
> previsto (diferente de áreas, que são contínuas). Separa com `;`. Se não tem nenhum
> agora, pode deixar em branco."

Salva em: `--owner-projects`

Se vazio: `--owner-projects ""` — o scaffold não gera stubs de projeto.

### 5. Idioma para journaling e reflexão pessoal

> "Em qual idioma você prefere escrever suas reflexões pessoais? (ex: 'pt-br', 'en',
> 'es'. Default: pt-br)"

Salva em: `--owner-lang`

Essa info só afeta os templates de journaling e a copy do perfil — o resto do vault é
pt-br fixo no MVP.

### 6. Fuso horário

> "Qual seu fuso horário? (IANA timezone — ex: 'America/Sao_Paulo', 'America/Belem',
> 'Europe/Lisbon'. Default: America/Sao_Paulo)"

Salva em: `--owner-timezone`

Se o usuário não souber o IANA, pergunte a cidade e traduza.

### 7. Tom da escrita

> "Como você prefere que a IA escreva pra você dentro do vault? 'casual' (você/tu,
> linguagem solta) ou 'formal' (senhor/senhora, linguagem de e-mail executivo)?"

Salva em: `--owner-tone`

## Resumo de confirmação

Depois das 7, mostre algo como:

```
Vou scaffoldar seu vault em `~/Documents/MeuVault` com:

- Dono: Rafael Melgaco
- Profissão: Dev de IA
- Áreas: IA; CRM; Gestão
- Projetos ativos: Automatik Club; Tomik CRM
- Idioma journaling: pt-br
- Fuso: America/Sao_Paulo
- Tom: casual

Confirma? (sim | editar | cancelar)
```

Só rode o script depois do "sim".
