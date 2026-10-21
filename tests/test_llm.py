import json
from pathlib import Path

import httpx
import pytest
from pydantic import BaseModel

from prodpath.cache import HashCache
from prodpath.llm import OLLAMA_URL, FakeLLM, LLMError, OllamaLLM, estimate_tokens


class Answer(BaseModel):
    text: str
    score: int


GOOD = json.dumps({"text": "ok", "score": 3})


def test_valid_output_is_returned_and_validated() -> None:
    llm = FakeLLM(lambda s, u, schema: GOOD)
    assert llm.complete("sys", "user", Answer) == Answer(text="ok", score=3)
    assert llm.calls == 1


def test_invalid_output_triggers_exactly_one_repair_retry() -> None:
    seen_users: list[str] = []

    def handler(system: str, user: str, schema: type[BaseModel]) -> str:
        seen_users.append(user)
        return "not json" if len(seen_users) == 1 else GOOD

    llm = FakeLLM(handler)
    assert llm.complete("sys", "user", Answer).score == 3
    assert llm.calls == 2
    assert "That output was invalid" in seen_users[1]  # the model is told what was wrong


def test_second_failure_raises_with_prompt_hash() -> None:
    llm = FakeLLM(lambda s, u, schema: '{"text": "x"}')  # missing score, both times
    with pytest.raises(LLMError, match=r"invalid output twice \(prompt [0-9a-f]{12}\)"):
        llm.complete("sys", "user", Answer)
    assert llm.calls == 2


def test_cache_means_the_model_is_not_asked_twice(tmp_path: Path) -> None:
    cache = HashCache(tmp_path / "c.sqlite")
    llm = FakeLLM(lambda s, u, schema: GOOD, cache=cache)
    first = llm.complete("sys", "user", Answer)
    second = llm.complete("sys", "user", Answer)
    other = llm.complete("sys", "different user", Answer)
    cache.close()
    assert first == second == other
    assert llm.calls == 2  # the repeated prompt hit the cache; the different one did not


def test_ollama_request_is_schema_constrained_deterministic_and_local() -> None:
    captured: dict[str, object] = {}

    def respond(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        captured["url"] = str(request.url)
        return httpx.Response(200, json={"message": {"content": GOOD}})

    client = httpx.Client(transport=httpx.MockTransport(respond), base_url=OLLAMA_URL)
    llm = OllamaLLM(model="m:1", num_ctx=2048, client=client)
    assert llm.complete("sys", "user", Answer).text == "ok"
    assert captured["url"] == f"{OLLAMA_URL}/api/chat"
    assert captured["stream"] is False
    assert captured["format"] == Answer.model_json_schema()
    assert captured["options"] == {"temperature": 0, "num_ctx": 2048}
    assert OLLAMA_URL.startswith("http://localhost")


def test_ollama_unreachable_gives_an_actionable_message() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    client = httpx.Client(transport=httpx.MockTransport(refuse), base_url=OLLAMA_URL)
    with pytest.raises(LLMError, match="ollama serve"):
        OllamaLLM(client=client).complete("s", "u", Answer)


def test_ollama_missing_model_suggests_pull() -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(404, text="model not found")),
        base_url=OLLAMA_URL,
    )
    with pytest.raises(LLMError, match="ollama pull nope:1"):
        OllamaLLM(model="nope:1", client=client).complete("s", "u", Answer)


def test_estimate_tokens_is_monotonic() -> None:
    assert estimate_tokens("a" * 400) > estimate_tokens("a" * 40)


def test_stats_count_first_try_repaired_and_failed_calls() -> None:
    answers = iter(["bad", GOOD, GOOD, "bad", "bad"])
    llm = FakeLLM(lambda s, u, schema: next(answers))
    llm.complete("s", "repaired", Answer)  # bad, then good
    llm.complete("s", "first try", Answer)  # good
    with pytest.raises(LLMError):
        llm.complete("s", "fails", Answer)  # bad, bad
    assert (llm.stats.calls, llm.stats.valid_first_try) == (3, 1)
    assert (llm.stats.valid_after_repair, llm.stats.failed) == (1, 1)
    assert llm.stats.seconds >= 0
