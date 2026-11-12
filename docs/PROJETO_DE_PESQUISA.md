# EvoPolicy-SDD: abordagem orientada por especificações para coevolução de regras e políticas em agentes de IA

**Tipo:** pré-projeto de pesquisa aplicada (versão inicial, 10 de novembro de 2026)  
**Área:** Engenharia de Software, Qualidade de Software, Sistemas baseados em IA  
**Status:** hipótese e protótipo exploratório; resultados científicos não estabelecidos.

## 1. Contextualização

Agentes baseados em LLM e RAG podem apoiar decisões operacionais ancoradas em documentos normativos. Entretanto, decisões também podem depender de regras determinísticas em código, restrições obrigatórias e uma trilha auditável. Quando políticas são alteradas, documentos e regras podem ficar em versões diferentes, sem que a execução falhe de maneira óbvia.

Em paralelo, o método SDD-ADR previamente concebido para decisão de estilos de comunicação de APIs organiza requisitos versionados, filtragem determinística, análise orientada a atributos de qualidade, ADRs e verificação de vínculos. O EvoPolicy-SDD aproveita o princípio de **especificações como fonte rastreável**, mas investiga um problema diferente: **coevolução de políticas documentais e regras executáveis em agentes**.

## 2. Problema e pergunta de pesquisa

**Problema:** não existe garantia automática de que o documento recuperado para justificar uma decisão esteja sincronizado com a versão de regra efetivamente aplicada, especialmente após alterações de requisitos.

**Questão principal (QP):** Em que medida um fluxo orientado por especificações versionadas melhora a detecção de inconsistências e a rastreabilidade de decisões de agentes híbridos com recuperação documental e regras determinísticas ao longo da evolução de políticas de negócio?

Perguntas secundárias:

- **QP1:** A abordagem aumenta a taxa de detecção de divergências entre especificações, regras e documentos, comparada a baselines sem verificação de coevolução?
- **QP2:** A abordagem reduz decisões justificadas com evidências desatualizadas durante atualizações controladas de políticas?
- **QP3:** Quais custos adicionais (tempo de implementação, bloqueios, manutenção, latência e revisão humana) a abordagem introduz?
- **QP4:** Em quais condições a verificação estrutural deixa passar divergências semânticas e qual é o benefício incremental de revisão humana ou verificação assistida por LLM?

## 3. Objetivos

### Geral

Projetar e avaliar uma abordagem de engenharia de software orientada por especificações que mantenha vínculos verificáveis entre requisitos, regras determinísticas, documentos recuperáveis e decisões produzidas por agentes de IA durante a evolução de políticas.

### Específicos

1. Definir metamodelo com identificadores estáveis, versões, regras, prioridades, condições e requisitos.
2. Construir protótipo com motor de decisão, base documental e validador de consistência.
3. Modelar cenários de mudança controlada e injeção deliberada de defeitos de sincronização.
4. Comparar com baselines funcionalmente equivalentes, explicitando as capacidades a mais da proposta.
5. Avaliar conformidade, detecção, cobertura decisória, rastreabilidade e custos de revisão.
6. Examinar ameaças à validade e produzir dados/scripts reproduzíveis.

## 4. Proposta técnica

- **A1 — especificação:** `specs/v*/specification.yaml` com versão, requisitos, critérios de aceitação, prioridades e regras.
- **A2 — documentação recuperável:** `knowledge/v*/policies.json`, com fonte e versão explícitas.
- **A3 — motor de decisão:** aplica regras ordenadas e produz decisão com ID da regra, ID do documento e requisitos relacionados.
- **A4 — validador:** detecta IDs ausentes, versões divergentes, alterações de condição/decisão e referências desatualizadas.
- **A5 — suíte evolutiva:** cenários com decisões oráculo independentes por versão e relatórios comparativos.

No protótipo v0.1.1, a ligação entre regra e documento usa fingerprint SHA-256 de atributos estruturados da regra (inclusive a justificativa), e a especificação fixa o digest do texto aprovado de cada documento; isso **não comprova equivalência semântica** entre o texto da política e o código e não substitui revisão especializada.

## 5. Hipóteses falsificáveis

- **H1:** SDD terá maior sensibilidade na detecção de deriva entre documentos e regras em mutações pré-definidas.
- **H2:** SDD terá menor proporção de decisões emitidas com evidência versionada incorretamente, quando o bloqueio for contabilizado separadamente.
- **H3:** SDD acarretará custos adicionais de manutenção e/ou indisponibilidade (por bloqueio) que precisam ser quantificados.

Hipóteses são direcionais para orientar coleta e análise, não resultados observados.

## 6. Desenho do estudo

### 6.1. Demonstração técnica, pronta no repositório

