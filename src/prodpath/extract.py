"""Stage 3: facts per service. Deterministic, no LLM.

Source-file facts are cached by (path, hash, EXTRACTOR_VERSION); small config files are
parsed every run.
"""

import logging
import posixpath
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from pydantic import TypeAdapter

from prodpath.cache import HashCache
from prodpath.edges import http_edges, infra_edges
from prodpath.facts import ExtractionError, compose, docker, javascript, manifests
from prodpath.facts import python as python_facts
from prodpath.models import Fact, Inventory, Service, ServiceCandidate, SystemModel

log = logging.getLogger(__name__)

EXTRACTOR_VERSION = "1"  # bump when any extractor changes, so cached facts are recomputed
MAX_READ_BYTES = 1024 * 1024
MAX_EVIDENCE_PER_FACT = 5
TEST_DIRS = {"tests", "test", "__tests__", "spec"}
FACTS = TypeAdapter(list[Fact])

SOURCE_EXTRACTORS: dict[str, Callable[[str, str], list[Fact]]] = {
    "python": python_facts.extract,
    "javascript": javascript.extract,
    "typescript": javascript.extract,
}
CONFIG_EXTRACTORS: dict[str, Callable[[str, str], list[Fact]]] = {
    "package.json": manifests.extract_package_json,
    "pyproject.toml": manifests.extract_pyproject,
}


@dataclass
class ExtractStats:
    extracted: int = 0  # source files run through an extractor this time
    cached: int = 0  # source files served from the facts cache


def _owner(path: str, roots: list[str]) -> str | None:
    """Deepest service root containing the file ('.' contains everything)."""
    best: str | None = None
    for root in roots:
        inside = root == "." or path == root or path.startswith(root + "/")
        if inside and (best is None or len(root) > len(best) or best == "."):
            best = root
    return best


def _is_test_path(path: str) -> bool:
    parts = path.split("/")
    name = parts[-1]
    return bool(TEST_DIRS & set(parts[:-1])) or name.startswith("test_") or ".test." in name


def _read(repo: Path, path: str) -> str:
    if (repo / path).is_symlink():  # defence in depth: scan already excludes symlinks
        raise OSError(f"refusing to read a symlink: {path}")
    return (repo / path).read_bytes()[:MAX_READ_BYTES].decode("utf-8", errors="replace")


def merge_facts(facts: list[Fact]) -> list[Fact]:
    """One Fact per (kind, value); evidence combined, bounded and sorted."""
    merged: dict[tuple[str, str], Fact] = {}
    for fact in facts:
        key = (fact.kind, fact.value)
        if key not in merged:
            merged[key] = fact.model_copy(deep=True)
            continue
        known = merged[key]
        seen = {(e.path, e.line) for e in known.evidence}
        known.evidence += [e for e in fact.evidence if (e.path, e.line) not in seen]
        if fact.certainty == "parsed":
            known.certainty = "parsed"
    for fact in merged.values():
        fact.evidence.sort(key=lambda e: (e.path, e.line or 0))
        del fact.evidence[MAX_EVIDENCE_PER_FACT:]
    return [merged[key] for key in sorted(merged)]


def _source_facts(
    repo: Path, path: str, digest: str, language: str, cache: HashCache, stats: ExtractStats
) -> list[Fact]:
    cached = cache.get_facts(path, digest, EXTRACTOR_VERSION)
    if cached is not None:
        stats.cached += 1
        return FACTS.validate_json(cached)
    facts = SOURCE_EXTRACTORS[language](path, _read(repo, path))
    cache.put_facts(path, digest, EXTRACTOR_VERSION, FACTS.dump_json(facts).decode())
    stats.extracted += 1
    return facts


def _is_compose_file(base: str) -> bool:
    return base.startswith(("docker-compose", "compose")) and base.endswith((".yml", ".yaml"))


def _config_facts(repo: Path, path: str, base: str) -> list[Fact]:
    """Small config files are parsed on every run; no cache needed."""
    if base == "Dockerfile" or base.startswith("Dockerfile."):
        return docker.extract(path, _read(repo, path))
    if base in CONFIG_EXTRACTORS:
        return CONFIG_EXTRACTORS[base](path, _read(repo, path))
    if base.startswith("requirements") and base.endswith(".txt"):
        return manifests.extract_requirements(path, _read(repo, path))
    if base == ".env" or base.startswith(".env."):
        return manifests.extract_env_file(path, _read(repo, path))
    return []


def extract_system(
    repo: Path, inventory: Inventory, candidates: list[ServiceCandidate], cache: HashCache
) -> tuple[SystemModel, ExtractStats]:
    stats = ExtractStats()
    roots = [c.root for c in candidates]
    by_root: dict[str, list[Fact]] = {root: [] for root in roots}
    not_analyzed: list[str] = []
    excluded_tests = 0
    infra: dict[str, tuple[Fact, list[str]]] = {}

    for entry in inventory.files:
        base = posixpath.basename(entry.path)
        owner = _owner(entry.path, roots)
        is_compose = _is_compose_file(base)
        if owner is None and not is_compose:
            continue  # compose files may sit above every service root
        if entry.skipped:
            not_analyzed.append(f"{entry.path}: skipped ({entry.skipped})")
            continue
        try:
            if is_compose:
                result = compose.extract(entry.path, _read(repo, entry.path))
                for root, facts in result.per_root.items():
                    if root in by_root:
                        by_root[root] += facts
                for name, fact in result.infra.items():
                    infra[name] = (fact, result.users.get(name, []))
            elif owner is None:
                continue
            elif _is_test_path(entry.path) and entry.language:
                excluded_tests += 1
            elif entry.language in SOURCE_EXTRACTORS:
                by_root[owner] += _source_facts(
                    repo, entry.path, entry.hash, entry.language, cache, stats
                )
            else:
                by_root[owner] += _config_facts(repo, entry.path, base)
        except ExtractionError as error:
            not_analyzed.append(f"{entry.path}: {error}")

    if excluded_tests:
        not_analyzed.append(f"{excluded_tests} test files excluded from analysis")

    services = [
        Service(id=c.id, root=c.root, kind=c.kind, facts=merge_facts(by_root[c.root]))
        for c in candidates
    ]
    id_by_root = {c.root: c.id for c in candidates}
    shared = {
        name: (fact, [id_by_root[r] for r in users if r in id_by_root])
        for name, (fact, users) in infra.items()
        if len({id_by_root.get(r) for r in users}) > 1
    }
    system = SystemModel(
        services=services,
        edges=sorted(
            [*http_edges(services), *infra_edges(shared)],
            key=lambda e: (e.src, e.dst, e.via),
        ),
        shared_infra=[fact for _, (fact, _) in sorted(shared.items())],
        not_analyzed=sorted(not_analyzed),
    )
    log.info("extracted facts for %d services (%d files, %d cached)", len(services),
             stats.extracted, stats.cached)  # fmt: skip
    return system, stats
