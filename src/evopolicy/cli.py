"""Comandos: validate, decide, benchmark, diff, trace, fingerprint, mutate."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

from .core import LEVELS, check
from .evolution import (append_jsonl, decision_record, diff_specs, impact,
                        synchronize, trace_matrix)
from .experiment import check_cases, run_benchmark
from .mutations import run_mutation_study
from .project import (available_versions, find_root, knowledge_path, load_agent,
                      load_cases, load_knowledge, load_spec, spec_path)


def _print(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="evopolicy", description=__doc__)
    parser.add_argument("--root", help="Raiz do repositório (padrão: detecção automática)")
    commands = parser.add_subparsers(dest="command", required=True)

    v = commands.add_parser("validate", help="Verifica versões, IDs, regras, fingerprints e digests")
    v.add_argument("--spec-version", default="v2")
    v.add_argument("--doc-version", default=None, help="Padrão: igual à spec")
    v.add_argument("--level", choices=list(LEVELS), default="L3_completa")

    d = commands.add_parser("decide", help="Executa um caso do dataset")
    d.add_argument("--case", required=True, help="ID do caso, ex. C05")
    d.add_argument("--spec-version", default="v2")
    d.add_argument("--doc-version", default=None)
    d.add_argument("--no-guard", action="store_true", help="Baseline sem bloqueio SDD")
    d.add_argument("--log", help="Acrescenta o registro da decisão a um arquivo JSONL")

    b = commands.add_parser("benchmark", help="Benchmark offline das cinco condições")
    b.add_argument("--output", default=None, help="Padrão: <root>/results")

    df = commands.add_parser("diff", help="Diferença entre versões e casos impactados")
    df.add_argument("old")
    df.add_argument("new")

    t = commands.add_parser("trace", help="Matriz de rastreabilidade REQ -> regra -> documento")
    t.add_argument("--spec-version", default="v2")
    t.add_argument("--doc-version", default=None)
    t.add_argument("--format", choices=["json", "md"], default="md")

    f = commands.add_parser("fingerprint",
                            help="Mostra (ou grava, após revisão humana) fingerprints e digests")
    f.add_argument("--version", default="v2")
    f.add_argument("--write", action="store_true",
                   help="Grava nos arquivos. Use só depois de revisar o texto dos documentos!")

    m = commands.add_parser("mutate", help="Experimento de mutações (sensibilidade/alarmes falsos)")
    m.add_argument("--output", default=None, help="Padrão: <root>/results")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        root = find_root(args.root)
    except FileNotFoundError as exc:
        parser.error(str(exc))
    versions = available_versions(root)
    for attr in ("spec_version", "doc_version", "version", "old", "new"):
        val = getattr(args, attr, None)
        if val is not None and val not in versions:
            parser.error(f"Versão '{val}' inexistente; disponíveis: {', '.join(versions)}")

    if args.command == "validate":
        spec = load_spec(root, args.spec_version)
        kn = load_knowledge(root, args.doc_version or args.spec_version)
        issues = check(spec, kn, LEVELS[args.level])
        case_problems = check_cases(spec, load_cases(root))
        _print({"valid": not issues, "level": args.level, "errors": [str(i) for i in issues],
                "dataset_warnings": case_problems})
        return 2 if issues else 0

    if args.command == "decide":
        cases = {c["id"]: c for c in load_cases(root)}
        if args.case not in cases:
            parser.error(f"Caso não encontrado: {args.case}")
        agent = load_agent(root, args.spec_version, args.doc_version, not args.no_guard)
        decision = agent.decide(cases[args.case])
        _print(decision.to_dict())
        if args.log:
            append_jsonl(Path(args.log), [decision_record(decision, cases[args.case])])
        return 0

    if args.command == "benchmark":
        _print(run_benchmark(root, Path(args.output) if args.output else None))
        return 0

    if args.command == "diff":
        old_spec, new_spec = load_spec(root, args.old), load_spec(root, args.new)
        result = diff_specs(old_spec, new_spec)
        result["casos_impactados"] = impact(load_cases(root),
                                            load_agent(root, args.old, sdd=False),
                                            load_agent(root, args.new, sdd=False))
        _print(result)
        return 0

    if args.command == "trace":
        rows = trace_matrix(load_spec(root, args.spec_version),
                            load_knowledge(root, args.doc_version or args.spec_version))
        if args.format == "json":
            _print(rows)
        else:
            print("| Requisito | Regra | Documento | Estado |\n|---|---|---|---|")
            for r in rows:
                print(f"| {r['requirement_id']} | {r['rule_id'] or '-'} | "
                      f"{r['document_id'] or '-'} | {r['status']} |")
        return 0 if all(r["status"] == "OK" for r in rows) else 2

    if args.command == "fingerprint":
        spec, kn = synchronize(load_spec(root, args.version), load_knowledge(root, args.version))
        if args.write:
            with open(spec_path(root, args.version), "w", encoding="utf-8") as fh:
                yaml.safe_dump(spec, fh, sort_keys=False, allow_unicode=True, width=110)
            with open(knowledge_path(root, args.version), "w", encoding="utf-8") as fh:
                json.dump(kn, fh, ensure_ascii=False, indent=2)
                fh.write("\n")
            print(f"Marcas gravadas para {args.version}.", file=sys.stderr)
        _print({"document_digests": spec["document_digests"],
                "rule_fingerprints": {d["id"]: d["rule_fingerprints"] for d in kn["documents"]}})
        return 0

    if args.command == "mutate":
        out = Path(args.output) if args.output else root / "results"
        res = run_mutation_study(load_spec(root, "v2"), load_knowledge(root, "v2"),
                                 load_knowledge(root, "v1"), load_cases(root), out)
        _print(res["levels"])
        return 0
    return 1


def entrypoint() -> None:
    raise SystemExit(main())


if __name__ == "__main__":
    entrypoint()
