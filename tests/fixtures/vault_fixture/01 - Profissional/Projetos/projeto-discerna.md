---
created: 2025-11-08
updated: 2026-02-28
area: profissional
type: projeto
status: ativo
project: discerna
tags: [projeto, ia, video-analysis]
---

# Projeto Discerna

Ferramenta de analise de video usando a [[escala-hawkins]] como lente de
calibracao de consciencia. Entrada: URL de YouTube ou arquivo local.
Saida: relatorio estruturado com nivel calibrado, citacoes-chave, e
analise de dinamica de fala.

## Arquitetura

- Transcricao via whisper.cpp
- Analise multi-camada: texto + prosodia + visual (quando aplicavel)
- Calibracao cruzada com referenciais da [[escala-hawkins]]
- Saida em Markdown pra integracao com Obsidian

## Status

- Pipeline de texto funciona (quick mode)
- Pipeline de audio parcial — prosodia em W
- Diarizacao multi-speaker em teste (ver [[sessao-2026-03-10]])

Dialoga com [[projeto-automatiklabs]] (usar pra analisar aulas) e com
[[projeto-obsidian-master-kit]] (saida ja vai pro vault).
