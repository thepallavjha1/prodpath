"""Compare local Ollama models on the fixture repos (Phase 3 benchmark; dev tool, not shipped).

Usage: uv run python scripts/benchmark_models.py phi3:latest llama3.1:latest [--num-ctx 4096]

Reports per model: schema-valid rate (first try and after the repair retry), evidence
citation rate (claims kept / claims made), and seconds per call. Nothing is cached, so every
run measures the model. Talks to localhost Ollama only.
"""

import argparse
import tempfile
from pathlib import Path

from prodpath.cache import HashCache
from prodpath.detect import detect_services
from prodpath.extract import extract_system
from prodpath.llm import DEFAULT_MAX_INPUT_TOKENS, LLMError, OllamaLLM
from prodpath.models import Service, SystemModel
from prodpath.scan import scan_repo
from prodpath.summarize import summarize_service

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
FIXTURE_NAMES = ["mono_a", "mono_b", "mono_c"]


def load_systems(workdir: Path) -> list[tuple[str, SystemModel]]:
    systems = []
    for name in FIXTURE_NAMES:
        repo = FIXTURES / name
        cache = HashCache(workdir / f"{name}.sqlite")
        inventory, _ = scan_repo(repo, cache)
        system, _ = extract_system(repo, inventory, detect_services(repo, inventory), cache)
        cache.close()
        systems.append((name, system))
    return systems


def benchmark(model: str, num_ctx: int, services: list[Service]) -> dict[str, float]:
    llm = OllamaLLM(model=model, num_ctx=num_ctx, cache=None)
    kept = dropped = errors = 0
    for service in services:
        try:
            summary = summarize_service(llm, service, DEFAULT_MAX_INPUT_TOKENS)
        except LLMError as error:
            errors += 1
            print(f"  {model} {service.id}: {error}")
            continue
        if summary.generated_by == "llm":
            kept += len(summary.risks) + (1 if summary.hot_path else 0)
            dropped += summary.dropped_claims
    stats = llm.stats
    calls = max(stats.calls, 1)
    return {
        "calls": stats.calls,
        "valid_first_try": stats.valid_first_try / calls,
        "valid_final": (stats.valid_first_try + stats.valid_after_repair) / calls,
        "citation_rate": kept / (kept + dropped) if kept + dropped else 1.0,
        "seconds_per_call": stats.seconds / calls,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("models", nargs="+", help="Ollama model tags to compare")
    parser.add_argument("--num-ctx", type=int, default=4096)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as workdir:
        systems = load_systems(Path(workdir))
    services = [s for _, system in systems for s in system.services if s.facts]
    print(f"{len(services)} services with facts across {len(systems)} fixtures\n")
    print("| model | calls | valid first try | valid after repair | citation rate | s/call |")
    print("|---|---|---|---|---|---|")
    for model in args.models:
        r = benchmark(model, args.num_ctx, services)
        print(
            f"| {model} | {r['calls']:.0f} | {r['valid_first_try']:.0%} | {r['valid_final']:.0%} "
            f"| {r['citation_rate']:.0%} | {r['seconds_per_call']:.1f} |"
        )


if __name__ == "__main__":
    main()
