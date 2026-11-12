"""Agente com LLM: o modelo explica, a especificação decide.

``SDDAssistant`` (condição P do protocolo; com o guarda L4, P+S):
  1. guarda SDD (L3, e opcionalmente L4): artefatos inconsistentes bloqueiam;
  2. motor determinístico escolhe a regra e a decisão;
  3. o LLM redige a resposta ao atendente citando só o documento da regra;
  4. a resposta passa por conferência (decisão e citação). Se o LLM falhar
     ou contradisser a decisão, usa-se a justificativa da regra (fail-closed).

``LLMOnlyBaseline`` (condição B1, ou B1-RAG com recuperação semântica): o LLM
lê os documentos e os fatos e decide sozinho. Serve de comparação; nunca é usado para decidir em produção.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

from .core import BLOCKED, VALID_DECISIONS, Decision, PolicyAgent
from .llm import LLMClient, LLMError

DECISION_ENUM = sorted(VALID_DECISIONS)

EXPLAIN_SYSTEM = (
    "Você redige respostas para atendentes de uma plataforma de pedidos. A decisão já foi "
    "tomada por uma regra de negócio auditada; não a altere nem sugira outra. Explique a "
    "decisão em até três frases, em português, apoiando-se apenas no documento fornecido. "
    "Não invente prazos, valores ou exceções que não estejam no documento."
)

EXPLAIN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "decisao": {"type": "string", "enum": DECISION_ENUM},
        "resposta": {"type": "string"},
        "documentos_citados": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["decisao", "resposta", "documentos_citados"],
    "additionalProperties": False,
}

DECIDE_SYSTEM = (
    "Você decide pedidos de reembolso de uma plataforma de pedidos com base apenas nos "
    "documentos de política fornecidos. Se os documentos não permitirem uma conclusão "
    "segura, escolha REVISAO_HUMANA. Responda em português."
)

DECIDE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "decisao": {"type": "string", "enum": DECISION_ENUM},
        "documento_id": {"type": "string"},
        "justificativa": {"type": "string"},
    },
    "required": ["decisao", "documento_id", "justificativa"],
    "additionalProperties": False,
}


@dataclass
class Answer:
    case_id: str
    status: str
    text: str
    source: str  # "llm", "regra" (fallback) ou "bloqueio"
    model: str | None
    decision: dict[str, Any]
    llm_rejected_reason: str | None = None
    llm_raw: dict[str, Any] | None = field(default=None, repr=False)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SDDAssistant:
    def __init__(self, engine: PolicyAgent, llm: LLMClient):
        self.engine = engine
        self.llm = llm
        self._docs = {d.get("id"): d for d in engine.knowledge.get("documents", [])}

    def _prompt(self, case: dict[str, Any], decision: Decision) -> str:
        doc = self._docs.get(decision.document_id) or {}
        payload = {
            "pergunta_do_atendente": case.get("question", ""),
            "fatos_do_caso": case.get("facts", {}),
            "decisao": decision.status,
            "regra_aplicada": {"id": decision.rule_id, "justificativa": decision.rationale},
            "documento": {"id": doc.get("id"), "titulo": doc.get("title"),
                          "texto": doc.get("content")},
        }
        return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)

    def answer(self, case: dict[str, Any]) -> Answer:
        decision = self.engine.decide(case)
        cid = decision.case_id
        if decision.status == BLOCKED:
            return Answer(cid, BLOCKED, decision.rationale, "bloqueio", None, decision.to_dict())
        fallback = Answer(cid, decision.status, decision.rationale, "regra", self.llm.model,
                          decision.to_dict())
        if not decision.document_id or not decision.evidence_valid:
            fallback.llm_rejected_reason = "sem evidência documental íntegra para o LLM citar"
            return fallback
        try:
            raw = self.llm.complete_json(EXPLAIN_SYSTEM, self._prompt(case, decision),
                                         EXPLAIN_SCHEMA)
        except LLMError as exc:
            fallback.llm_rejected_reason = str(exc)
            return fallback
        fallback.llm_raw = raw
        reason = None
        if raw.get("decisao") != decision.status:
            reason = f"LLM contradisse a decisão ({raw.get('decisao')} != {decision.status})"
        elif set(raw.get("documentos_citados") or []) - {decision.document_id}:
            reason = "LLM citou documento fora da evidência da regra"
        elif not str(raw.get("resposta", "")).strip():
            reason = "resposta vazia"
        if reason:
            fallback.llm_rejected_reason = reason
            return fallback
        return Answer(cid, decision.status, raw["resposta"].strip(), "llm", self.llm.model,
                      decision.to_dict(), None, raw)


class LLMOnlyBaseline:
    """Condição B1: decisão tomada pelo LLM a partir dos documentos, sem regras.

    Sem ``retriever``, o LLM recebe todos os documentos. Com um
    ``retrieval.SemanticRetriever`` (B1-RAG), recebe só os mais próximos da
    pergunta; se nenhum passar do limiar de confiança, o caso vai para
    revisão humana sem chamada ao LLM.
    """

    def __init__(self, knowledge: dict[str, Any], llm: LLMClient, retriever: Any = None):
        self.knowledge = knowledge
        self.llm = llm
        self.retriever = retriever

    def decide(self, case: dict[str, Any]) -> dict[str, Any]:
        source_docs = self.knowledge.get("documents", [])
        retrieval = None
        if self.retriever is not None:
            from .retrieval import case_query
            try:
                hits = self.retriever.retrieve(case_query(case))
            except LLMError as exc:
                return {"case_id": case.get("id"), "status": "ERRO", "error": str(exc),
                        "model": self.llm.model}
            retrieval = [{"id": h["id"], "score": h["score"]} for h in hits]
            if not self.retriever.confident(hits):
                return {"case_id": case.get("id"), "status": "REVISAO_HUMANA",
                        "document_id": None, "model": None, "retrieval": retrieval,
                        "justificativa": "Confiança da recuperação abaixo do limiar."}
            source_docs = [h["doc"] for h in hits]
        docs = [{"id": d.get("id"), "titulo": d.get("title"), "texto": d.get("content")}
                for d in source_docs]
        prompt = json.dumps({"pergunta": case.get("question", ""),
                             "fatos_do_caso": case.get("facts", {}), "documentos": docs},
                            ensure_ascii=False, indent=2, sort_keys=True)
        try:
            raw = self.llm.complete_json(DECIDE_SYSTEM, prompt, DECIDE_SCHEMA)
        except LLMError as exc:
            return {"case_id": case.get("id"), "status": "ERRO", "error": str(exc),
                    "model": self.llm.model}
        status = raw.get("decisao")
        return {"case_id": case.get("id"), "retrieval": retrieval,
                "status": status if status in VALID_DECISIONS else "ERRO",
                "document_id": raw.get("documento_id"),
                "justificativa": raw.get("justificativa"), "model": self.llm.model}
