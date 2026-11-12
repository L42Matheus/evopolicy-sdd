# EvoPolicy-SDD

**Protótipo exploratório de pesquisa — v0.2.0 (12/11/2026)** · [Changelog](CHANGELOG.md)

Uma abordagem orientada por especificações para detectar deriva entre regras de negócio e documentos recuperáveis por um agente baseado em políticas.

## Hipótese investigada

A coevolução controlada de especificações, regras e documentos, com verificações automatizadas de rastreabilidade, **pode** melhorar a detecção de inconsistências durante mudanças de políticas. Essa hipótese **ainda não foi validada empiricamente** com agentes LLM/RAG reais.

## O que foi implementado

- Duas versões de uma política **100% fictícia** de cancelamento, com alteração na exceção para clientes premium.
- `specification.yaml` versionados: requisitos com IDs, regras, prioridades, condições e decisões.
- Documentos de conhecimento versionados, ligados às regras por IDs e fingerprints SHA-256; a especificação fixa o digest do texto aprovado de cada documento (vínculo nos dois sentidos).
- Verificador por categorias (versão, IDs, referências, fingerprint, digest, cobertura, esquema), com níveis de ablação L0–L3, que impede a execução da variante SDD quando os artefatos divergem.
- `diff` entre versões com casos impactados, matriz de rastreabilidade e registro JSONL de decisões.
- Experimento de mutações (12 derivas, 6 mudanças benignas) que mede sensibilidade, alarmes falsos e o limite semântico da abordagem.
- Motor determinístico de decisão sobre fatos **estruturados**, com trilha de regra e documentação.
- Recuperador lexical local simples (ilustrativo; **não** é RAG semântico nem LLM).
- Benchmark offline reproduzível com cinco condições e casos rotulados.
- **Camada de LLM (v0.2, opcional)** com Claude (Anthropic) ou GPT (OpenAI), pelos SDKs oficiais:
  - **L4 semântico** (`semantic-check`, `mutate --semantic`): o LLM compara regra executável, texto do documento e requisito, mirando as derivas ressincronizadas (M10/M11) que L1–L3 não veem. Falha ou recusa do modelo vira alerta (fail-closed).
  - **Agente P** (`ask`; com `--semantic-guard`, P+S): o guarda SDD e a regra determinística decidem; o LLM só redige a resposta. A resposta é conferida (mesma decisão, mesma evidência) e, se falhar, usa-se a justificativa da regra.
  - **Baseline B1** (`ask --llm-only`, `llm-benchmark`): o LLM decide sozinho a partir dos documentos, para comparação.
  - **Cache de respostas** (`--cache`, `--offline`) para reproduzir experimentos sem nova chamada.
- Testes unitários sem acesso à internet (o LLM é simulado) e pipeline CI do GitHub Actions.

**Primeiros resultados com LLM real** (Claude Opus 5.5, uma execução em 12/11/2026, respostas em `llm_cache/claude.json`): o L4 detecta 12/12 derivas, incluindo M10 e M11, sem alarme falso novo (N05 continua bloqueado pelo digest do L3). Sozinha, a categoria semântica pega 8/12 e não acusa nenhuma benigna. No agente, o baseline B1 (LLM decide pelos documentos) erra 4/18 com documentos antigos, três deles exatamente os casos da exceção premium; a condição P não emite decisão errada e bloqueia as 18 com documentos antigos. GPT ainda não foi executado.

**Não implementado nesta versão:** embeddings, orquestração de ferramentas, coleta de casos reais, revisão por especialistas ou inferência estatística.

## Estrutura

```text
evopolicy-sdd/
├── specs/v1/specification.yaml
├── specs/v2/specification.yaml
├── knowledge/v1/policies.json
├── knowledge/v2/policies.json
├── datasets/cases.json
├── src/evopolicy/{core,evolution,mutations,experiment,project,cli}.py
├── src/evopolicy/{llm,semantic,agent,experiment_llm}.py   # camada de LLM
├── tests/
├── docs/{PROJETO_DE_PESQUISA,ARQUITETURA,PROTOCOLO_EXPERIMENTAL,DECISOES}.md
└── results/
```

## Como executar (Python 3.10+)

```bash
python -m venv .venv
source .venv/bin/activate           # Windows: .venv\\Scripts\\activate
pip install -e .                    # ou: pip install .
evopolicy validate                  # consistência spec v2 x documentos v2
evopolicy trace                     # matriz REQ -> regra -> documento
evopolicy diff v1 v2                # o que mudou e quais casos são afetados
evopolicy decide --case C05 --log results/decisoes.jsonl
evopolicy benchmark                 # cinco condições de demonstração
evopolicy mutate                    # experimento de mutações
python -m unittest discover -s tests -v
```

