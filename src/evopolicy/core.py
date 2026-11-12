"""Núcleo independente de provedor de LLM e de bibliotecas de embeddings.

A validação aqui é estrutural e criptográfica (fingerprints e digests), não
equivalência semântica de linguagem natural. A verificação semântica com LLM
(nível L4) fica em ``semantic.py`` e entra no guarda via ``extra_errors``.

Vínculos verificados (coevolução nos dois sentidos):

* documento -> regra: cada documento guarda o fingerprint de cada regra que
  o cita (``rule_fingerprints``). Mudou a regra sem revisar o documento:
  alerta ``fingerprint``.
* especificação -> documento: a especificação fixa o digest do texto de cada
  documento aprovado (``document_digests``). Mudou o texto sem revisar a
  especificação: alerta ``digest``.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

import yaml

VALID_DECISIONS = {"PERMITIR", "NEGAR", "REVISAO_HUMANA"}
VALID_OPS = {"eq", "in", "lte", "gte"}
BLOCKED = "BLOQUEADO"
FALLBACK_DEFAULT_DECISION = "REVISAO_HUMANA"

# Esquema usado quando a especificação não declara ``fields`` (compatibilidade).
LEGACY_FIELDS = {
    "fraude_suspeita": "bool", "falha_origem": "str", "cancelamento_cliente": "bool",
    "despachado": "bool", "cliente_premium": "bool", "horas_apos_despacho": "number",
}
FIELD_TYPES = {"bool", "str", "number"}

# Categorias de verificação. Os níveis são ablações cumulativas do validador
# e são usados no experimento de mutações (docs/PROTOCOLO_EXPERIMENTAL.md).
CATEGORIES = ("estrutura", "versao", "ids", "referencias", "fingerprint",
              "digest", "cobertura", "esquema")
LEVELS: dict[str, frozenset[str]] = {
    "L0_sem_verificacao": frozenset(),
    "L1_versao": frozenset({"estrutura", "versao"}),
    "L2_estrutural": frozenset({"estrutura", "versao", "ids", "referencias", "fingerprint"}),
    "L3_completa": frozenset(CATEGORIES),
}
FULL = LEVELS["L3_completa"]


# --------------------------------------------------------------------- E/S

def load_yaml(path: str | Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        result = yaml.safe_load(f)
    if not isinstance(result, dict):
        raise ValueError(f"Arquivo inválido: {path}")
    return result


def load_json(path: str | Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def canonical_digest(obj: Any) -> str:
    raw = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ------------------------------------------------------------ fingerprints

def rule_fingerprint(rule: dict[str, Any]) -> str:
    """Marca técnica do que a regra decide e de como se justifica.

    Inclui ``rationale`` e ``document_id`` porque ambos aparecem para o
    usuário como justificativa da decisão; ordem de ``requirement_ids`` não
    importa. Não cobre a prosa do documento (ver ``document_digest``).
    """
    selected = {
        "id": rule.get("id"), "when": rule.get("when"),
        "decision": rule.get("decision"), "priority": rule.get("priority"),
        "requirement_ids": sorted(rule.get("requirement_ids") or []),
        "rationale": rule.get("rationale"), "document_id": rule.get("document_id"),
    }
    return canonical_digest(selected)


def document_digest(doc: dict[str, Any]) -> str:
    """Digest do texto aprovado de um documento (id, título e conteúdo)."""
    return canonical_digest({"id": doc.get("id"), "title": doc.get("title"),
                             "content": doc.get("content")})


def spec_fields(spec: dict[str, Any]) -> dict[str, str]:
    fields = spec.get("fields")
    return dict(fields) if isinstance(fields, dict) else dict(LEGACY_FIELDS)


# ------------------------------------------------------------- validação

@dataclass(frozen=True)
class Issue:
    category: str
    message: str

    def __str__(self) -> str:
        return f"[{self.category}] {self.message}"


def value_has_type(value: Any, kind: str) -> bool:
    if kind == "bool":
        return isinstance(value, bool)
    if kind == "str":
        return isinstance(value, str)
    if kind == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return False


def _clause_issues(rid: str, clause: Any, fields: dict[str, str]) -> list[str]:
    if not isinstance(clause, dict):
        return [f"{rid}: cláusula inválida {clause!r}"]
    field, op, value = clause.get("field"), clause.get("op"), clause.get("value")
    if field not in fields or op not in VALID_OPS:
        return [f"{rid}: operador/campo inválido {clause}"]
    kind = fields[field]
    if op == "eq" and not value_has_type(value, kind):
        return [f"{rid}: valor de '{field}' deve ser {kind}"]
    if op == "in" and (not isinstance(value, list) or not value
                       or not all(value_has_type(v, kind) for v in value)):
        return [f"{rid}: operador 'in' em '{field}' exige lista não vazia de {kind}"]
    if op in {"lte", "gte"} and (kind != "number" or not value_has_type(value, "number")):
        return [f"{rid}: operador '{op}' exige campo e valor numéricos em '{field}'"]
    return []


def check(spec: dict[str, Any], knowledge: dict[str, Any],
          categories: Iterable[str] = FULL) -> list[Issue]:
    """Executa as verificações das categorias pedidas e devolve os problemas."""
    enabled = set(categories)
    if not enabled:
        return []
    issues: list[Issue] = []

    def add(category: str, message: str) -> None:
        if category in enabled:
            issues.append(Issue(category, message))

    version = str(spec.get("version", ""))
    reqs, rules, docs = spec.get("requirements"), spec.get("rules"), knowledge.get("documents")
    if (not version or not isinstance(reqs, list) or not isinstance(rules, list)
            or not isinstance(docs, list)):
        return [Issue("estrutura", "Estrutura de especificação ou base documental inválida")]

    # versão
    if str(knowledge.get("version", "")) != version:
        add("versao", f"Versões divergentes: spec={version}, docs={knowledge.get('version')}")
    for d in docs:
        if str(d.get("version")) != version:
            add("versao", f"{d.get('id')}: versão documental desatualizada ({d.get('version')} != {version})")

    # identificadores
    req_ids = [r.get("id") for r in reqs]
    rule_ids = [r.get("id") for r in rules]
    doc_ids = [d.get("id") for d in docs]
    for label, ids in (("requisitos", req_ids), ("regras", rule_ids), ("documentos", doc_ids)):
        if len(ids) != len(set(ids)) or None in ids:
            add("ids", f"IDs ausentes ou duplicados de {label}")

    # esquema
    fields = spec_fields(spec)
    if any(t not in FIELD_TYPES for t in fields.values()):
        add("esquema", "Tipo de campo inválido em 'fields'")
    if any(not r.get("acceptance_criterion") for r in reqs):
        add("esquema", "Todo requisito precisa ter critério de aceitação")
    if spec.get("default_decision", FALLBACK_DEFAULT_DECISION) not in VALID_DECISIONS:
        add("esquema", "default_decision inválida")
    priorities = [r.get("priority") for r in rules]
    if len(priorities) != len(set(priorities)):
        add("esquema", "Prioridades duplicadas tornam a precedência ambígua")

    by_doc = {d.get("id"): d for d in docs}
    linked: dict[Any, set[str]] = {d.get("id"): set() for d in docs}
    implemented: set[str] = set()
    for r in rules:
        rid = r.get("id", "<sem-id>")
        if r.get("decision") not in VALID_DECISIONS:
            add("esquema", f"{rid}: decisão inválida")
        if not isinstance(r.get("priority"), int) or isinstance(r.get("priority"), bool):
            add("esquema", f"{rid}: prioridade inválida")
        if not r.get("rationale"):
            add("esquema", f"{rid}: justificativa ausente")
        rq = r.get("requirement_ids") or []
        if not rq or any(q not in req_ids for q in rq):
            add("referencias", f"{rid}: requisito inexistente")
        implemented.update(rq)
        clauses = (r.get("when") or {}).get("all")
        if not isinstance(clauses, list) or not clauses:
            add("esquema", f"{rid}: condição ausente ou inválida")
        else:
            for c in clauses:
                for msg in _clause_issues(rid, c, fields):
                    add("esquema", msg)
        did = r.get("document_id")
        if did not in by_doc:
            add("referencias", f"{rid}: documento inexistente {did}")
            continue
        linked[did].add(rid)
        doc = by_doc[did]
        if (doc.get("rule_fingerprints") or {}).get(rid) != rule_fingerprint(r):
            add("fingerprint", f"{rid}: fingerprint incompatível no documento {did}")
        if not set(rq).issubset(set(doc.get("requirement_ids") or [])):
            add("referencias", f"{rid}: rastreabilidade incompleta em {did}")

    for did, doc in by_doc.items():
        if not doc.get("content"):
            add("esquema", f"{did}: conteúdo vazio")
        if set(doc.get("rule_fingerprints") or {}) != linked[did]:
            add("referencias", f"{did}: conjunto de regras do documento não coincide com a especificação")
        unknown = set(doc.get("requirement_ids") or []) - set(req_ids)
        if unknown:
            add("referencias", f"{did}: cita requisitos inexistentes {sorted(unknown)}")
        if not linked[did]:
            add("cobertura", f"{did}: documento não sustenta nenhuma regra")

    # digests: a especificação fixa o texto aprovado de cada documento
    pinned = spec.get("document_digests") or {}
    for did, doc in by_doc.items():
        if did not in pinned:
            add("digest", f"{did}: texto do documento não fixado na especificação")
        elif pinned[did] != document_digest(doc):
            add("digest", f"{did}: texto alterado sem revisão da especificação")
    for did in set(pinned) - set(by_doc):
        add("digest", f"{did}: digest fixado para documento inexistente")

    # cobertura: todo requisito precisa de pelo menos uma regra executável
    for q in req_ids:
        if q not in implemented:
            add("cobertura", f"{q}: requisito sem regra que o implemente")

    unique = sorted(set(issues), key=lambda i: (i.category, i.message))
    return unique


def validate(spec: dict[str, Any], knowledge: dict[str, Any],
             categories: Iterable[str] = FULL) -> list[str]:
    """Erros que impedem a publicação, como texto ``[categoria] mensagem``."""
    return [str(i) for i in check(spec, knowledge, categories)]


# ------------------------------------------------------------------ motor

def clause_matches(clause: dict[str, Any], facts: dict[str, Any]) -> bool:
    value = facts.get(clause["field"])
    if value is None:  # fato desconhecido nunca satisfaz uma condição
        return False
    op, target = clause["op"], clause["value"]
    is_number = isinstance(value, (int, float)) and not isinstance(value, bool)
    if op == "eq":
        return type(value) is type(target) and value == target
    if op == "in":
        return value in target
    if op == "lte":
        return is_number and value <= target
    if op == "gte":
        return is_number and value >= target
    return False


def match_rule(rule: dict[str, Any], facts: dict[str, Any]) -> bool:
    return all(clause_matches(c, facts) for c in rule["when"]["all"])


STOPWORDS = {"para", "com", "uma", "que", "por", "dos", "das", "esse", "essa",
             "sobre", "depois", "como"}


def tokens(text: str) -> set[str]:
    norm = unicodedata.normalize("NFKD", text.lower())
    norm = "".join(c for c in norm if not unicodedata.combining(c))
    return {w for w in re.findall(r"[a-z0-9]{3,}", norm) if w not in STOPWORDS}


def retrieve(question: str, knowledge: dict[str, Any], top_k: int = 3) -> list[dict[str, Any]]:
    """Recuperação lexical demonstrativa (Jaccard); NÃO equivale a embeddings ou LLM."""
    query = tokens(question)
    ranked = []
    for doc in knowledge.get("documents", []):
        dwords = tokens(f"{doc.get('title', '')} {doc.get('content', '')}")
        score = len(query & dwords) / max(1, len(query | dwords))
        ranked.append({"id": doc.get("id"), "score": round(score, 4)})
    return sorted(ranked, key=lambda v: (-v["score"], str(v["id"])))[:top_k]


@dataclass
class Decision:
    case_id: str
    status: str
    rule_id: str | None
    document_id: str | None
    document_version: str | None
    specification_version: str
    requirement_ids: list[str]
    rationale: str
    validation_errors: list[str]
    retrieval: list[dict[str, Any]]
    # True: evidência citada e íntegra; False: citada mas desatualizada ou
    # ausente; None: nenhuma evidência citada (bloqueio ou decisão padrão).
    evidence_valid: bool | None
    rule_fingerprint: str | None = None
    spec_digest: str = ""
    knowledge_digest: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PolicyAgent:
    """Motor determinístico com guarda SDD opcional (fail-closed)."""

    def __init__(self, spec: dict[str, Any], knowledge: dict[str, Any],
                 enforce_sdd: bool = True, categories: Iterable[str] = FULL,
                 extra_errors: Iterable[str] = ()):
        self.spec = spec
        self.knowledge = knowledge
        self.enforce_sdd = enforce_sdd
        # extra_errors: alertas de verificações externas (ex.: L4 semântico)
        self.errors = validate(spec, knowledge, categories) + list(extra_errors)
        self._docs = {d.get("id"): d for d in knowledge.get("documents", [])}
        self.spec_digest = canonical_digest(spec)
        self.knowledge_digest = canonical_digest(knowledge)
        self.default_decision = spec.get("default_decision", FALLBACK_DEFAULT_DECISION)
        if self.default_decision not in VALID_DECISIONS:
            self.default_decision = FALLBACK_DEFAULT_DECISION

    def _rules(self) -> list[dict[str, Any]]:
        return sorted(self.spec.get("rules", []), key=lambda r: (r["priority"], r["id"]))

    def decide(self, case: dict[str, Any]) -> Decision:
        version = str(self.spec.get("version", ""))
        case_id = case.get("id", "sem-id")
        retrieved = retrieve(case.get("question", ""), self.knowledge)
        common = {"spec_digest": self.spec_digest, "knowledge_digest": self.knowledge_digest}
        if self.enforce_sdd and self.errors:
            return Decision(case_id, BLOCKED, None, None, None, version, [],
                            "Publicação bloqueada: inconsistência entre artefatos.",
                            self.errors, retrieved, None, **common)
        facts = case.get("facts", {})
        for rule in self._rules():
            if match_rule(rule, facts):
                fp = rule_fingerprint(rule)
                document = self._docs.get(rule.get("document_id"))
                evidence_ok = bool(
                    document
                    and str(document.get("version")) == version
                    and (document.get("rule_fingerprints") or {}).get(rule["id"]) == fp
                )
                return Decision(case_id, rule["decision"], rule["id"],
                                document.get("id") if document else None,
                                str(document.get("version")) if document else None,
                                version, list(rule.get("requirement_ids", [])),
                                rule.get("rationale", ""), self.errors, retrieved,
                                evidence_ok, fp, **common)
        return Decision(case_id, self.default_decision, None, None, None, version, [],
                        "Nenhuma regra conclusiva; aplicada a decisão padrão da especificação.",
                        self.errors, retrieved, None, **common)
