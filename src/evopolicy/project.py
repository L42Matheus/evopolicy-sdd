"""Localização dos artefatos de pesquisa (specs, knowledge, datasets).

Os artefatos não fazem parte do pacote instalado: são dados versionados do
repositório. A raiz é resolvida, nesta ordem, por argumento explícito,
variável ``EVOPOLICY_ROOT``, diretório atual (ou ancestral) e, por fim, o
checkout de origem do pacote. Assim ``pip install .`` e ``pip install -e .``
funcionam igualmente quando o comando roda dentro do repositório.
"""
from __future__ import annotations

import os
from pathlib import Path

from .core import PolicyAgent, load_json, load_yaml, FULL

ENV_VAR = "EVOPOLICY_ROOT"


def _is_root(p: Path) -> bool:
    return (p / "specs").is_dir() and (p / "knowledge").is_dir()


def find_root(explicit: str | Path | None = None) -> Path:
    if explicit:
        p = Path(explicit).resolve()
        if not _is_root(p):
            raise FileNotFoundError(f"{p} não contém specs/ e knowledge/")
        return p
    env = os.environ.get(ENV_VAR)
    if env:
        return find_root(env)
    for start in (Path.cwd().resolve(), Path(__file__).resolve().parent):
        for p in (start, *start.parents):
            if _is_root(p):
                return p
    raise FileNotFoundError(
        "Artefatos não encontrados: execute dentro do repositório EvoPolicy-SDD, "
        f"use --root ou defina {ENV_VAR}.")


def available_versions(root: Path) -> list[str]:
    specs = {p.parent.name for p in (root / "specs").glob("*/specification.yaml")}
    docs = {p.parent.name for p in (root / "knowledge").glob("*/policies.json")}
    return sorted(specs | docs, key=lambda v: (len(v), v))


def spec_path(root: Path, version: str) -> Path:
    return root / "specs" / version / "specification.yaml"


def knowledge_path(root: Path, version: str) -> Path:
    return root / "knowledge" / version / "policies.json"


def load_spec(root: Path, version: str) -> dict:
    return load_yaml(spec_path(root, version))


def load_knowledge(root: Path, version: str) -> dict:
    return load_json(knowledge_path(root, version))


def load_cases(root: Path) -> list[dict]:
    return load_json(root / "datasets" / "cases.json")["cases"]


def load_agent(root: Path, spec_version: str, doc_version: str | None = None,
               sdd: bool = True, categories=FULL) -> PolicyAgent:
    return PolicyAgent(load_spec(root, spec_version),
                       load_knowledge(root, doc_version or spec_version),
                       enforce_sdd=sdd, categories=categories)
