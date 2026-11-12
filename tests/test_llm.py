"""Testes offline da camada de LLM: nenhuma chamada de rede, nenhuma chave."""
import contextlib
import io
import json
import re
import importlib.util
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from evopolicy.agent import LLMOnlyBaseline, SDDAssistant
from evopolicy.cli import main
from evopolicy.core import BLOCKED, PolicyAgent
from evopolicy.experiment_llm import run_llm_benchmark
from evopolicy.llm import (DEFAULT_MODEL, FALLBACK_BETA, AnthropicClient, CachedLLM,
                           FakeLLM, LLMError, OpenAIClient)
from evopolicy.mutations import MUTATIONS, apply, run_mutation_study
from evopolicy.project import find_root, load_cases, load_knowledge, load_spec
from evopolicy.semantic import SemanticVerifier, check_l4

ROOT = find_root(Path(__file__).resolve().parents[1])
SPEC, KN, KN1 = load_spec(ROOT, "v2"), load_knowledge(ROOT, "v2"), load_knowledge(ROOT, "v1")
CASES = load_cases(ROOT)
CASE = {c["id"]: c for c in CASES}


def _payload(user: str) -> dict:
    return json.loads(user[user.index("{"):])


def heuristic_auditor(system: str, user: str) -> dict:
    """Auditor fictício: compara limiar em horas e presença da exceção premium."""
    data = _payload(user)
    text = data["documento"]["texto"] + " " + " ".join(
        q["acceptance_criterion"] for q in data["requisitos_ligados"])
    divergences = []
    for rule in data["regras_que_citam_o_documento"]:
        for c in rule["when"]["all"]:
            if c["field"] == "cliente_premium" and "premium" not in data["documento"]["texto"]:
                divergences.append({"regra_id": rule["id"], "aspecto": "excecao",
                                    "explicacao": "texto não prevê a exceção premium"})
            if c["field"] == "horas_apos_despacho":
                hours = {float(h) for h in re.findall(r"até (\d+) hora", text)}
                if hours and hours != {float(c["value"])}:
                    divergences.append({"regra_id": rule["id"], "aspecto": "limiar",
                                        "explicacao": f"regra usa {c['value']}h, texto {hours}"})
    return {"consistente": not divergences, "divergencias": divergences}


def explainer(decision_override=None, cite=None):
    def respond(system, user):
        data = _payload(user)
        return {"decisao": decision_override or data["decisao"],
                "resposta": f"Decisão {data['decisao']} conforme {data['documento']['id']}.",
                "documentos_citados": [cite or data["documento"]["id"]]}
    return respond


def failing(system, user):
    raise LLMError("indisponível no teste")


class SemanticTests(unittest.TestCase):
    def test_synchronized_artifacts_pass(self):
        llm = FakeLLM(heuristic_auditor)
        self.assertEqual(SemanticVerifier(llm).check(SPEC, KN), [])
        self.assertEqual(len(llm.calls), 3)  # um pedido por documento

    def test_resynchronized_drifts_detected(self):
        verifier = SemanticVerifier(FakeLLM(heuristic_auditor))
        for mid in ("M10", "M11"):
            m = next(m for m in MUTATIONS if m.id == mid)
            spec, kn = apply(m, SPEC, KN, KN1)
            issues = verifier.check(spec, kn)
            self.assertTrue(issues, mid)
            self.assertTrue(all(i.category == "semantica" for i in issues))

    def test_llm_failure_is_fail_closed(self):
        issues = SemanticVerifier(FakeLLM(failing)).check(SPEC, KN)
        self.assertEqual(len(issues), 3)
        self.assertIn("indisponível", issues[0].message)

    def test_out_of_schema_answer_is_fail_closed(self):
        issues = SemanticVerifier(FakeLLM(lambda s, u: {"ok": True})).check(SPEC, KN)
        self.assertEqual(len(issues), 3)

    def test_l4_includes_structural_checks(self):
        issues = check_l4(SPEC, KN1, SemanticVerifier(FakeLLM(heuristic_auditor)))
        self.assertIn("versao", {i.category for i in issues})

    def test_mutation_study_adds_l4(self):
        res = run_mutation_study(SPEC, KN, KN1, CASES,
                                 verifier=SemanticVerifier(FakeLLM(heuristic_auditor)))
        l4 = next(r for r in res["levels"] if r["level"] == "L4_semantica")
        self.assertNotIn("M10", l4["missed"])
        self.assertNotIn("M11", l4["missed"])
        self.assertNotIn("N06", l4["false_alarms"])
        self.assertEqual(l4["emitted_wrong"], 0)
        self.assertIn("L3_completa", [r["level"] for r in res["levels"]])


