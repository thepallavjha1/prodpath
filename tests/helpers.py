from pathlib import Path

from prodpath.cache import HashCache
from prodpath.detect import detect_services
from prodpath.models import ServiceCandidate
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
