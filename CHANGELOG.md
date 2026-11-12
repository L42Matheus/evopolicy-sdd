# Changelog

## 0.1.1 — 11/11/2026

Revisão da v0.1 antes da primeira publicação. Decisões em [docs/DECISOES.md](docs/DECISOES.md).

**Corrigido**
- CLI quebrava com `pip install .` (não editável): raiz dos artefatos agora é detectada (`--root`, `EVOPOLICY_ROOT`, diretório atual).
- `default_decision` da especificação era ignorado.
- Casos sem regra aplicável contavam como "evidência válida"; agora `evidence_valid = null`.
- Testes dependiam da posição dos casos no JSON; agora usam o ID.
- CLI aceitava apenas `v1`/`v2` fixos; versões são descobertas em `specs/` e `knowledge/`.

**Validador**
- Categorias de verificação e níveis de ablação L0–L3.
- Novas verificações: requisito sem regra, documento sem regra, requisito citado inexistente, prioridades duplicadas, justificativa ausente, tipos de valores por operador (esquema `fields`).
- Fingerprint inclui `rationale` e `document_id` (D-001).
- Especificação fixa o digest do texto de cada documento (D-002).

**Novo**
- `evopolicy diff vA vB`: requisitos/regras adicionados, removidos e alterados e casos impactados.
- `evopolicy trace`: matriz REQ → regra → documento com estado de cada vínculo.
- `evopolicy fingerprint [--write]`: calcula e grava marcas (após revisão humana).
- `evopolicy decide --log arquivo.jsonl`: registro auditável da decisão (digests de spec, base e fatos).
- `evopolicy mutate`: experimento de mutações com 12 derivas e 6 mudanças benignas.
- Benchmark exporta `decisions.jsonl` e métricas condicionadas a decisões emitidas.

## 0.1.0 — 10/11/2026

Versão inicial: especificações v1/v2, base documental com fingerprints, motor determinístico, recuperador lexical, benchmark de cinco condições e 17 testes.
