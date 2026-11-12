"""Benchmark com LLM real: B1 (LLM decide) x P (SDD decide, LLM explica).

Cada condição roda com documentos sincronizados (v2) e com documentos antigos
(v1) diante da política vigente (spec v2). O rótulo esperado é sempre
``expected_v2``. Use um cache (``CachedLLM``) para reproduzir sem custo.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Callable

from .agent import LLMOnlyBaseline, SDDAssistant
from .core import BLOCKED, PolicyAgent
from .llm import LLMClient

SCENARIOS = [("docs_v2", "v2"), ("docs_v1_antigos", "v1")]


def run_llm_benchmark(spec: dict[str, Any], knowledge_by_version: dict[str, dict[str, Any]],
                      cases: list[dict[str, Any]], llm: LLMClient,
                      output_dir: Path | None = None,
                      retriever_factory: Callable[[dict[str, Any]], Any] | None = None
                      ) -> dict[str, Any]:
    """``retriever_factory(knowledge)`` acrescenta a condição B1-RAG."""
    rows: list[dict[str, Any]] = []
    conditions = ["B1_llm_decide", "P_sdd_llm_explica"]
    if retriever_factory is not None:
        conditions.insert(1, "B1R_rag_llm_decide")
    for scenario, kv in SCENARIOS:
        kn = knowledge_by_version[kv]
        baseline = LLMOnlyBaseline(kn, llm)
        rag = LLMOnlyBaseline(kn, llm, retriever_factory(kn)) if retriever_factory else None
        assistant = SDDAssistant(PolicyAgent(spec, kn, enforce_sdd=True), llm)
        for case in cases:
            expected = case["expected_v2"]
            p = baseline.decide(case)
            rows.append({"scenario": scenario, "condition": "B1_llm_decide", "case": case["id"],
                         "expected": expected, "status": p["status"],
                         "correct": p["status"] == expected, "blocked": False,
                         "llm_text_used": p["status"] != "ERRO", "note": p.get("error", "")})
            if rag is not None:
                r = rag.decide(case)
                rows.append({"scenario": scenario, "condition": "B1R_rag_llm_decide",
                             "case": case["id"], "expected": expected, "status": r["status"],
                             "correct": r["status"] == expected, "blocked": False,
                             "llm_text_used": r.get("model") is not None and r["status"] != "ERRO",
                             "note": r.get("error", "") or json.dumps(r.get("retrieval"))})
            a = assistant.answer(case)
            rows.append({"scenario": scenario, "condition": "P_sdd_llm_explica",
                         "case": case["id"], "expected": expected, "status": a.status,
                         "correct": a.status == expected, "blocked": a.status == BLOCKED,
                         "llm_text_used": a.source == "llm",
                         "note": a.llm_rejected_reason or ""})

    summary = []
    for scenario, _ in SCENARIOS:
        for condition in conditions:
            sel = [r for r in rows if r["scenario"] == scenario and r["condition"] == condition]
            emitted = [r for r in sel if not r["blocked"]]
            summary.append({
                "scenario": scenario, "condition": condition, "cases": len(sel),
                "blocked": len(sel) - len(emitted),
                "emitted_correct": sum(r["correct"] for r in emitted),
                "emitted_wrong": sum(not r["correct"] for r in emitted),
                "llm_text_used": sum(r["llm_text_used"] for r in sel),
            })
    result = {"protocol": "llm-benchmark-v0.3", "model": llm.model,
              "summary": summary, "observations": rows}
    if output_dir is not None:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        for name, data in (("llm_observations.csv", rows), ("llm_summary.csv", summary)):
            with open(output_dir / name, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=list(data[0]))
                w.writeheader()
                w.writerows(data)
        with open(output_dir / "llm_summary.json", "w", encoding="utf-8") as f:
            json.dump({k: v for k, v in result.items() if k != "observations"}, f,
                      indent=2, ensure_ascii=False)
    return result
