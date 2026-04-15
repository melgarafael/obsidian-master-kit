# Fixture Vault — Testes de Integracao

Este vault e um **fixture de teste** usado por `tests/test_core_integration.py`.
Simula um vault Obsidian realista em pt-br com ~50 notas distribuidas em 4
areas canonicas do obsidian-master-kit.

## Estrutura

```
00 - Pessoal/          → diarios, leituras, reflexoes
01 - Profissional/     → projetos ativos, contatos
02 - Pesquisas e Estudos/ → hermetismo, alquimia, escala hawkins
03 - Memoria da IA/    → logs de sessoes
_templates/            → templates (deve ser IGNORADO pelo scanner)
.obsidian-master/      → marker.json (DB e criado pelos testes)
```

## Variacoes intencionais

- **Frontmatter completo**: maioria das notas (created, updated, area, type, status, tags)
- **Frontmatter minimo / ausente**: ~5 notas (teste de robustez)
- **Wiki-links normais**: `[[hermetismo-overview]]`
- **Wiki-links com alias**: `[[tabua-esmeralda|A Tabua]]`
- **Links quebrados deliberados**: `[[projeto-inexistente-xyz]]`
- **Embed**: `![[imagem-algo]]` (arquivo de imagem nao existe, teste de link quebrado de embed)
- **Tags hierarquicas inline**: `#hermetismo`, `#esoterico/antiguidade`

## NAO EDITE

Esta pasta e imutavel. Os testes copiam (`shutil.copytree`) para `tmp_path`
antes de mexer. Qualquer scan gerado durante os testes fica no diretorio
temporario, nao aqui.
