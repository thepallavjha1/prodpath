from pathlib import Path

from prodpath.cache import HashCache
from prodpath.detect import detect_services
from prodpath.models import Evidence, Fact, Service, ServiceCandidate
from prodpath.scan import ScanStats, scan_repo


def scan_and_detect(
    repo: Path, cache_path: Path
) -> tuple[list[ServiceCandidate], ScanStats, list[str]]:
    cache = HashCache(cache_path)
    try:
        inventory, stats = scan_repo(repo, cache)
    finally:
        cache.close()
    return detect_services(repo, inventory), stats, [e.path for e in inventory.files]


def write_files(root: Path, files: dict[str, str]) -> None:
    for rel_path, content in files.items():
        target = root / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


def make_fact(kind: str, value: str, path: str = "svc/app.py", line: int = 1) -> Fact:
    evidence = [Evidence(path=path, line=line, snippet="x")]
    return Fact(kind=kind, value=value, evidence=evidence, certainty="parsed")  # type: ignore[arg-type]


def make_service(sid: str, kind: str, facts: list[Fact]) -> Service:
    return Service(id=sid, root=sid, kind=kind, facts=facts)  # type: ignore[arg-type]
