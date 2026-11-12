"""Experimento de mutações: sensibilidade e alarmes falsos do validador.

Cada operador parte do par sincronizado (spec v2, documentos v2) e produz um
mutante com rótulo de verdade definido a priori:

* ``drift=True``: os artefatos passam a divergir em significado (deveria
  alertar);
* ``drift=False``: mudança benigna ou evolução completa e sincronizada (não
  deveria alertar).

Os níveis L0-L3 de ``core.LEVELS`` são ablações cumulativas do validador.
Com um ``SemanticVerifier`` (LLM), o estudo acrescenta o nível L4_semantica.
O rótulo ``drift`` foi atribuído pelo autor; não há revisão independente.
"""
from __future__ import annotations

import copy
import csv
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .core import BLOCKED, LEVELS, PolicyAgent, check
from .evolution import synchronize

Artifacts = tuple[dict[str, Any], dict[str, Any]]


def _rule(spec: dict, rid: str) -> dict:
    return next(r for r in spec["rules"] if r["id"] == rid)


def _doc(kn: dict, did: str) -> dict:
    return next(d for d in kn["documents"] if d["id"] == did)


def _clause(rule: dict, field_name: str) -> dict:
    return next(c for c in rule["when"]["all"] if c["field"] == field_name)


# ------------------------------------------------------------- operadores

def m01_limiar(spec, kn):
    _clause(_rule(spec, "REG-PREMIUM-EXC"), "horas_apos_despacho")["value"] = 2.0
    return spec, kn


def m02_precedencia(spec, kn):
    a, b = _rule(spec, "REG-PREMIUM-EXC"), _rule(spec, "REG-CANCEL-ENVIADO")
    a["priority"], b["priority"] = b["priority"], a["priority"]
    return spec, kn


def m03_decisao(spec, kn):
    _rule(spec, "REG-CANCEL-PRE")["decision"] = "NEGAR"
    return spec, kn


def m04_regra_removida(spec, kn):
    spec["rules"] = [r for r in spec["rules"] if r["id"] != "REG-PREMIUM-EXC"]
    return spec, kn


def m05_requisito_removido(spec, kn):
    spec["requirements"] = [q for q in spec["requirements"] if q["id"] != "REQ-05"]
    return spec, kn


def m06_requisito_orfao(spec, kn):
    spec["requirements"].append({
        "id": "REQ-06",
        "description": "Cliente premium com atraso superior a 2 horas recebe reembolso.",
        "acceptance_criterion": "Premium e atraso > 2h, sem fraude: PERMITIR.",
    })
    return spec, kn


def m07_justificativa(spec, kn):
    _rule(spec, "REG-PREMIUM-EXC")["rationale"] = "Exceção premium: até 2 horas após despacho."
    return spec, kn


def m08_atualizacao_parcial(spec, kn):
    _doc(kn, "DOC-SEG")["version"] = "1"
    return spec, kn


def m09_texto_editado(spec, kn):
    _doc(kn, "DOC-CANCEL")["content"] = (
        "Cancelamento antes do despacho é permitido. Após despacho, é sempre negado.")
    return spec, kn


def m10_texto_invertido_ressincronizado(spec, kn):
    spec, kn = m09_texto_editado(spec, kn)
    return synchronize(spec, kn)


def m11_regra_alterada_ressincronizada(spec, kn):
    spec, kn = m01_limiar(spec, kn)
    return synchronize(spec, kn)


def m12_base_documental_antiga(spec, kn, *, stale: dict | None = None):
    return spec, copy.deepcopy(stale)


def n01_reordenar_regras(spec, kn):
    spec["rules"] = list(reversed(spec["rules"]))
    return spec, kn


def n02_reordenar_documentos(spec, kn):
    kn["documents"] = list(reversed(kn["documents"]))
    return spec, kn


def n03_reordenar_requisitos_da_regra(spec, kn):
    r = _rule(spec, "REG-SEG")
    r["requirement_ids"] = list(reversed(r["requirement_ids"]))
    return spec, kn


def n04_metadados(spec, kn):
    spec["effective_date"] = "2026-12-01"
    spec["scope"] = spec.get("scope", "") + " (revisão editorial)"
    return spec, kn


