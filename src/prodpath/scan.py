"""Stage 1: walk the repo, hash files, detect languages. Deterministic, no LLM."""

import fnmatch
import hashlib
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

from prodpath.cache import HashCache
from prodpath.models import FileEntry, Inventory

log = logging.getLogger(__name__)

# Never descended into. `.prodpath` is our own output folder.
IGNORED_DIRS = {
    ".git", "node_modules", "dist", "build", ".venv", "venv", "vendor", "__pycache__",
    ".prodpath", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".next", ".terraform", "target",
}  # fmt: skip
MAX_HASH_BYTES = 5 * 1024 * 1024  # larger files are listed as skipped, not read
LANGUAGES = {
    ".py": "python", ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".ts": "typescript", ".tsx": "typescript", ".go": "go", ".rs": "rust", ".java": "java",
    ".rb": "ruby", ".tf": "terraform", ".sh": "shell",
}  # fmt: skip


@dataclass
class ScanStats:
    hashed: int = 0  # files actually read and hashed this run
    cached: int = 0  # files served from the cache
    unsupported_gitignore: list[str] = field(default_factory=list)


def _load_gitignore(repo: Path, stats: ScanStats) -> list[str]:
    gitignore = repo / ".gitignore"
    if not gitignore.is_file():
        return []
    patterns = []
    for raw in gitignore.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("!"):  # negation is out of scope; say so instead of guessing
            stats.unsupported_gitignore.append(line)
            continue
        patterns.append(line)
    return patterns


def _is_gitignored(rel_path: str, is_dir: bool, patterns: list[str]) -> bool:
    name = rel_path.rsplit("/", 1)[-1]
    for pattern in patterns:
        dir_only = pattern.endswith("/")
        bare = pattern.strip("/")
        if dir_only and not is_dir:
            continue
        if fnmatch.fnmatch(name, bare) or fnmatch.fnmatch(rel_path, bare.lstrip("/")):
            return True
    return False


def _hash_file(path: Path) -> str:
    digest = hashlib.blake2b(digest_size=16)
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def scan_repo(repo: Path, cache: HashCache) -> tuple[Inventory, ScanStats]:
    stats = ScanStats()
    patterns = _load_gitignore(repo, stats)
    entries: list[FileEntry] = []
    for dirpath, dirnames, filenames in os.walk(repo):
        rel_dir = Path(dirpath).relative_to(repo).as_posix()
        prefix = "" if rel_dir == "." else rel_dir + "/"
        dirnames[:] = sorted(
            d for d in dirnames
            if d not in IGNORED_DIRS and not _is_gitignored(prefix + d, True, patterns)
        )  # fmt: skip
        for filename in sorted(filenames):
            rel_path = prefix + filename
            if _is_gitignored(rel_path, False, patterns):
                continue
            entries.append(_entry_for(repo / rel_path, rel_path, cache, stats))
    entries.sort(key=lambda e: e.path)
    log.info("scanned %d files (%d hashed, %d cached)", len(entries), stats.hashed, stats.cached)
    return Inventory(files=entries), stats


def _entry_for(path: Path, rel_path: str, cache: HashCache, stats: ScanStats) -> FileEntry:
    info = path.stat()
    language = LANGUAGES.get(path.suffix.lower())
    if info.st_size > MAX_HASH_BYTES:
        return FileEntry(path=rel_path, hash="", size=info.st_size, language=language,
                         skipped="too large")  # fmt: skip
    digest = cache.get(rel_path, info.st_mtime_ns, info.st_size)
    if digest is None:
        digest = _hash_file(path)
        cache.put(rel_path, info.st_mtime_ns, info.st_size, digest)
        stats.hashed += 1
    else:
        stats.cached += 1
    return FileEntry(path=rel_path, hash=digest, size=info.st_size, language=language)
