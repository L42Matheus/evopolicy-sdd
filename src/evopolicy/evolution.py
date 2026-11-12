"""Evolução de políticas: diff entre versões, impacto, matriz e sincronização."""
from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .core import (PolicyAgent, canonical_digest, document_digest, rule_fingerprint)

RULE_FIELDS = ("priority", "when", "decision", "requirement_ids", "document_id", "rationale")
REQ_FIELDS = ("description", "acceptance_criterion")


def _diff_items(old: list[dict], new: list[dict], fields: tuple[str, ...]) -> dict[str, Any]:
    a = {x["id"]: x for x in old}
    b = {x["id"]: x for x in new}
    changed = {}
    for i in sorted(set(a) & set(b)):
        diffs = {f: {"antes": a[i].get(f), "depois": b[i].get(f)}
                 for f in fields if a[i].get(f) != b[i].get(f)}
        if diffs:
            changed[i] = diffs
    return {"adicionados": sorted(set(b) - set(a)),
            "removidos": sorted(set(a) - set(b)),
            "alterados": changed}


def diff_specs(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    """Diferença semântica-estrutural entre duas especificações."""
    result = {
        "de": str(old.get("version")), "para": str(new.get("version")),
        "requisitos": _diff_items(old.get("requirements", []), new.get("requirements", []), REQ_FIELDS),
        "regras": _diff_items(old.get("rules", []), new.get("rules", []), RULE_FIELDS),
    }
    for key in ("default_decision", "fields"):
        if old.get(key) != new.get(key):
            result[key] = {"antes": old.get(key), "depois": new.get(key)}
    return result


def impact(cases: list[dict], old_agent: PolicyAgent, new_agent: PolicyAgent) -> list[dict[str, Any]]:
    """Casos cuja decisão ou regra aplicada muda entre duas versões (sem guarda)."""
    out = []
    for case in cases:
        a, b = old_agent.decide(case), new_agent.decide(case)
        if (a.status, a.rule_id) != (b.status, b.rule_id):
            out.append({"case_id": case.get("id"),
                        "antes": {"status": a.status, "rule_id": a.rule_id},
                        "depois": {"status": b.status, "rule_id": b.rule_id}})
    return out


def trace_matrix(spec: dict[str, Any], knowledge: dict[str, Any]) -> list[dict[str, Any]]:
    """Matriz REQ -> regra -> documento, com estado de cada vínculo."""
    docs = {d["id"]: d for d in knowledge.get("documents", [])}
    rows = []
    for req in spec.get("requirements", []):
        rules = [r for r in spec.get("rules", []) if req["id"] in (r.get("requirement_ids") or [])]
        if not rules:
            rows.append({"requirement_id": req["id"], "rule_id": "", "document_id": "",
                         "status": "SEM_REGRA"})
            continue
        for r in rules:
            doc = docs.get(r.get("document_id"))
            if doc is None:
                status = "DOC_INEXISTENTE"
            elif (doc.get("rule_fingerprints") or {}).get(r["id"]) != rule_fingerprint(r):
                status = "FINGERPRINT_DIVERGENTE"
            elif (spec.get("document_digests") or {}).get(doc["id"]) != document_digest(doc):
                status = "TEXTO_NAO_APROVADO"
            elif str(doc.get("version")) != str(spec.get("version")):
                status = "VERSAO_DIVERGENTE"
            else:
                status = "OK"
            rows.append({"requirement_id": req["id"], "rule_id": r["id"],
                         "document_id": r.get("document_id", ""), "status": status})
    return rows


def synchronize(spec: dict[str, Any], knowledge: dict[str, Any]) -> tuple[dict, dict]:
    """Recalcula fingerprints nos documentos e digests na especificação.

    Deve ser executado SOMENTE depois de revisar que o texto dos documentos
    expressa as regras: recalcular marcas sem revisão é exatamente a
    mutação M08/M09 que o validador não consegue detectar.
    """
    spec, knowledge = copy.deepcopy(spec), copy.deepcopy(knowledge)
    by_doc: dict[str, dict[str, str]] = {d["id"]: {} for d in knowledge["documents"]}
    for r in spec.get("rules", []):
        if r.get("document_id") in by_doc:
            by_doc[r["document_id"]][r["id"]] = rule_fingerprint(r)
    for d in knowledge["documents"]:
        d["rule_fingerprints"] = by_doc[d["id"]]
    spec["document_digests"] = {d["id"]: document_digest(d) for d in knowledge["documents"]}
    return spec, knowledge


def decision_record(decision, case: dict[str, Any], timestamp: bool = True) -> dict[str, Any]:
    """Registro auditável de uma decisão (uma linha JSONL)."""
    rec = {
        "case_id": decision.case_id,
        "facts_digest": canonical_digest(case.get("facts", {})),
        "status": decision.status,
        "rule_id": decision.rule_id,
        "rule_fingerprint": decision.rule_fingerprint,
        "requirement_ids": decision.requirement_ids,
        "document_id": decision.document_id,
        "document_version": decision.document_version,
        "specification_version": decision.specification_version,
        "spec_digest": decision.spec_digest,
        "knowledge_digest": decision.knowledge_digest,
        "evidence_valid": decision.evidence_valid,
        "validation_errors": decision.validation_errors,
    }
    if timestamp:
        rec["timestamp"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return rec


def append_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")