class AssistantTests(unittest.TestCase):
    def engine(self, kn=KN):
        return PolicyAgent(SPEC, kn, enforce_sdd=True)

    def test_llm_text_used_when_consistent(self):
        a = SDDAssistant(self.engine(), FakeLLM(explainer())).answer(CASE["C05"])
        self.assertEqual((a.status, a.source), ("PERMITIR", "llm"))
        self.assertIsNone(a.llm_rejected_reason)

    def test_contradiction_falls_back_to_rule(self):
        a = SDDAssistant(self.engine(), FakeLLM(explainer("NEGAR"))).answer(CASE["C05"])
        self.assertEqual((a.status, a.source), ("PERMITIR", "regra"))
        self.assertIn("contradisse", a.llm_rejected_reason)

    def test_foreign_citation_falls_back(self):
        a = SDDAssistant(self.engine(), FakeLLM(explainer(cite="DOC-SEG"))).answer(CASE["C05"])
        self.assertEqual(a.source, "regra")

    def test_llm_error_falls_back(self):
        a = SDDAssistant(self.engine(), FakeLLM(failing)).answer(CASE["C05"])
        self.assertEqual((a.status, a.source), ("PERMITIR", "regra"))

    def test_blocked_never_calls_llm(self):
        llm = FakeLLM(explainer())
        a = SDDAssistant(self.engine(KN1), llm).answer(CASE["C05"])
        self.assertEqual(a.status, BLOCKED)
        self.assertEqual(llm.calls, [])

    def test_llm_only_invalid_decision(self):
        out = LLMOnlyBaseline(KN, FakeLLM(lambda s, u: {"decisao": "TALVEZ"})).decide(CASE["C05"])
        self.assertEqual(out["status"], "ERRO")

    def test_llm_benchmark_ps_never_wrong(self):
        res = run_llm_benchmark(SPEC, {"v1": KN1, "v2": KN}, CASES, FakeLLM(
            lambda s, u: {"decisao": "NEGAR", "documento_id": "DOC-CANCEL", "justificativa": "x"}
            if "decide pedidos" in s else explainer()(s, u)))
        ps = [r for r in res["summary"] if r["condition"] == "P_sdd_llm_explica"]
        self.assertTrue(all(r["emitted_wrong"] == 0 for r in ps))
        stale = next(r for r in ps if r["scenario"] == "docs_v1_antigos")
        self.assertEqual(stale["blocked"], len(CASES))


