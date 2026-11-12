"""Benchmark exploratório e determinístico; nenhuma inferência com LLM."""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from .core import BLOCKED, VALID_DECISIONS, spec_fields, value_has_type
from .evolution import decision_record
from .project import load_agent, load_cases

CONFIGURATIONS = [
    # nome, regras, documentos, guarda SDD
    ("B1_hibrido_desatualizado", "v1", "v1", False),
    ("B2_hibrido_atualizado", "v2", "v2", False),
    ("B3_hibrido_documento_antigo", "v2", "v1", False),
    ("P1_sdd_sincronizado", "v2", "v2", True),
    ("P2_sdd_documento_antigo", "v2", "v1", True),
]


def check_cases(spec: dict[str, Any], cases: list[dict[str, Any]]) -> list[str]:
    """Problemas do dataset: IDs duplicados, campos desconhecidos, rótulos inválidos."""
    fields = spec_fields(spec)
    problems = []
    ids = [c.get("id") for c in cases]
    if len(ids) != len(set(ids)):
        problems.append("IDs de casos duplicados")
    for c in cases:
        for k, v in c.get("facts", {}).items():
            if k not in fields:
                problems.append(f"{c.get('id')}: campo desconhecido {k}")
            elif v is not None and not value_has_type(v, fields[k]):
                problems.append(f"{c.get('id')}: {k} deveria ser {fields[k]}")
        for key in ("expected_v1", "expected_v2"):
            if c.get(key) not in VALID_DECISIONS:
                problems.append(f"{c.get('id')}: rótulo {key} inválido")
    return problems


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def run_benchmark(root: Path, output_dir: Path | None = None) -> list[dict[str, Any]]:
    cases = load_cases(root)
    output_dir = Path(output_dir) if output_dir else root / "results"
    output_dir.mkdir(parents=True, exist_ok=True)
    observations: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    for name, spec_v, doc_v, enforce in CONFIGURATIONS:
        agent = load_agent(root, spec_v, doc_v, enforce)
        n = len(cases)
        correct = blocked = invalid = no_evidence = wrong_permits = 0
        for case in cases:
            result = agent.decide(case)
            expected = case["expected_v2"]
            is_blocked = result.status == BLOCKED
            blocked += is_blocked
            correct += result.status == expected
            invalid += result.evidence_valid is False
            no_evidence += result.evidence_valid is None
            wrong_permits += result.status == "PERMITIR" and expected != "PERMITIR"
            observations.append({
                "condition": name, "case_id": case["id"], "expected": expected,
                "observed": result.status, "correct": result.status == expected,
                "blocked": is_blocked,
                "evidence": {True: "valida", False: "invalida", None: "nenhuma"}[result.evidence_valid],
                "rule_id": result.rule_id or "", "document_id": result.document_id or "",
                "specification_version": result.specification_version,
                "document_version": result.document_version or "",
            })
            rec = decision_record(result, case, timestamp=False)
            rec["condition"] = name
            records.append(rec)
        emitted = n - blocked
        summaries.append({
            "condition": name, "n": n,
            "correct": correct, "accuracy": round(correct / n, 4),
            "blocked": blocked, "block_rate": round(blocked / n, 4),
            "emitted": emitted,
            "accuracy_when_emitted": round(correct / emitted, 4) if emitted else None,
            "invalid_evidence": invalid, "no_evidence": no_evidence,
            "invalid_evidence_rate_when_emitted": round(invalid / emitted, 4) if emitted else None,
            "wrong_permits": wrong_permits,
            "structural_issues": len(agent.errors),
        })
    _write_csv(output_dir / "observations.csv", observations)
    _write_csv(output_dir / "summary.csv", summaries)
    with open(output_dir / "summary.json", "w", encoding="utf-8") as f:
        json.dump({"protocol": "offline-demo-v0.1", "summaries": summaries}, f,
                  indent=2, ensure_ascii=False)
    with open(output_dir / "decisions.jsonl", "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")
    return summaries
