import contextlib
import copy
import io
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from evopolicy.cli import main
from evopolicy.core import (BLOCKED, LEVELS, PolicyAgent, check, document_digest,
                            retrieve, rule_fingerprint, validate)
from evopolicy.evolution import decision_record, diff_specs, impact, synchronize, trace_matrix
from evopolicy.experiment import check_cases, run_benchmark
from evopolicy.project import (available_versions, find_root, load_agent, load_cases,
                               load_knowledge, load_spec)

ROOT = find_root(Path(__file__).resolve().parents[1])
CASES = {c["id"]: c for c in load_cases(ROOT)}


def artifacts(version="v2"):
    return load_spec(ROOT, version), load_knowledge(ROOT, version)


def agent(spec_v="v2", doc_v=None, sdd=True):
    return load_agent(ROOT, spec_v, doc_v, sdd)


class ValidationTests(unittest.TestCase):
    def test_versions_discovered(self):
        self.assertEqual(available_versions(ROOT), ["v1", "v2"])

    def test_v1_and_v2_valid(self):
        for v in ("v1", "v2"):
            with self.subTest(version=v):
                self.assertEqual(agent(v).errors, [])

    def test_stale_docs_rejected(self):
        errors = agent("v2", "v1").errors
        self.assertTrue(any(e.startswith("[versao]") for e in errors))
        self.assertTrue(any(e.startswith("[fingerprint]") for e in errors))

    def test_bad_fingerprint_detected(self):
        spec, docs = artifacts()
        docs["documents"][0]["rule_fingerprints"]["REG-SEG"] = "0000"
        self.assertTrue(any("fingerprint" in e for e in validate(spec, docs)))

    def test_deleted_requirement_detected(self):
        spec, docs = artifacts()
        spec["requirements"] = [q for q in spec["requirements"] if q["id"] != "REQ-05"]
        self.assertTrue(any("requisito inexistente" in e for e in validate(spec, docs)))

    def test_deleted_document_detected(self):
        spec, docs = artifacts()
        docs["documents"] = [d for d in docs["documents"] if d["id"] != "DOC-CANCEL"]
        self.assertTrue(any("documento inexistente" in e for e in validate(spec, docs)))

    def test_orphan_requirement_detected(self):
        spec, docs = artifacts()
        spec["requirements"].append({"id": "REQ-99", "description": "x", "acceptance_criterion": "y"})
        self.assertIn("[cobertura] REQ-99: requisito sem regra que o implemente", validate(spec, docs))

    def test_rationale_change_breaks_fingerprint(self):
        spec, docs = artifacts()
        spec["rules"][0]["rationale"] = "outra justificativa"
        self.assertTrue(any(e.startswith("[fingerprint] REG-SEG") for e in validate(spec, docs)))

    def test_document_text_change_detected_by_digest(self):
        spec, docs = artifacts()
        doc = next(d for d in docs["documents"] if d["id"] == "DOC-CANCEL")
        doc["content"] = "Cancelamento após despacho é sempre negado."
        errors = validate(spec, docs)
        self.assertEqual(errors, ["[digest] DOC-CANCEL: texto alterado sem revisão da especificação"])

    def test_resynchronized_semantic_drift_is_a_known_limit(self):
        """Texto contradiz a regra, mas marcas recalculadas: nada é detectado (QP4)."""
        spec, docs = artifacts()
        doc = next(d for d in docs["documents"] if d["id"] == "DOC-CANCEL")
        doc["content"] = "Cancelamento após despacho é sempre negado."
        spec, docs = synchronize(spec, docs)
        self.assertEqual(validate(spec, docs), [])

    def test_schema_type_checks(self):
        spec, docs = artifacts()
        clause = spec["rules"][1]["when"]["all"][0]
        clause["value"] = "restaurante"  # 'in' exige lista
        spec, docs = synchronize(spec, docs)
        self.assertTrue(any("exige lista" in e for e in validate(spec, docs)))
        spec2, docs2 = artifacts()
        spec2["rules"][0]["when"]["all"][0]["value"] = "sim"  # bool esperado
        spec2, docs2 = synchronize(spec2, docs2)
        self.assertTrue(any("deve ser bool" in e for e in validate(spec2, docs2)))

    def test_duplicate_priority_detected(self):
        spec, docs = artifacts()
        spec["rules"][1]["priority"] = spec["rules"][0]["priority"]
        spec, docs = synchronize(spec, docs)
        self.assertIn("[esquema] Prioridades duplicadas tornam a precedência ambígua",
                      validate(spec, docs))

    def test_levels_are_cumulative(self):
        names = list(LEVELS)
        for a, b in zip(names, names[1:]):
            self.assertTrue(LEVELS[a] <= LEVELS[b])
        spec, docs = artifacts()
        self.assertEqual(check(spec, load_knowledge(ROOT, "v1"), LEVELS["L0_sem_verificacao"]), [])

    def test_synchronize_is_idempotent_on_valid_artifacts(self):
        spec, docs = artifacts()
        self.assertEqual(synchronize(spec, docs), (spec, docs))

    def test_dataset_is_well_formed(self):
        self.assertEqual(check_cases(load_spec(ROOT, "v2"), list(CASES.values())), [])


