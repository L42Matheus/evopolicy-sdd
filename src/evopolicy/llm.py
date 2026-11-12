"""Clientes de LLM usados pela verificação semântica (L4) e pelo agente.

Toda chamada pede saída JSON com esquema fixo e devolve um ``dict``. Quem
chama trata qualquer falha (recusa, JSON inválido, erro de rede) como
``LLMError`` e decide de forma fail-closed.

Implementações:

* ``AnthropicClient``: chamada real ao Claude pelo SDK oficial ``anthropic``
  (dependência opcional: ``pip install -e ".[llm]"``). Lê a chave de
  ``ANTHROPIC_API_KEY``; nunca a recebe por argumento de linha de comando.
* ``OpenAIClient``: chamada real ao GPT pelo SDK oficial ``openai`` (mesma
  dependência opcional). Lê a chave de ``OPENAI_API_KEY``.
* ``CachedLLM``: grava cada resposta em um arquivo JSON indexado pelo hash do
  pedido. Reexecutar um experimento com o mesmo cache reproduz as respostas
  sem nova chamada (e sem custo).
* ``FakeLLM``: respostas programadas, para testes offline.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Callable, Protocol

DEFAULT_MODEL = "claude-opus-5-5"
DEFAULT_EFFORT = "medium"
FALLBACK_BETA = "server-side-fallback-2026-07-01"
DEFAULT_OPENAI_MODEL = "gpt-5.5"
PROVIDERS = ("anthropic", "openai")
MODEL_ENV = "EVOPOLICY_MODEL"
EFFORT_ENV = "EVOPOLICY_EFFORT"


class LLMError(RuntimeError):
    """Falha que impede usar a resposta do modelo (tratada como fail-closed)."""


class LLMClient(Protocol):
    model: str

    def complete_json(self, system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]:
        ...


def request_key(model: str, system: str, user: str, schema: dict[str, Any]) -> str:
    raw = json.dumps({"model": model, "system": system, "user": user, "schema": schema},
                     ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class AnthropicClient:
    """Claude via SDK oficial, com saída estruturada e fallback no servidor."""

    def __init__(self, model: str | None = None, effort: str | None = None,
                 max_tokens: int = 16000, client: Any = None):
        self.model = model or os.environ.get(MODEL_ENV, DEFAULT_MODEL)
        self.effort = effort or os.environ.get(EFFORT_ENV, DEFAULT_EFFORT)
        self.max_tokens = max_tokens
        if client is None:
            try:
                import anthropic
            except ImportError as exc:  # pragma: no cover - depende do ambiente
                raise LLMError('SDK ausente: instale com  pip install -e ".[llm]"') from exc
            if not os.environ.get("ANTHROPIC_API_KEY"):
                raise LLMError("ANTHROPIC_API_KEY não definida no ambiente")
            client = anthropic.Anthropic()
        self._client = client

    def complete_json(self, system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]:
        import anthropic

        try:
            response = self._client.beta.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
                output_config={"effort": self.effort,
                               "format": {"type": "json_schema", "schema": schema}},
                betas=[FALLBACK_BETA],
                fallbacks="default",
            )
        except anthropic.AuthenticationError as exc:
            raise LLMError("Chave de API inválida ou revogada") from exc
        except anthropic.RateLimitError as exc:
            raise LLMError("Limite de requisições atingido; tente mais tarde") from exc
        except anthropic.BadRequestError as exc:
            raise LLMError(f"Requisição rejeitada pela API: {exc.message}") from exc
        except anthropic.APIConnectionError as exc:
            raise LLMError("Falha de conexão com a API") from exc
        except anthropic.APIStatusError as exc:
            raise LLMError(f"Erro da API ({exc.status_code})") from exc

        if response.stop_reason == "refusal":
            raise LLMError("O modelo recusou o pedido")
        if response.stop_reason == "max_tokens":
            raise LLMError("Resposta truncada (max_tokens)")
        return _parse_object("".join(b.text for b in response.content if b.type == "text"))


class OpenAIClient:
    """GPT via SDK oficial (Responses API), com saída estruturada estrita."""

    def __init__(self, model: str | None = None, effort: str | None = None,
                 max_tokens: int = 16000, client: Any = None):
        self.model = model or os.environ.get(MODEL_ENV, DEFAULT_OPENAI_MODEL)
        self.effort = effort or os.environ.get(EFFORT_ENV, DEFAULT_EFFORT)
        self.max_tokens = max_tokens
        if client is None:
            try:
                import openai
            except ImportError as exc:  # pragma: no cover - depende do ambiente
                raise LLMError('SDK ausente: instale com  pip install -e ".[llm]"') from exc
            if not os.environ.get("OPENAI_API_KEY"):
                raise LLMError("OPENAI_API_KEY não definida no ambiente")
            client = openai.OpenAI()
        self._client = client

    def complete_json(self, system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]:
        import openai

        try:
            response = self._client.responses.create(
                model=self.model,
                instructions=system,
                input=user,
                max_output_tokens=self.max_tokens,
                reasoning={"effort": self.effort},
                text={"format": {"type": "json_schema", "name": "evopolicy",
                                 "schema": schema, "strict": True}},
                store=False,
            )
        except openai.AuthenticationError as exc:
            raise LLMError("Chave de API inválida ou revogada") from exc
        except openai.RateLimitError as exc:
            raise LLMError("Limite de requisições atingido; tente mais tarde") from exc
        except openai.BadRequestError as exc:
            raise LLMError(f"Requisição rejeitada pela API: {exc.message}") from exc
        except openai.APIConnectionError as exc:
            raise LLMError("Falha de conexão com a API") from exc
        except openai.APIStatusError as exc:
            raise LLMError(f"Erro da API ({exc.status_code})") from exc

        for item in response.output or []:
            for part in getattr(item, "content", None) or []:
                if getattr(part, "type", None) == "refusal":
                    raise LLMError("O modelo recusou o pedido")
        if response.status == "incomplete":
            raise LLMError("Resposta incompleta (limite de tokens)")
        return _parse_object(response.output_text)


def _parse_object(text: str) -> dict[str, Any]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMError("Resposta do modelo não é JSON válido") from exc
    if not isinstance(data, dict):
        raise LLMError("Resposta do modelo não é um objeto JSON")
    return data


class CachedLLM:
    """Cache em arquivo: reprodutibilidade e custo zero em reexecuções.

    Com ``offline=True`` só lê do cache; um pedido ausente vira ``LLMError``.
    """

    def __init__(self, inner: LLMClient | None, path: str | Path, offline: bool = False):
        if inner is None and not offline:
            raise ValueError("Sem cliente interno, o cache precisa ser offline")
        self.inner = inner
        self.model = inner.model if inner else os.environ.get(MODEL_ENV, DEFAULT_MODEL)
        self.path = Path(path)
        self.offline = offline
        self.hits = self.misses = 0
        self._data: dict[str, Any] = {}
        if self.path.exists():
            self._data = json.loads(self.path.read_text(encoding="utf-8"))

    def complete_json(self, system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]:
        key = request_key(self.model, system, user, schema)
        if key in self._data:
            self.hits += 1
            return self._data[key]["response"]
        self.misses += 1
        if self.offline or self.inner is None:
            raise LLMError("Resposta ausente no cache (modo offline)")
        result = self.inner.complete_json(system, user, schema)
        self._data[key] = {"model": self.model, "response": result}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._data, ensure_ascii=False, indent=2, sort_keys=True)
                             + "\n", encoding="utf-8")
        return result


class FakeLLM:
    """LLM programável para testes: ``responder(system, user) -> dict``."""

    def __init__(self, responder: Callable[[str, str], dict[str, Any]], model: str = "fake"):
        self.responder = responder
        self.model = model
        self.calls: list[tuple[str, str]] = []

    def complete_json(self, system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((system, user))
        return self.responder(system, user)


def make_client(provider: str = "anthropic", cache: str | Path | None = None,
                offline: bool = False, model: str | None = None,
                effort: str | None = None) -> LLMClient:
    """Cliente da CLI (Claude ou GPT), opcionalmente atrás de um cache."""
    if provider not in PROVIDERS:
        raise LLMError(f"Provedor desconhecido: {provider}")
    if offline:
        if cache is None:
            raise LLMError("Modo offline exige --cache")
        default = DEFAULT_MODEL if provider == "anthropic" else DEFAULT_OPENAI_MODEL
        cached = CachedLLM(None, cache, offline=True)
        cached.model = model or os.environ.get(MODEL_ENV, default)
        return cached
    cls = AnthropicClient if provider == "anthropic" else OpenAIClient
    inner = cls(model=model, effort=effort)
    return CachedLLM(inner, cache) if cache else inner