Os comandos procuram `specs/` e `knowledge/` no diretório atual (ou acima). Fora do repositório, use `--root CAMINHO` ou `EVOPOLICY_ROOT`. Também funciona via `PYTHONPATH=src python -m evopolicy ...` quando PyYAML está instalado.

### Com LLM real (Claude ou GPT)

```bash
pip install -e ".[llm]"
# Chaves só pelo ambiente (nunca por argumento ou commit):
#   ANTHROPIC_API_KEY para --provider anthropic (padrão, modelo claude-opus-5-5)
#   OPENAI_API_KEY    para --provider openai    (modelo gpt-5.5)
evopolicy semantic-check --cache llm_cache/claude.json
evopolicy ask --case C05 --cache llm_cache/claude.json
evopolicy ask --case C05 --llm-only --provider openai --cache llm_cache/gpt.json
evopolicy mutate --semantic --cache llm_cache/claude.json     # acrescenta L4
evopolicy llm-benchmark --provider openai --cache llm_cache/gpt.json
# Reexecução sem rede e sem custo, a partir do cache:
evopolicy mutate --semantic --offline --cache llm_cache/claude.json
```

`--model` e `--effort` (ou `EVOPOLICY_MODEL`/`EVOPOLICY_EFFORT`) trocam modelo e esforço de raciocínio. Com Claude, a chamada usa saída JSON estruturada e o fallback do servidor (`fallbacks: "default"`), que repete um pedido recusado por política em outro modelo; uma recusa final vira alerta. Com GPT, usa a Responses API com esquema estrito e `store=False`. O cache guarda as respostas por hash do pedido e pode ser versionado para tornar o experimento reproduzível.

### Publicar uma nova versão da política

1. Criar `specs/vN/` e `knowledge/vN/` e editar regras e textos.
2. `evopolicy diff vN-1 vN` para revisar o impacto nos casos.
3. **Revisar se o texto dos documentos expressa as regras** e só então `evopolicy fingerprint --version vN --write`.
4. `evopolicy validate --spec-version vN` e testes.

O passo 3 é o ponto frágil: recalcular marcas sem revisão contorna a verificação estrutural (mutações M10/M11). O `semantic-check` (L4) existe para pegar exatamente esse caso.

### Demonstração da inconsistência

```bash
# SDD com artefatos consistentes -> decisão rastreada
evopolicy decide --case C05

# Especificação v2 contra documentos v1 -> bloqueia publicação
evopolicy validate --spec-version v2 --doc-version v1

# Baseline sem guarda, com fonte desatualizada -> continua decidindo
evopolicy decide --case C05 --spec-version v2 --doc-version v1 --no-guard
```

O bloqueio é **fail-closed** e deve ser operacionalizado com fluxo de exceção e revisão humana; não indica automaticamente decisão correta. Os hashes protegem o vínculo entre estruturas técnicas, **não garantem que o texto da política seja semanticamente equivalente** à regra.

## Origem e ética

Projeto e código originais. O domínio é uma plataforma fictícia de pedidos, sem dados reais. A publicação de resultados precisa declarar o baseline, protocolo, versões, dataset e limitações.

## Documentos

- [Proposta científica](docs/PROJETO_DE_PESQUISA.md)
- [Arquitetura](docs/ARQUITETURA.md)
- [Protocolo experimental](docs/PROTOCOLO_EXPERIMENTAL.md)
- [Registro de decisões de projeto](docs/DECISOES.md)
- [Projeto de pesquisa em LaTeX (modelo SBC)](paper/) e [PDF compilado](paper/projeto_evopolicy_sdd.pdf)

## Resultado do experimento de mutações

| Nível do validador | Sensibilidade | Alarmes falsos | Não detectadas |
|---|---|---|---|
| L1 só versão | 2/12 | 0/6 | 10 |
| L2 estrutural (v0.1) | 8/12 | 0/6 | M06, M09, M10, M11 |
| L3 completo (v0.1.1) | 10/12 | 1/6 (N05) | M10, M11 |

Números de um único cenário fictício, com mutantes e rótulos do próprio autor: ilustram o mecanismo, **não** sustentam inferência. Detalhes em [PROTOCOLO_EXPERIMENTAL.md](docs/PROTOCOLO_EXPERIMENTAL.md#fase-a2--experimento-de-mutações-implementado-exploratório).

## Próxima etapa científica

Acrescentar adaptadores controlados para um único LLM e um retriever com embeddings, fixar seeds/temperaturas, incluir casos adversariais e avaliar métodos comparáveis sob o **mesmo orçamento, corpus e versões**, preferencialmente com avaliadores cegos.
