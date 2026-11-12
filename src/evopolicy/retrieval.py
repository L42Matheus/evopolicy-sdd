"""Recuperação semântica (RAG) por embeddings, com limiar de confiança.

Usada pela condição B1-RAG: o agente recupera os documentos mais próximos da
pergunta e, se nenhum passar do limiar, encaminha o caso para revisão humana
sem chamar o LLM. A recuperação lexical de ``core.retrieve`` continua sendo a
referência determinística dos testes.

* ``OpenAIEmbedder``: embeddings da OpenAI (``OPENAI_API_KEY`` no ambiente).
* ``CachedEmbedder``: cache em arquivo por hash de (modelo, texto).
* ``HashingEmbedder``: vetor de palavras com hashing, sem rede (testes).
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any, Protocol

from .core import tokens
from .llm import LLMError

DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_ENV = "EVOPOLICY_EMBEDDING_MODEL"
DEFAULT_THRESHOLD = 0.30
DEFAULT_TOP_K = 2


class Embedder(Protocol):
    model: str

    def embed(self, texts: list[str]) -> list[list[float]]:
        ...


class OpenAIEmbedder:
    def __init__(self, model: str | None = None, client: Any = None):
        self.model = model or os.environ.get(EMBEDDING_ENV, DEFAULT_EMBEDDING_MODEL)
        if client is None:
            try:
                import openai
            except ImportError as exc:  # pragma: no cover - depende do ambiente
                raise LLMError('SDK ausente: instale com  pip install -e ".[llm]"') from exc
            if not os.environ.get("OPENAI_API_KEY"):
                raise LLMError("OPENAI_API_KEY não definida no ambiente (embeddings)")
            client = openai.OpenAI()
        self._client = client

    def embed(self, texts: list[str]) -> list[list[float]]:
        import openai

        try:
            response = self._client.embeddings.create(model=self.model, input=texts)
        except openai.AuthenticationError as exc:
            raise LLMError("Chave de API inválida ou revogada") from exc
        except openai.APIConnectionError as exc:
            raise LLMError("Falha de conexão com a API de embeddings") from exc
        except openai.APIStatusError as exc:
            raise LLMError(f"Erro da API de embeddings ({exc.status_code})") from exc
        return [d.embedding for d in sorted(response.data, key=lambda d: d.index)]


def _key(model: str, text: str) -> str:
    return hashlib.sha256(f"{model}\n{text}".encode("utf-8")).hexdigest()


class CachedEmbedder:
    def __init__(self, inner: Embedder | None, path: str | Path, offline: bool = False,
                 model: str | None = None):
        if inner is None and not offline:
            raise ValueError("Sem embedder interno, o cache precisa ser offline")
        self.inner = inner
        self.model = inner.model if inner else (model or DEFAULT_EMBEDDING_MODEL)
        self.path = Path(path)
        self.offline = offline
        self._data: dict[str, list[float]] = {}
        if self.path.exists():
            self._data = json.loads(self.path.read_text(encoding="utf-8"))

    def embed(self, texts: list[str]) -> list[list[float]]:
        keys = [_key(self.model, t) for t in texts]
        missing = [(k, t) for k, t in zip(keys, texts) if k not in self._data]
        if missing:
            if self.offline or self.inner is None:
                raise LLMError("Embedding ausente no cache (modo offline)")
            vectors = self.inner.embed([t for _, t in missing])
            for (k, _), v in zip(missing, vectors):
                self._data[k] = [round(x, 6) for x in v]
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self._data, sort_keys=True) + "\n", encoding="utf-8")
        return [self._data[k] for k in keys]


class HashingEmbedder:
    """Embedding determinístico de palavras (sem rede), para testes."""

    def __init__(self, dim: int = 256):
        self.model = f"hashing-{dim}"
        self.dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for t in texts:
            v = [0.0] * self.dim
            for w in tokens(t):
                v[int(hashlib.md5(w.encode()).hexdigest(), 16) % self.dim] += 1.0
            out.append(v)
        return out


def cosine(a: list[float], b: list[float]) -> float:
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if not na or not nb:
        return 0.0
    return sum(x * y for x, y in zip(a, b)) / (na * nb)


def case_query(case: dict[str, Any]) -> str:
    """Consulta = pergunta do atendente + fatos do caso em texto."""
    facts = "; ".join(f"{k}={v}" for k, v in sorted((case.get("facts") or {}).items()))
    return f"{case.get('question', '')}\nFatos: {facts}"


class SemanticRetriever:
    def __init__(self, knowledge: dict[str, Any], embedder: Embedder,
                 top_k: int = DEFAULT_TOP_K, threshold: float = DEFAULT_THRESHOLD):
        self.embedder = embedder
        self.top_k = top_k
        self.threshold = threshold
        self.docs = list(knowledge.get("documents", []))
        texts = [f"{d.get('title', '')}\n{d.get('content', '')}" for d in self.docs]
        self._vectors = embedder.embed(texts) if texts else []

    def retrieve(self, query: str) -> list[dict[str, Any]]:
        """Top-k documentos com score de similaridade (cosseno)."""
        if not self.docs:
            return []
        q = self.embedder.embed([query])[0]
        ranked = [{"id": d.get("id"), "score": round(cosine(q, v), 4), "doc": d}
                  for d, v in zip(self.docs, self._vectors)]
        ranked.sort(key=lambda r: (-r["score"], str(r["id"])))
        return ranked[: self.top_k]

    def confident(self, hits: list[dict[str, Any]]) -> bool:
        return bool(hits) and hits[0]["score"] >= self.threshold
