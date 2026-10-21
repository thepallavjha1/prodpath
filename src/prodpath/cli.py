import argparse
import logging
import sys
from pathlib import Path

from prodpath import __version__
from prodpath.cache import HashCache
from prodpath.detect import detect_services
from prodpath.models import Inventory, ServiceCandidate
from prodpath.scan import scan_repo

OUTPUT_DIR = ".prodpath"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="prodpath",
        description="Read-only local agent: reads your repo, writes a production plan.",
    )
    parser.add_argument("--version", action="version", version=f"prodpath {__version__}")
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="check Ollama, model, GPU/VRAM, terraform (stub in phase 0)")
    scan = sub.add_parser("scan", help="scan the repo and list detected services")
    scan.add_argument("--path", type=Path, default=Path("."), help="repo to scan (default: .)")
    return parser


def format_service_table(services: list[ServiceCandidate]) -> str:
    rows = [("ID", "ROOT", "KIND", "EVIDENCE")]
    for service in services:
        ev = service.evidence[0]
        where = f"{ev.path}:{ev.line}" if ev.line else ev.path
        suffix = "" if service.certainty == "parsed" else " (heuristic)"
        rows.append((service.id, service.root, service.kind, where + suffix))
    widths = [max(len(row[i]) for row in rows) for i in range(4)]
    lines = ["  ".join(cell.ljust(w) for cell, w in zip(row, widths, strict=True)) for row in rows]
    return "\n".join(line.rstrip() for line in lines)


def write_inventory(path: Path, inventory: Inventory) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(inventory.model_dump_json(indent=2) + "\n", encoding="utf-8")


def run_scan(repo: Path) -> int:
    repo = repo.resolve()
    cache = HashCache(repo / OUTPUT_DIR / "cache.sqlite")
    try:
        inventory, stats = scan_repo(repo, cache)
    finally:
        cache.close()
    write_inventory(repo / OUTPUT_DIR / "inventory.json", inventory)
    services = detect_services(repo, inventory)
    print(format_service_table(services))
    counts = f"{stats.hashed} hashed, {stats.cached} cached"
    print(f"\n{len(inventory.files)} files ({counts}), {len(services)} services")
    for pattern in stats.unsupported_gitignore:
        print(f"note: unsupported .gitignore pattern ignored: {pattern}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING)
    if args.command == "scan":
        return run_scan(args.path)
    if args.command == "doctor":
        print("doctor: not implemented yet (phase 3). Nothing was checked.")
        return 0
    return 2  # unreachable: argparse enforces a known command


if __name__ == "__main__":
    sys.exit(main())
