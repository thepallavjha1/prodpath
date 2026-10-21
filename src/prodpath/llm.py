"""The only module that talks to Ollama. Everything else uses the `LLM` protocol (ADR-004).

Both OllamaLLM and FakeLLM share one validate-and-repair path, so the failure behaviour
tested with the fake is the behaviour the real model gets.
"""

import hashlib
import json
import logging
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Protocol, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from prodpath.cache import HashCache

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

OLLAMA_URL = "http://localhost:11434"  # never anything else; see SECURITY.md section 2
DEFAULT_MODEL = "phi3:latest"
DEFAULT_NUM_CTX = 4096  # sized for a 4 GB laptop GPU
DEFAULT_MAX_INPUT_TOKENS = 2800  # leaves room for the schema, instructions and the answer
TIMEOUT_SECONDS = 900.0  # CPU spill on a laptop is slow; fail loudly rather than hang forever

Messages = list[dict[str, str]]


class LLMError(Exception):
    """The model failed to return schema-valid output, or Ollama could not be used."""


class LLM(Protocol):
    def complete(self, system: str, user: str, schema: type[T]) -> T: ...


def estimate_tokens(text: str) -> int:
    return len(text) // 4 + 1  # rough on purpose; budgets keep a margin


def prompt_hash(model: str, num_ctx: int, system: str, user: str, schema: type[BaseModel]) -> str:
    material = json.dumps(
        [model, num_ctx, system, user, schema.model_json_schema()], sort_keys=True
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


class ChatLLM(ABC):
    """Shared complete(): cache lookup, one call, validation, one repair retry, then raise."""

    model: str
    num_ctx: int
    cache: HashCache | None

    @abstractmethod
    def chat(self, messages: Messages, schema: type[BaseModel]) -> str:
        """Send messages, return the raw model text (expected to be JSON)."""

    def complete(self, system: str, user: str, schema: type[T]) -> T:
        key = prompt_hash(self.model, self.num_ctx, system, user, schema)
        if self.cache is not None and (hit := self.cache.get_llm(key)) is not None:
            return schema.model_validate_json(hit)
        messages: Messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        raw = self.chat(messages, schema)
        try:
            result = schema.model_validate_json(raw)
        except (ValidationError, ValueError) as first_error:
            log.warning("invalid model output (prompt %s), retrying once", key[:12])
            messages += [
                {"role": "assistant", "content": raw},
                {
                    "role": "user",
                    "content": "That output was invalid: "
                    f"{str(first_error)[:400]}\nReturn only corrected JSON matching the schema.",
                },
            ]
            raw = self.chat(messages, schema)
            try:
                result = schema.model_validate_json(raw)
            except (ValidationError, ValueError) as error:
                raise LLMError(
                    f"model {self.model} returned invalid output twice (prompt {key[:12]}): "
                    f"{str(error)[:300]}"
                ) from error
        if self.cache is not None:
            self.cache.put_llm(key, result.model_dump_json())
        return result


class OllamaLLM(ChatLLM):
    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        num_ctx: int = DEFAULT_NUM_CTX,
        cache: HashCache | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.model = model
        self.num_ctx = num_ctx
        self.cache = cache
        self._client = client or httpx.Client(base_url=OLLAMA_URL, timeout=TIMEOUT_SECONDS)

    def chat(self, messages: Messages, schema: type[BaseModel]) -> str:
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "format": schema.model_json_schema(),  # schema-constrained decoding
            "options": {"temperature": 0, "num_ctx": self.num_ctx},
        }
        try:
            response = self._client.post("/api/chat", json=payload)
            response.raise_for_status()
        except httpx.ConnectError as error:
            raise LLMError(
                f"cannot reach Ollama at {OLLAMA_URL}. Start it (`ollama serve`) and retry."
            ) from error
        except httpx.HTTPStatusError as error:
            raise LLMError(
                f"Ollama returned {error.response.status_code}: {error.response.text[:200]}. "
                f"Is the model pulled? Try `ollama pull {self.model}`."
            ) from error
        except httpx.TimeoutException as error:
            raise LLMError(
                f"Ollama did not answer within {TIMEOUT_SECONDS:.0f}s "
                f"(model {self.model}); try a smaller model."
            ) from error
        return str(response.json()["message"]["content"])


class FakeLLM(ChatLLM):
    """Deterministic stand-in for tests. `handler` maps (system, user, schema) to raw JSON text."""

    def __init__(
        self,
        handler: Callable[[str, str, type[BaseModel]], str],
        model: str = "fake",
        cache: HashCache | None = None,
    ) -> None:
        self.model = model
        self.num_ctx = DEFAULT_NUM_CTX
        self.cache = cache
        self._handler = handler
        self.calls = 0

    def chat(self, messages: Messages, schema: type[BaseModel]) -> str:
        self.calls += 1
        system = messages[0]["content"]
        user = messages[1]["content"]
        # On a repair retry the handler sees the corrective message appended to the prompt.
        if len(messages) > 2:
            user += "\n" + messages[-1]["content"]
        return self._handler(system, user, schema)
