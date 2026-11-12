# Registro de decisões de projeto — EvoPolicy-SDD

Decisões de engenharia do protótipo, no formato curto contexto → decisão → consequências.
Não confundir com o SDD-ADR (projeto separado, sobre estilos de comunicação de APIs).

## D-001 — Fingerprint cobre o que a regra decide e como se justifica (v0.1.1)

**Contexto.** Na v0.1 o fingerprint incluía `id`, `when`, `decision`, `priority` e `requirement_ids`. A `rationale` mostrada ao usuário podia mudar sem alerta (ex.: "até 2 horas" com limiar de 1 hora).
**Decisão.** Incluir `rationale` e `document_id` no fingerprint.
**Consequências.** Toda edição de justificativa exige revisão do documento associado. Fingerprints da v0.1 deixam de valer e foram regenerados com `evopolicy fingerprint --write`.

## D-002 — A especificação fixa o digest do texto aprovado de cada documento (v0.1.1)

**Contexto.** O vínculo era unidirecional (documento → regra). Editar a prosa de um documento sem tocar nas regras passava na validação (mutação M09).
**Decisão.** `specification.yaml` ganhou `document_digests` (SHA-256 de `id`, `title`, `content`). Divergência gera alerta da categoria `digest`.
**Consequências.** Detecta M09. Custo: qualquer edição de texto, inclusive correção de pontuação (N05), bloqueia até nova aprovação — é o único alarme falso observado no experimento de mutações. O digest **não** prova equivalência semântica: M10 e M11 (marcas recalculadas sem revisão real) continuam indetectáveis.

## D-003 — Verificações organizadas em categorias e níveis cumulativos (v0.1.1)

**Contexto.** Para testar H1 é preciso atribuir a detecção a cada mecanismo, e não ao validador como um todo.
**Decisão.** Cada problema tem categoria (`versao`, `ids`, `referencias`, `fingerprint`, `digest`, `cobertura`, `esquema`). Os níveis L0–L3 ativam subconjuntos cumulativos e funcionam como ablação.
**Consequências.** L1 representa versionamento convencional (baseline B3 do projeto de pesquisa); L2 corresponde ao validador da v0.1; L3 à versão revisada.

## D-004 — Esquema de fatos declarado na especificação (v0.1.1)

**Contexto.** Os campos aceitos estavam fixos no código e os valores das cláusulas não eram tipados (um `in` com string passava).
**Decisão.** Seção `fields` na especificação (`bool`, `str`, `number`); o validador verifica tipos por operador e o dataset é checado contra o mesmo esquema.
**Consequências.** Mudar o vocabulário de fatos passa a ser uma mudança versionada da especificação.

## D-005 — Bloqueio fail-closed e decisão padrão vinda da especificação

**Contexto.** O motor ignorava `default_decision`.
**Decisão.** Sem regra aplicável, usa-se `default_decision` (fallback `REVISAO_HUMANA` se ausente/inválida). Com guarda ativa e qualquer erro, o caso é `BLOQUEADO`.
**Consequências.** Bloqueio reduz disponibilidade; deve ser operado com fluxo de exceção e revisão humana. Decisões bloqueadas ou por padrão têm `evidence_valid = null` (nenhuma evidência citada), separadas de evidência inválida.

## D-006 — Artefatos de pesquisa fora do pacote instalado

**Contexto.** `ROOT` era derivado de `__file__`; com `pip install .` a CLI procurava `specs/` dentro do site-packages.
**Decisão.** Raiz resolvida por `--root`, `EVOPOLICY_ROOT`, diretório atual (ou ancestral) e checkout de origem, nessa ordem.
**Consequências.** Specs, documentos e casos continuam versionados no repositório, não no wheel.
