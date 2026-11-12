# Protocolo experimental v0.1.1

## Fase A — demonstração reproduzível (implementada)

1. Executar `evopolicy validate --spec-version v2 --doc-version v2`.
2. Executar `evopolicy validate --spec-version v2 --doc-version v1` e observar erro de validação (exit code 2).
3. Executar `evopolicy benchmark` para obter `results/observations.csv`, `results/summary.csv` e `results/summary.json`.
4. Executar `python -m unittest discover -s tests -v`.

### Condições

| Identificação | Regras | Documentos | Verificação de publicação | Interpretação |
|---|---|---|---|---|
| B1_hibrido_desatualizado | v1 | v1 | não | Falha de atualização geral |
| B2_hibrido_atualizado | v2 | v2 | não | Atualização correta sem guarda SDD |
| B3_hibrido_documento_antigo | v2 | v1 | não | Decisão pode estar correta, mas evidência obsoleta |
| P1_sdd_sincronizado | v2 | v2 | sim | Proposta com artefatos alinhados |
| P2_sdd_documento_antigo | v2 | v1 | sim | Proposta detecta e bloqueia divergência |

**Importante:** as condições têm capacidades intencionalmente distintas para **demonstrar o mecanismo**. Não é um ensaio causal justo sobre produtividade ou eficácia geral do SDD. Em particular, B2 e P1 devem empatar na correção quando não houver deriva.

### Oráculo

`datasets/cases.json` contém os rótulos esperados por versão, definidos separadamente das chamadas ao motor. São casos sintéticos, revisados apenas pelo autor do protótipo. A revisão cega e validação dos rótulos não foram realizadas.

### Como ler o benchmark

- `accuracy`: proporção de casos com decisão idêntica ao oráculo v2, **incluindo bloqueios como não acertos**. Não é qualidade de LLM.
- `block_rate`: percentual de decisões suspensas por validação SDD. Quanto maior, menor disponibilidade; não confundir com acerto.
- `accuracy_when_emitted`: acerto apenas entre as decisões emitidas (exclui bloqueios).
- `invalid_evidence`: decisões que citam documento com versão ou fingerprint incompatível. Bloqueios e decisões por `default_decision` **não** citam evidência e são contados à parte em `no_evidence`.
- `invalid_evidence_rate_when_emitted`: `invalid_evidence / emitted`.
- `wrong_permits`: decisões de permissão emitidas em casos cujo oráculo não autoriza.

## Fase A2 — experimento de mutações (implementado, exploratório)

Responde de forma preliminar a H1 (sensibilidade), H2 (decisões emitidas com evidência divergente) e H3 (custo de bloqueio), e torna mensurável o limite semântico de QP4.

```bash
evopolicy mutate   # gera results/mutation_observations.csv, mutation_summary.csv/json
```

**Procedimento.** Cada operador (`src/evopolicy/mutations.py`) parte do par sincronizado spec v2 + documentos v2 e produz um mutante com rótulo de verdade atribuído a priori pelo autor: `drift=True` (artefatos divergem em significado) ou `drift=False` (mudança benigna ou evolução completa e sincronizada). Cada mutante é validado nos quatro níveis cumulativos do validador e os 18 casos são executados com guarda.

| Nível | Categorias ativas | Interpretação |
|---|---|---|
| L0_sem_verificacao | nenhuma | agente sem guarda |
| L1_versao | estrutura, versão | versionamento convencional (≈ B3) |
| L2_estrutural | + IDs, referências, fingerprint | validador da v0.1 |
| L3_completa | + digest, cobertura, esquema | validador v0.1.1 |

**Mutantes.** M01 limiar só na spec · M02 precedência trocada · M03 decisão invertida · M04 regra removida · M05 requisito removido · M06 requisito sem regra · M07 justificativa contraditória · M08 atualização parcial (um documento na versão antiga) · M09 texto do documento editado sem revisão · M10 texto invertido com marcas recalculadas · M11 limiar alterado com marcas recalculadas e texto antigo · M12 base documental v1 inteira. Benignos: N01–N03 reordenações · N04 metadados editoriais · N05 correção de pontuação · N06 evolução completa e sincronizada (limiar 2h na regra e no texto).

**Resultados observados (determinísticos, 12 derivas + 6 benignas).**

| Nível | Detectadas | Sensibilidade | Alarmes falsos | Não detectadas | Decisões erradas emitidas | Decisões emitidas com evidência divergente |
|---|---|---|---|---|---|---|
| L0 | 0/12 | 0,00 | 0/6 | todas | 9 | 101 |
| L1 | 2/12 | 0,17 | 0/6 | M01–M07, M09–M11 | 9 | 81 |
| L2 | 8/12 | 0,67 | 0/6 | M06, M09, M10, M11 | 1 | 27 |
| L3 | 10/12 | 0,83 | 1/6 (N05) | M10, M11 | 1 | 18 |

**Leitura.** (i) Fingerprints explicam a maior parte do ganho sobre o versionamento convencional. (ii) O digest de texto (D-002) captura M09, mas transforma uma correção de pontuação (N05) em bloqueio de 18 decisões — custo operacional, não erro de lógica. (iii) M10 e M11 mostram o limite do mecanismo: se alguém recalcula as marcas sem revisar o texto, a verificação estrutural é contornada; só revisão humana ou verificação semântica (próxima etapa, com LLM como verificador) pode atuar aí.

**Limites.** Os mutantes e seus rótulos foram escritos pelo mesmo autor do validador (risco de viés de construção); há um mutante por família e uma única política; contagens não têm intervalo de confiança e **não sustentam inferência estatística**. A Fase B deve gerar mutantes de forma sistemática, com rótulos revisados por terceiros e cegos ao validador.

## Fase B — avaliação confirmatória (não implementada)

Pré-registrar hipótese, seleção de cenários, unidade de análise, métricas e plano estatístico. Construir ao menos diferentes famílias de mudança com grau controlado; variar diferentes versões, não apenas uma exceção. Comparar quatro métodos com capacidades pareadas e mesmo modelo, modelo de embeddings e orçamento. Garantir que os avaliadores dos oráculos não conheçam a condição experimental. Executar análise de potência e utilizar testes pareados com correção por múltiplas comparações quando necessário. Publicar scripts, artefatos e limitações.

## Reprodutibilidade

Fixar commit do código, arquivo de cenário, hash de documentos, versões de dependências, semente da execução do LLM e logs completos de falhas. O protótipo atual é determinístico e não exige seed. O benchmark grava `results/decisions.jsonl` com o digest da especificação, da base documental e dos fatos de cada decisão, permitindo replay e auditoria.