class DecisionTests(unittest.TestCase):
    def test_guard_blocks_every_case_in_mismatch(self):
        a = agent("v2", "v1")
        for cid, case in CASES.items():
            with self.subTest(case=cid):
                d = a.decide(case)
                self.assertEqual(d.status, BLOCKED)
                self.assertIsNone(d.evidence_valid)

    def test_goldens(self):
        for v in ("v1", "v2"):
            a = agent(v)
            for cid, case in CASES.items():
                with self.subTest(version=v, case=cid):
                    self.assertEqual(a.decide(case).status, case[f"expected_{v}"])

    def test_priority_fraud_over_exception(self):
        self.assertEqual(agent().decide(CASES["C10"]).rule_id, "REG-SEG")

    def test_premium_boundary_one_hour(self):
        self.assertEqual(agent().decide(CASES["C06"]).status, "PERMITIR")
        self.assertEqual(agent().decide(CASES["C07"]).status, "NEGAR")

    def test_premium_unknown_time_falls_back_to_deny(self):
        self.assertEqual(agent().decide(CASES["C13"]).status, "NEGAR")

    def test_unknown_request_uses_default_decision(self):
        d = agent().decide(CASES["C11"])
        self.assertEqual(d.status, "REVISAO_HUMANA")
        self.assertIsNone(d.evidence_valid)

    def test_default_decision_comes_from_spec(self):
        spec, docs = artifacts()
        spec["default_decision"] = "NEGAR"
        self.assertEqual(PolicyAgent(spec, docs).decide(CASES["C11"]).status, "NEGAR")

    def test_baseline_can_use_stale_evidence(self):
        d = agent("v2", "v1", sdd=False).decide(CASES["C05"])
        self.assertEqual(d.status, "PERMITIR")
        self.assertFalse(d.evidence_valid)

    def test_sdd_decision_has_trace(self):
        d = agent().decide(CASES["C05"])
        self.assertEqual((d.rule_id, d.document_id), ("REG-PREMIUM-EXC", "DOC-CANCEL"))
        self.assertIn("REQ-05", d.requirement_ids)
        self.assertTrue(d.evidence_valid)
        rec = decision_record(d, CASES["C05"], timestamp=False)
        self.assertEqual(rec["rule_fingerprint"],
                         rule_fingerprint(next(r for r in load_spec(ROOT, "v2")["rules"]
                                               if r["id"] == "REG-PREMIUM-EXC")))
        self.assertEqual(len(rec["spec_digest"]), 64)

    def test_retriever_is_deterministic(self):
        docs = load_knowledge(ROOT, "v2")
        self.assertEqual(retrieve("cancelamento premium", docs),
                         retrieve("cancelamento premium", docs))