def n05_correcao_ortografica(spec, kn):
    d = _doc(kn, "DOC-FALHA")
    d["content"] = d["content"].replace("transportadora gera", "transportadora, gera")
    return spec, kn


def n06_evolucao_sincronizada(spec, kn):
    _clause(_rule(spec, "REG-PREMIUM-EXC"), "horas_apos_despacho")["value"] = 2.0
    _rule(spec, "REG-PREMIUM-EXC")["rationale"] = "Exceção premium: pedido cancelado até 2 horas após despacho."
    d = _doc(kn, "DOC-CANCEL")
    d["content"] = d["content"].replace("até 1 hora", "até 2 horas")
    q = next(q for q in spec["requirements"] if q["id"] == "REQ-05")
    q["acceptance_criterion"] = q["acceptance_criterion"].replace("até 1 hora", "até 2 horas")
    return synchronize(spec, kn)


@dataclass(frozen=True)
class Mutation:
    id: str
    family: str
    description: str
    drift: bool
    operator: Callable[..., Artifacts]
    affected_docs: frozenset[str] = field(default_factory=frozenset)


ALL_DOCS = frozenset({"DOC-SEG", "DOC-FALHA", "DOC-CANCEL"})
C = frozenset({"DOC-CANCEL"})

MUTATIONS: list[Mutation] = [
    Mutation("M01", "regra", "Limiar da exceção premium muda (1h->2h) só na spec", True, m01_limiar, C),
    Mutation("M02", "regra", "Precedência trocada entre exceção e regra geral", True, m02_precedencia, C),
    Mutation("M03", "regra", "Decisão invertida em REG-CANCEL-PRE", True, m03_decisao, C),
    Mutation("M04", "regra", "Regra de exceção removida; documento ainda a descreve", True, m04_regra_removida, C),
    Mutation("M05", "requisito", "REQ-05 removido; regra e documento ainda o citam", True, m05_requisito_removido, C),
    Mutation("M06", "requisito", "Requisito novo sem regra que o implemente", True, m06_requisito_orfao, frozenset()),
    Mutation("M07", "regra", "Justificativa da regra contradiz o documento", True, m07_justificativa, C),
    Mutation("M08", "documento", "Atualização parcial: DOC-SEG ficou na versão 1", True, m08_atualizacao_parcial, frozenset({"DOC-SEG"})),
    Mutation("M09", "documento", "Texto do DOC-CANCEL perde a exceção, sem revisão", True, m09_texto_editado, C),
    Mutation("M10", "semantica", "Texto perde a exceção e marcas são recalculadas", True, m10_texto_invertido_ressincronizado, C),
    Mutation("M11", "semantica", "Limiar muda e marcas são recalculadas sem editar o texto", True, m11_regra_alterada_ressincronizada, C),
    Mutation("M12", "documento", "Base documental v1 inteira com spec v2", True, m12_base_documental_antiga, ALL_DOCS),
    Mutation("N01", "benigna", "Regras reordenadas no arquivo", False, n01_reordenar_regras),
    Mutation("N02", "benigna", "Documentos reordenados no arquivo", False, n02_reordenar_documentos),
    Mutation("N03", "benigna", "Ordem de requirement_ids alterada", False, n03_reordenar_requisitos_da_regra),
    Mutation("N04", "benigna", "Metadados editoriais (data, escopo)", False, n04_metadados),
    Mutation("N05", "benigna", "Correção de pontuação no texto de DOC-FALHA", False, n05_correcao_ortografica),
    Mutation("N06", "benigna", "Evolução completa e sincronizada (limiar 2h em regra e texto)", False, n06_evolucao_sincronizada),
]


def apply(mutation: Mutation, spec: dict, kn: dict, stale_kn: dict) -> Artifacts:
    s, k = copy.deepcopy(spec), copy.deepcopy(kn)
    if mutation.operator is m12_base_documental_antiga:
        return mutation.operator(s, k, stale=stale_kn)
    return mutation.operator(s, k)


def _rate(num: int, den: int) -> float | None:
    return round(num / den, 4) if den else None


