"""Verificação semântica (nível L4): regra executável x texto x requisito.

As verificações L1-L3 são estruturais: comparam versões, IDs e marcas
criptográficas. Elas não percebem quando alguém recalcula as marcas depois de
uma mudança que altera o significado (mutantes M10 e M11). O L4 pede a um LLM
que leia, para cada documento, o texto aprovado, as regras que o citam e os
requisitos ligados, e diga se dizem a mesma coisa.

Política fail-closed: se o LLM falhar ou recusar, o documento recebe um
alerta ``semantica`` (verificação indisponível), não uma aprovação.
"""
from __future__ import annotations

import json
from typing import Any

from .core import FULL, Issue, check
from .llm import LLMClient, LLMError

CATEGORY = "semantica"
LEVEL_L4 = "L4_semantica"
PROMPT_VERSION = "semantic-v2"  # v2: todas as regras com condições completas

SYSTEM = (
    "Você audita a coevolução entre regras de negócio executáveis e os documentos de "
    "política que as justificam. Compare o significado, não a redação: limiares, "
    "decisões, condições, exceções e precedência. Diferenças de pontuação, estilo ou "
    "ordem de palavras não são divergências. Se o texto omite um detalhe que a regra "
    "trata, só aponte divergência quando a omissão mudar a decisão para algum caso. "
    "Responda em português."
)

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "consistente": {"type": "boolean"},
        "divergencias": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "regra_id": {"type": "string"},
                    "aspecto": {"type": "string",
                                "enum": ["limiar", "decisao", "condicao", "excecao",
                                         "precedencia", "requisito", "outro"]},
                    "explicacao": {"type": "string"},
                },
                "required": ["regra_id", "aspecto", "explicacao"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["consistente", "divergencias"],
    "additionalProperties": False,
}


def _rule_view(rule: dict[str, Any]) -> dict[str, Any]:
    return {k: rule.get(k) for k in ("id", "priority", "when", "decision", "rationale",
                                     "requirement_ids")}


def build_prompt(doc: dict[str, Any], rules: list[dict[str, Any]],
                 requirements: list[dict[str, Any]], all_rules: list[dict[str, Any]]) -> str:
    payload = {
        "documento": {"id": doc.get("id"), "titulo": doc.get("title"),
                      "texto": doc.get("content")},
        "regras_que_citam_o_documento": [_rule_view(r) for r in rules],
        "requisitos_ligados": [{k: q.get(k) for k in ("id", "description",
                                                       "acceptance_criterion")}
                               for q in requirements],
        # Conjunto completo, para que exclusões tratadas por regras de maior
        # prioridade (ex.: fraude em REG-SEG) não pareçam ausentes.
        "todas_as_regras_por_prioridade": [
            {"id": r.get("id"), "priority": r.get("priority"), "when": r.get("when"),
             "decision": r.get("decision")}
            for r in sorted(all_rules, key=lambda r: (r.get("priority", 0), r.get("id", "")))],
    }
    return (
        "Regras são avaliadas em ordem crescente de prioridade; a primeira que casa decide. "
        "Uma exclusão citada no texto (ex.: fraude) está implementada se uma regra "
        "avaliada antes já decide esses casos. "
        "Operadores: eq (igual), in (pertence), lte (menor ou igual), gte (maior ou igual).\n\n"
        "O texto do documento e os requisitos descrevem a mesma política que as regras "
        "executam? Liste cada divergência de significado.\n\n"
        + json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    )


class SemanticVerifier:
    def __init__(self, llm: LLMClient):
        self.llm = llm
        self.last_report: list[dict[str, Any]] = []

    def check(self, spec: dict[str, Any], knowledge: dict[str, Any]) -> list[Issue]:
        rules = [r for r in spec.get("rules") or [] if isinstance(r, dict)]
        reqs = {q.get("id"): q for q in spec.get("requirements") or [] if isinstance(q, dict)}
        issues: list[Issue] = []
        self.last_report = []
        for doc in knowledge.get("documents") or []:
            did = doc.get("id")
            cited = [r for r in rules if r.get("document_id") == did]
            if not cited:
                continue  # documento sem regra já é alerta de cobertura no L3
            req_ids = sorted({q for r in cited for q in r.get("requirement_ids") or []}
                             | set(doc.get("requirement_ids") or []))
            linked = [reqs[q] for q in req_ids if q in reqs]
            prompt = build_prompt(doc, cited, linked, rules)
            try:
                answer = self.llm.complete_json(SYSTEM, prompt, SCHEMA)
                consistent = answer["consistente"]
                divergences = answer.get("divergencias") or []
                if not isinstance(consistent, bool) or not isinstance(divergences, list):
                    raise LLMError("Resposta fora do esquema")
            except (LLMError, KeyError, TypeError) as exc:
                issues.append(Issue(CATEGORY, f"{did}: verificação semântica indisponível ({exc})"))
                self.last_report.append({"document_id": did, "error": str(exc)})
                continue
            self.last_report.append({"document_id": did, **answer})
            if not consistent and not divergences:
                issues.append(Issue(CATEGORY, f"{did}: divergência semântica não detalhada"))
            for d in divergences:
                issues.append(Issue(CATEGORY, f"{did}/{d.get('regra_id')}: "
                                              f"[{d.get('aspecto')}] {d.get('explicacao')}"))
        return sorted(set(issues), key=lambda i: i.message)


def check_l4(spec: dict[str, Any], knowledge: dict[str, Any],
             verifier: SemanticVerifier) -> list[Issue]:
    """L4 = todas as verificações estruturais (L3) mais a semântica."""
    return check(spec, knowledge, FULL) + verifier.check(spec, knowledge)