class EvolutionTests(unittest.TestCase):
    def test_diff_v1_v2(self):
        diff = diff_specs(load_spec(ROOT, "v1"), load_spec(ROOT, "v2"))
        self.assertEqual(diff["requisitos"]["adicionados"], ["REQ-05"])
        self.assertEqual(diff["regras"]["adicionados"], ["REG-PREMIUM-EXC"])
        self.assertEqual(diff["regras"]["alterados"], {})

    def test_impact_matches_label_changes(self):
        changed = {i["case_id"] for i in impact(list(CASES.values()),
                                                agent("v1", sdd=False), agent("v2", sdd=False))}
        expected = {cid for cid, c in CASES.items() if c["expected_v1"] != c["expected_v2"]}
        self.assertEqual(changed, expected)

    def test_trace_matrix(self):
        rows = trace_matrix(*artifacts())
        self.assertTrue(all(r["status"] == "OK" for r in rows))
        stale = trace_matrix(load_spec(ROOT, "v2"), load_knowledge(ROOT, "v1"))
        self.assertIn("FINGERPRINT_DIVERGENTE", {r["status"] for r in stale})


class ExperimentTests(unittest.TestCase):
    def test_benchmark_output(self):
        with TemporaryDirectory() as td:
            res = run_benchmark(ROOT, Path(td))
            self.assertEqual(len(res), 5)
            for name in ("observations.csv", "summary.csv", "summary.json", "decisions.jsonl"):
                self.assertTrue((Path(td) / name).is_file())
            by = {s["condition"]: s for s in res}
            self.assertEqual(by["P1_sdd_sincronizado"]["accuracy"], 1.0)
            self.assertEqual(by["P2_sdd_documento_antigo"]["blocked"], len(CASES))
            self.assertEqual(by["B1_hibrido_desatualizado"]["correct"], len(CASES) - 3)
            self.assertEqual(by["B3_hibrido_documento_antigo"]["invalid_evidence"], 16)

    def test_mutation_study(self):
        from evopolicy.mutations import run_mutation_study
        with TemporaryDirectory() as td:
            res = run_mutation_study(load_spec(ROOT, "v2"), load_knowledge(ROOT, "v2"),
                                     load_knowledge(ROOT, "v1"), list(CASES.values()), Path(td))
            self.assertTrue((Path(td) / "mutation_summary.csv").is_file())
        lv = {s["level"]: s for s in res["levels"]}
        sens = [lv[n]["sensitivity"] for n in LEVELS]
        self.assertEqual(sens, sorted(sens))  # ablação: sensibilidade não diminui
        self.assertEqual(lv["L0_sem_verificacao"]["tp"], 0)
        self.assertEqual(lv["L3_completa"]["missed"], "M10|M11")  # limite semântico
        self.assertEqual(lv["L3_completa"]["false_alarms"], "N05")  # custo do digest

    def test_mutants_do_not_alter_originals(self):
        from evopolicy.mutations import MUTATIONS, apply
        spec, docs = artifacts()
        before = copy.deepcopy((spec, docs))
        for m in MUTATIONS:
            apply(m, spec, docs, load_knowledge(ROOT, "v1"))
        self.assertEqual((spec, docs), before)


class CliTests(unittest.TestCase):
    def setUp(self):
        self._quiet = contextlib.redirect_stdout(io.StringIO())
        self._quiet.__enter__()
        self.addCleanup(self._quiet.__exit__, None, None, None)

    def test_validate_exit_codes(self):
        self.assertEqual(main(["--root", str(ROOT), "validate"]), 0)
        self.assertEqual(main(["--root", str(ROOT), "validate", "--doc-version", "v1"]), 2)

    def test_unknown_version_rejected(self):
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            main(["--root", str(ROOT), "validate", "--spec-version", "v9"])

    def test_decide_log(self):
        with TemporaryDirectory() as td:
            log = Path(td) / "d.jsonl"
            main(["--root", str(ROOT), "decide", "--case", "C05", "--log", str(log)])
            rec = json.loads(log.read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(rec["rule_id"], "REG-PREMIUM-EXC")
            self.assertIn("timestamp", rec)

    def test_root_from_env_outside_repo(self):
        """Regressão: com pacote instalado, a CLI não pode depender de site-packages."""
        with TemporaryDirectory() as td:
            env = dict(os.environ, EVOPOLICY_ROOT=str(ROOT),
                       PYTHONPATH=str(ROOT / "src"))
            out = subprocess.run([sys.executable, "-m", "evopolicy", "validate"],
                                 cwd=td, env=env, capture_output=True, text=True)
            self.assertEqual(out.returncode, 0, out.stderr)


if __name__ == "__main__":
    unittest.main()