def run_mutation_study(spec: dict, kn: dict, stale_kn: dict, cases: list[dict],
                       output_dir: Path | None = None, verifier: Any = None,
                       prefix: str = "mutation") -> dict[str, Any]:
    """Executa todos os mutantes em todos os níveis e agrega as métricas.

    ``verifier`` (``semantic.SemanticVerifier``) acrescenta o nível L4.
    """
    levels: dict[str, Any] = dict(LEVELS)
    if verifier is not None:
        levels["L4_semantica"] = "semantica"
    rows: list[dict[str, Any]] = []
    for m in MUTATIONS:
        ms, mk = apply(m, spec, kn, stale_kn)
        # Oráculo: para deriva, a política pretendida continua sendo a v2;
        # para mudança benigna, é o próprio mutante (evolução intencional).
        oracle_agent = PolicyAgent(ms, mk, enforce_sdd=False) if not m.drift else None
        for level, cats in levels.items():
            if cats == "semantica":
                semantic = verifier.check(ms, mk)
                issues = check(ms, mk, LEVELS["L3_completa"]) + semantic
                agent = PolicyAgent(ms, mk, enforce_sdd=True,
                                    extra_errors=[str(i) for i in semantic])
            else:
                issues = check(ms, mk, cats)
                agent = PolicyAgent(ms, mk, enforce_sdd=True, categories=cats)
            wrong = blocked = divergent = 0
            for case in cases:
                d = agent.decide(case)
                if d.status == BLOCKED:
                    blocked += 1
                    continue
                expected = (case["expected_v2"] if m.drift
                            else oracle_agent.decide(case).status)
                wrong += d.status != expected
                divergent += bool(m.drift and d.document_id in m.affected_docs)
            rows.append({
                "mutation": m.id, "family": m.family, "drift": m.drift, "level": level,
                "detected": bool(issues), "n_issues": len(issues),
                "categories": "|".join(sorted({i.category for i in issues})),
                "cases": len(cases), "blocked": blocked,
                "emitted_wrong": wrong, "emitted_divergent_evidence": divergent,
            })

    summary = []
    for level in levels:
        lr = [r for r in rows if r["level"] == level]
        tp = sum(r["detected"] and r["drift"] for r in lr)
        fn = sum(not r["detected"] and r["drift"] for r in lr)
        fp = sum(r["detected"] and not r["drift"] for r in lr)
        tn = sum(not r["detected"] and not r["drift"] for r in lr)
        summary.append({
            "level": level, "mutants": len(lr), "tp": tp, "fn": fn, "fp": fp, "tn": tn,
            "sensitivity": _rate(tp, tp + fn), "false_alarm_rate": _rate(fp, fp + tn),
            "precision": _rate(tp, tp + fp),
            "missed": "|".join(r["mutation"] for r in lr if r["drift"] and not r["detected"]),
            "false_alarms": "|".join(r["mutation"] for r in lr if not r["drift"] and r["detected"]),
            "emitted_wrong": sum(r["emitted_wrong"] for r in lr),
            "emitted_divergent_evidence": sum(r["emitted_divergent_evidence"] for r in lr),
            "blocked_decisions": sum(r["blocked"] for r in lr),
            "blocked_benign_decisions": sum(r["blocked"] for r in lr if not r["drift"]),
        })

    protocol = "offline-mutation-v0.1"
    if verifier is not None:
        protocol = f"llm-mutation-v0.2 ({getattr(verifier.llm, 'model', '?')})"
    result = {"protocol": protocol, "levels": summary, "observations": rows,
              "mutations": [{"id": m.id, "family": m.family, "drift": m.drift,
                             "description": m.description} for m in MUTATIONS]}
    if output_dir is not None:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        for name, data in ((f"{prefix}_observations.csv", rows), (f"{prefix}_summary.csv", summary)):
            with open(output_dir / name, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=list(data[0]))
                w.writeheader()
                w.writerows(data)
        with open(output_dir / f"{prefix}_summary.json", "w", encoding="utf-8") as f:
            json.dump({k: v for k, v in result.items() if k != "observations"}, f,
                      indent=2, ensure_ascii=False)
    return result