Dezoito casos sintéticos de reembolso e cancelamento são rotulados nas versões v1 e v2. A alteração introduz uma exceção para cliente premium após despacho. O benchmark ilustra cinco condições, incluindo dados deliberadamente não sincronizados. Os resultados desta fase demonstram apenas propriedades do código escrito, não efeitos de SDD na qualidade de LLMs.

Um experimento exploratório de mutações (Fase A2 do protocolo) aplica 12 derivas e 6 mudanças benignas ao par v2 e compara quatro níveis cumulativos do validador. Ele operacionaliza H1–H3 em pequena escala e expõe o limite de QP4 (derivas semânticas com marcas recalculadas não são detectadas), mas os mutantes e rótulos são do próprio autor e não permitem inferência.

### 6.2. Estudo empírico planejado

Construir corpus sintético maior com múltiplas famílias de mudanças: adição de exceções, remoção, alteração de precedência, mudança de limiar, documentos conflitantes, inversão semântica preservando metadados, atualização parcial e requisitos ambíguos.

Comparar condições sob **mesmo LLM, mesmo corpus, mesmo limite de tokens, mesma temperatura e mesmas tarefas**:

- **B1:** agente RAG com instruções, sem guardas de regra.
- **B2:** agente RAG + regras determinísticas + validação de saída.
- **B3:** B2 com atualização manual sistemática e versionamento convencional.
- **P:** B3 acrescido da verificação SDD, matriz de rastreabilidade e mecanismos de bloqueio/revisão.

O baseline B3 é necessário para atribuir ganhos à **verificação SDD**, e não meramente à organização ou versionamento que qualquer equipe pode implementar.

## 7. Métricas e análise

- **Taxa de detecção de deriva:** mutações reais detectadas / total de mutações injetadas.
- **Precisão dos alertas:** alertas verdadeiros / total de alertas (evitar bloqueio excessivo).
- **Taxa de decisão correta:** decisões iguais ao oráculo / total de casos; **reportar bloqueios separadamente**.
- **Cobertura de decisões:** casos com decisão executada / total de casos.
- **Citações válidas:** decisões com versão e política adequadas / decisões com fonte citada.
- **Rastreabilidade:** fração de decisões com vínculos verificáveis para regras e requisitos; além da verificação de pertinência por avaliadores.
- **Custo:** p50/p95 latência, tokens, custo estimado, esforço de atualização, taxa de revisão humana.

Repetições independentes devem ser feitas por cenário/modelo quando houver LLM, com intervalo de confiança por bootstrap agrupado por cenário e comparação pareada apropriada ao tipo de métrica (por exemplo McNemar para acerto binário). Definir tamanho de amostra com estudo piloto e análise de potência antes de coleta confirmatória. Não assumir que 18 casos bastem para inferência.

## 8. Ameaças à validade

- **Construto:** fingerprints verificam estruturas, mas não conteúdo semântico; oráculo exige revisão independente.
- **Interna:** baseline simplificado pode favorecer a proposta; igualar funcionalidades e recursos antes do estudo principal.
- **Externa:** políticas fictícias não representam sistemas regulados reais.
- **Conclusão:** cenários correlacionados exigem unidades de análise e intervalos adequados; uso de um LLM restringe generalização.
- **Operacional:** fail-closed aumenta bloqueios; custo e custo de indisponibilidade precisam ser considerados.

## 9. Contribuição esperada

Um metamodelo, um pipeline de coevolução verificável, um conjunto de mutações e um estudo controlado sobre confiabilidade e rastreabilidade em políticas evolutivas, com artefatos abertos. A originalidade dependerá de revisão de trabalhos sobre policy-as-code, evolução de RAG, conformidade de agentes e spec-driven development.

## 10. Cronograma preliminar de 6 meses

| Mês | Entregável |
|---|---|
| M1 | Revisão de literatura e protocolo pré-registrado |
| M2 | Metamodelo e implementação com embedders/LLMs opcionais |
| M3 | Conjunto de cenários e oráculos por avaliadores |
| M4 | Injeção de mutações, execuções e validação dos logs |
| M5 | Análise quantitativa e revisão dos resultados |
| M6 | Redação e submissão do artigo |

## 11. Referências iniciais de trabalho

- Projeto de referência: https://github.com/DouglasKomori/ifood-genai-agent-poc (inspiração arquitetural, não reprodução de código ou dados).
- SDD-ADR (artefato prévio do grupo, objeto de pesquisa diferente).
- Complementar a revisão com artigos revisados por pares sobre engenharia de sistemas LLM/RAG, *policy-as-code*, governança de agentes, testes metamórficos e evolução de especificações. **Não tratar esta lista preliminar como revisão sistemática concluída.**