class CacheTests(unittest.TestCase):
    def test_cache_round_trip_and_offline_miss(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "cache.json"
            fake = FakeLLM(heuristic_auditor, model=DEFAULT_MODEL)
            SemanticVerifier(CachedLLM(fake, path)).check(SPEC, KN)
            offline = CachedLLM(None, path, offline=True)
            self.assertEqual(SemanticVerifier(offline).check(SPEC, KN), [])
            self.assertEqual((offline.hits, offline.misses), (3, 0))
            with self.assertRaises(LLMError):
                offline.complete_json("s", "pedido novo", {})

    def test_cli_ask_offline_from_cache(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "cache.json"
            fake = CachedLLM(FakeLLM(explainer(), model=DEFAULT_MODEL), path)
            SDDAssistant(PolicyAgent(SPEC, KN), fake).answer(CASE["C05"])
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = main(["--root", str(ROOT), "ask", "--case", "C05",
                             "--offline", "--cache", str(path)])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(out.getvalue())["source"], "llm")

    def test_cli_offline_cache_miss_falls_back_to_rule(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main(["--root", str(ROOT), "ask", "--case", "C05", "--offline",
                         "--cache", "/nonexistent/cache.json"])
        self.assertEqual(code, 0)  # cache vazio: LLM indisponível, cai na regra
        answer = json.loads(out.getvalue())
        self.assertEqual((answer["status"], answer["source"]), ("PERMITIR", "regra"))


class ClientWiringTests(unittest.TestCase):
    """Confere os parâmetros enviados aos SDKs, com clientes simulados."""

    @unittest.skipUnless(importlib.util.find_spec("anthropic"), "SDK anthropic ausente")
    def test_anthropic_request_and_refusal(self):
        sent = {}

        def create(**kw):
            sent.update(kw)
            return SimpleNamespace(stop_reason="end_turn", content=[
                SimpleNamespace(type="text", text='{"ok": true}')])
        fake = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=create)))
        client = AnthropicClient(client=fake)
        self.assertEqual(client.complete_json("s", "u", {"type": "object"}), {"ok": True})
        self.assertEqual(sent["model"], DEFAULT_MODEL)
        self.assertEqual(sent["fallbacks"], "default")
        self.assertIn(FALLBACK_BETA, sent["betas"])
        self.assertEqual(sent["output_config"]["format"]["type"], "json_schema")
        self.assertNotIn("temperature", sent)

        fake.beta.messages.create = lambda **kw: SimpleNamespace(stop_reason="refusal", content=[])
        with self.assertRaises(LLMError):
            client.complete_json("s", "u", {})

    @unittest.skipUnless(importlib.util.find_spec("openai"), "SDK openai ausente")
    def test_openai_request_and_refusal(self):
        sent = {}

        def create(**kw):
            sent.update(kw)
            return SimpleNamespace(status="completed", output=[], output_text='{"ok": 1}')
        fake = SimpleNamespace(responses=SimpleNamespace(create=create))
        client = OpenAIClient(client=fake)
        self.assertEqual(client.complete_json("s", "u", {"type": "object"}), {"ok": 1})
        self.assertTrue(sent["text"]["format"]["strict"])
        self.assertFalse(sent["store"])

        refusal = SimpleNamespace(content=[SimpleNamespace(type="refusal", refusal="não")])
        fake.responses.create = lambda **kw: SimpleNamespace(
            status="completed", output=[refusal], output_text="")
        with self.assertRaises(LLMError):
            client.complete_json("s", "u", {})


if __name__ == "__main__":
    unittest.main()


class RetrievalTests(unittest.TestCase):
    def test_semantic_retriever_ranks_and_caches(self):
        from evopolicy.retrieval import CachedEmbedder, HashingEmbedder, SemanticRetriever, case_query
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "emb.json"
            r = SemanticRetriever(KN, CachedEmbedder(HashingEmbedder(), path), top_k=2)
            hits = r.retrieve(case_query(CASE["C03"]))
            self.assertEqual(len(hits), 2)
            self.assertGreaterEqual(hits[0]["score"], hits[1]["score"])
            offline = CachedEmbedder(None, path, offline=True, model="hashing-256")
            self.assertEqual(SemanticRetriever(KN, offline).retrieve(case_query(CASE["C03"]))[0]["id"],
                             hits[0]["id"])

    def test_rag_baseline_low_confidence_skips_llm(self):
        from evopolicy.retrieval import HashingEmbedder, SemanticRetriever
        llm = FakeLLM(lambda s, u: {"decisao": "PERMITIR", "documento_id": "x", "justificativa": "x"})
        out = LLMOnlyBaseline(KN, llm, SemanticRetriever(KN, HashingEmbedder(), threshold=1.01)
                              ).decide(CASE["C05"])
        self.assertEqual(out["status"], "REVISAO_HUMANA")
        self.assertEqual(llm.calls, [])

    def test_rag_baseline_sends_only_retrieved_docs(self):
        from evopolicy.retrieval import HashingEmbedder, SemanticRetriever
        llm = FakeLLM(lambda s, u: {"decisao": "PERMITIR", "documento_id": "x", "justificativa": "x"})
        LLMOnlyBaseline(KN, llm, SemanticRetriever(KN, HashingEmbedder(), top_k=1, threshold=0)
                        ).decide(CASE["C05"])
        self.assertEqual(len(_payload(llm.calls[0][1])["documentos"]), 1)

    def test_benchmark_with_rag_condition(self):
        from evopolicy.retrieval import HashingEmbedder, SemanticRetriever
        res = run_llm_benchmark(SPEC, {"v1": KN1, "v2": KN}, CASES, FakeLLM(
            lambda s, u: {"decisao": "NEGAR", "documento_id": "DOC-CANCEL", "justificativa": "x"}
            if "decide pedidos" in s else explainer()(s, u)),
            retriever_factory=lambda kn: SemanticRetriever(kn, HashingEmbedder(), threshold=0))
        self.assertIn("B1R_rag_llm_decide", {r["condition"] for r in res["summary"]})
