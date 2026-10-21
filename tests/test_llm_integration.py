"""Slow tests against a real local Ollama. Run with: uv run pytest -m llm

Asserts structure and evidence, never exact prose (TESTING.md section 6). Model comes from
PRODPATH_TEST_MODEL (default phi3:latest); the tests skip when Ollama or the model is missing.
"""

import os
import time
from pathlib import Path

import httpx
import pytest

from prodpath.cache import HashCache
from prodpath.detect import detect_services
from prodpath.extract import extract_system
from prodpath.llm import OLLAMA_URL, OllamaLLM
from prodpath.scan import scan_repo
from prodpath.summarize import summarize_system

MODEL = os.environ.get("PRODPATH_TEST_MODEL", "phi3:latest")

pytestmark = pytest.mark.llm


@pytest.fixture(scope="module")
def require_model() -> None:
    try:
        tags = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=3).json()
    except httpx.HTTPError:
        pytest.skip("Ollama is not running on localhost:11434")
    if MODEL not in {m["name"] for m in tags.get("models", [])}:
        pytest.skip(f"model {MODEL} is not installed")


def test_real_model_returns_valid_cited_summaries(
    require_model: None, fixtures_dir: Path, tmp_path: Path
) -> None:
    repo = fixtures_dir / "mono_b"
    cache = HashCache(tmp_path / "c.sqlite")
    inventory, _ = scan_repo(repo, cache)
    system, _ = extract_system(repo, inventory, detect_services(repo, inventory), cache)
    llm = OllamaLLM(model=MODEL, cache=None)
    started = time.monotonic()
    summaries = summarize_system(llm, system, MODEL)
    cache.close()
    print(f"\n{MODEL}: {llm.stats.calls} calls, {time.monotonic() - started:.1f}s total")

    assert llm.stats.failed == 0
    assert {s.service_id for s in summaries.services} == {s.id for s in system.services}
    known_paths = {e.path for s in system.services for f in s.facts for e in f.evidence}
    for item in summaries.services:
        for claim in item.risks:
            assert claim.evidence_ids
            assert all(ref.rsplit(":", 1)[0] in known_paths for ref in claim.evidence_ids)
    listed = {s.id for s in system.services}
    assert all(set(r.service_ids) <= listed for r in summaries.system.key_risks)
