import argparse
import logging
import sys
from pathlib import Path

from prodpath import __version__
from prodpath.cache import HashCache
from prodpath.detect import detect_services
from prodpath.doctor import format_checks, run_doctor
from prodpath.extract import extract_system
from prodpath.llm import (
    DEFAULT_MAX_INPUT_TOKENS,
    DEFAULT_MODEL,
    DEFAULT_NUM_CTX,
    LLMError,
    OllamaLLM,
)
from prodpath.models import Inventory, ServiceCandidate, Summaries, SystemModel
from prodpath.scan import scan_repo
from prodpath.summarize import summarize_system

OUTPUT_DIR = ".prodpath"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="prodpath",
        description="Read-only local agent: reads your repo, writes a production plan.",
    )
    parser.add_argument("--version", action="version", version=f"prodpath {__version__}")
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    sub = parser.add_subparsers(dest="command", required=True)
    doctor = sub.add_parser("doctor", help="check Ollama, model, GPU/VRAM, terraform")
    doctor.add_argument("--model", default=DEFAULT_MODEL, help="Ollama model tag to check")
    scan = sub.add_parser("scan", help="scan the repo and list detected services")
    scan.add_argument("--path", type=Path, default=Path("."), help="repo to scan (default: .)")
    facts = sub.add_parser("facts", help="extract evidence-backed facts per service")
    facts.add_argument("--path", type=Path, default=Path("."), help="repo to analyze (default: .)")
    facts.add_argument("--service", help="only show this service id")
    summarize = sub.add_parser("summarize", help="local-LLM summaries (needs Ollama running)")
    summarize.add_argument("--path", type=Path, default=Path("."), help="repo (default: .)")
    summarize.add_argument("--model", default=DEFAULT_MODEL, help="Ollama model tag")
    summarize.add_argument("--num-ctx", type=int, default=DEFAULT_NUM_CTX, help="context window")
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


def format_system(system: SystemModel, only_service: str | None = None) -> str:
    out: list[str] = []
    for service in system.services:
        if only_service and service.id != only_service:
            continue
        out.append(f"{service.id} ({service.kind}) root={service.root}")
        for fact in service.facts:
            ev = fact.evidence[0]
            where = f"{ev.path}:{ev.line}" if ev.line else ev.path
            mark = "" if fact.certainty == "parsed" else " [heuristic]"
            out.append(f"  {fact.kind:<15} {fact.value}  <- {where}{mark}")
    if not only_service:
        for edge in system.edges:
            out.append(f"edge: {edge.src} -> {edge.dst} via {edge.via}")
        for note in system.not_analyzed:
            out.append(f"not analyzed: {note}")
    return "\n".join(out)


def run_facts(repo: Path, only_service: str | None) -> int:
    repo = repo.resolve()
    cache = HashCache(repo / OUTPUT_DIR / "cache.sqlite")
    try:
        inventory, _ = scan_repo(repo, cache)
        candidates = detect_services(repo, inventory)
        system, stats = extract_system(repo, inventory, candidates, cache)
    finally:
        cache.close()
    target = repo / OUTPUT_DIR / "system.json"
    target.write_text(system.model_dump_json(indent=2) + "\n", encoding="utf-8")
    print(format_system(system, only_service))
    print(f"\n{stats.extracted} files extracted, {stats.cached} from cache")
    return 0


def format_summaries(summaries: Summaries) -> str:
    out = []
    for item in summaries.services:
        out.append(f"{item.service_id} ({item.role}) [{item.generated_by}]: {item.purpose}")
        for risk in item.risks:
            out.append(f"  risk: {risk.text}  <- {', '.join(risk.evidence_ids)}")
        if item.hot_path:
            out.append(
                f"  hot path: {item.hot_path.text}  <- {', '.join(item.hot_path.evidence_ids)}"
            )
        if item.dropped_claims:
            out.append(f"  ({item.dropped_claims} claims dropped: no valid evidence)")
    system = summaries.system
    out.append(f"\nOverview: {system.overview}")
    for key_risk in system.key_risks:
        out.append(f"  key risk: {key_risk.text}  [{', '.join(key_risk.service_ids)}]")
    if system.omitted_services:
        out.append(f"  ({system.omitted_services} services omitted from the overview: too large)")
    return "\n".join(out)


def run_summarize(repo: Path, model: str, num_ctx: int) -> int:
    repo = repo.resolve()
    cache = HashCache(repo / OUTPUT_DIR / "cache.sqlite")
    try:
        inventory, _ = scan_repo(repo, cache)
        system, _ = extract_system(repo, inventory, detect_services(repo, inventory), cache)
        llm = OllamaLLM(model=model, num_ctx=num_ctx, cache=cache)
        try:
            summaries = summarize_system(llm, system, model, DEFAULT_MAX_INPUT_TOKENS)
        except LLMError as error:
            print(f"error: {error}", file=sys.stderr)
            return 1
    finally:
        cache.close()
    target = repo / OUTPUT_DIR / "summaries.json"
    target.write_text(summaries.model_dump_json(indent=2) + "\n", encoding="utf-8")
    print(format_summaries(summaries))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING)
    if args.command == "scan":
        return run_scan(args.path)
    if args.command == "facts":
        return run_facts(args.path, args.service)
    if args.command == "summarize":
        return run_summarize(args.path, args.model, args.num_ctx)
    if args.command == "doctor":
        checks = run_doctor(args.model)
        print(format_checks(checks))
        return 1 if any(c.status == "fail" for c in checks) else 0
    return 2  # unreachable: argparse enforces a known command


if __name__ == "__main__":
    sys.exit(main())
