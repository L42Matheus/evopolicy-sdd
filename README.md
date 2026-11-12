# EvoPolicy-SDD

**Protótipo exploratório de pesquisa — v0.1.1 (11/11/2026)** · [Changelog](CHANGELOG.md)

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
- Testes unitários sem acesso à internet e pipeline CI do GitHub Actions.

**Não implementado nesta versão:** embeddings, modelo de linguagem, orquestração de ferramentas, coleta de casos reais, revisão por especialistas ou inferência estatística. O benchmark mede só o comportamento do protótipo deterministicamente, não a eficácia científica de SDD em produção.

## Estrutura

```text
evopolicy-sdd/
├── specs/v1/specification.yaml
├── specs/v2/specification.yaml
├── knowledge/v1/policies.json
├── knowledge/v2/policies.json
├── datasets/cases.json
├── src/evopolicy/{core,evolution,mutations,experiment,project,cli}.py
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

### Publicar uma nova versão da política

1. Criar `specs/vN/` e `knowledge/vN/` e editar regras e textos.
2. `evopolicy diff vN-1 vN` para revisar o impacto nos casos.
3. **Revisar se o texto dos documentos expressa as regras** e só então `evopolicy fingerprint --version vN --write`.
4. `evopolicy validate --spec-version vN` e testes.

O passo 3 é o ponto frágil: recalcular marcas sem revisão contorna a verificação (mutações M10/M11).

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

Projeto original e código independentes, inspirados conceitualmente por: Douglas Komori, [`ifood-genai-agent-poc`](https://github.com/DouglasKomori/ifood-genai-agent-poc). **Não é fork e não reproduz código nem dados daquele repositório.** O domínio foi adaptado para uma plataforma fictícia, sem qualquer vínculo com iFood. A publicação de resultados precisa declarar o baseline, protocolo, versões, dataset e limitações.

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
