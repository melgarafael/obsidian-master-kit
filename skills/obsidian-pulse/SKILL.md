---
name: obsidian-pulse
description: Esta skill deve ser usada quando o usuario diz "abre meu pulse", "mostra o dashboard", "o que ta acontecendo no vault", "ve os padroes", "sugere o que eu devo fazer agora", ou invoca `/obsidian-master-kit:pulse`. Sobe dashboard FastAPI+HTMX em localhost (default :4711) com insights temporais, sugestoes contextuais via ranking FSRS + bridges + clusters dormentes, deteccao de anomalias (streaks quebrados, keyword emergente, area abandonada), heatmap estilo GitHub, explicabilidade em cada card. 100% local, zero servicos cloud, anti-vigilante (tom sempre aberto, nunca diagnostico).
---

# obsidian-pulse

"Netflix/YouTube pessoal" rodando 100% local. Worker batch pre-computa
insights; dashboard serve em <500ms.

## Quando usar

- Usuario diz "abre o pulse", "dashboard", "o que ta rolando no vault".
- Usuario invoca `/obsidian-master-kit:pulse`.
- Apos scan + organizer: pulse consome `suggestions_cache`,
  `alerts_cache`, `clusters`, `events` pra gerar views.

## Quando **nao** usar

- Vault sem scan inicial (pulse precisa de notes/events).
- Sem deps `pulse` instaladas: `pip install 'obsidian-master-kit[pulse]'`.

## Fluxo canonico

### Passo 1: Detecte o vault

Walk ancestrais procurando `.obsidian-master/marker.json`. Senao,
pede `--vault PATH`.

### Passo 2: Escolha o sub-comando

| Intencao do usuario | Sub-comando |
|---|---|
| "Roda analise e atualiza caches" | `refresh` |
| "Sobe dashboard localhost" | `serve` |
| "Tudo junto, em foreground" | `daemon` |
| "Me da status resumido" | `status` |

### Passo 3: Invoque o script

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/obsidian-pulse/scripts/pulse.py \
  <sub-comando> [--vault PATH] [--port 4711]
```

### Passo 4: Dashboard

- http://localhost:4711 (porta configuravel)
- Token em `.obsidian-master/pulse-token.txt` — header `X-Pulse-Token`
- 6 tabs: Hoje / Pulso / Grafo / Saude / Descobrir / Insights
- Rejeita requests de IPs != 127.0.0.1

## Princípios duros (anti-vigilante)

1. **Max 5 insights por dia** (`LIMIT 5` nas queries).
2. **Max 1 alerta WARN por dia** (resto vai pra aba passiva).
3. **Reasoning obrigatorio** em cada card — constraint no schema.
4. **Zero LLM no loop** — templates deterministicos em pt-br.
5. **Privacy first**: `sensitive=1` redige titulo em `[item em area X]`.
6. **Pull, nao push**: dashboard abre quando Rafael quer; sem notificacao.

## CLI: referencia rapida

- `pulse refresh` — roda Stage B (batch analytics: FSRS, anomalies,
  ranking, cache generation)
- `pulse serve [--port 4711]` — sobe FastAPI+HTMX dashboard
- `pulse daemon [--port 4711]` — refresh + serve em foreground
- `pulse status` — resumo: ultima refresh, contagens, proxima window
