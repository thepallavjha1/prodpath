import argparse
import logging
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

from prodpath import __version__
from prodpath.cache import HashCache
from prodpath.detect import detect_services
from prodpath.doctor import format_checks, run_doctor
from prodpath.extract import extract_system
from prodpath.forecast import UsageBook, UsageError, load_usage_file
from prodpath.iac_check import DEFAULT_MIRROR, TerraformReport, run_checks
from prodpath.llm import (
    DEFAULT_MAX_INPUT_TOKENS,
    DEFAULT_MODEL,
    DEFAULT_NUM_CTX,
    LLMError,
    OllamaLLM,
)
from prodpath.models import Inventory, Prefs, ServiceCandidate, Summaries, SystemModel
from prodpath.providers import get_provider
from prodpath.providers.aws.pricing import (
    DEFAULT_PRICE_DIR,
    PriceBook,
    PriceError,
    snapshot_path,
    update_prices,
)
from prodpath.render import render_forecast, render_plan
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
    plan = sub.add_parser("plan", help="write PLAN.md (needs no LLM)")
    plan.add_argument("--path", type=Path, default=Path("."), help="repo (default: .)")
    plan.add_argument("--provider", default="aws", choices=["aws"], help="target cloud")
    plan.add_argument("--region", default=Prefs().region, help="cloud region")
    plan.add_argument("--env", default="prod", choices=["prod", "nonprod"], help="environment")
    plan.add_argument(
        "--tf-mirror", type=Path, default=DEFAULT_MIRROR, help="local Terraform provider mirror"
    )
    forecast = sub.add_parser("forecast", help="write FORECAST.md: monthly cost range and traps")
    forecast.add_argument("--path", type=Path, default=Path("."), help="repo (default: .)")
    forecast.add_argument("--provider", default="aws", choices=["aws"], help="target cloud")
    forecast.add_argument("--region", default=Prefs().region, help="cloud region")
    forecast.add_argument("--env", default="prod", choices=["prod", "nonprod"], help="environment")
    forecast.add_argument("--usage", type=Path, help="usage.toml with your real numbers")
    forecast.add_argument(
        "--prices-dir", type=Path, default=DEFAULT_PRICE_DIR, help="price snapshots"
    )
    run = sub.add_parser(
        "run", help="everything: (summaries,) plan + Terraform, forecast (needs a price snapshot)"
    )
    run.add_argument("--path", type=Path, default=Path("."), help="repo (default: .)")
    run.add_argument("--provider", default="aws", choices=["aws"], help="target cloud")
    run.add_argument("--region", default=Prefs().region, help="cloud region")
    run.add_argument("--env", default="prod", choices=["prod", "nonprod"], help="environment")
    run.add_argument("--usage", type=Path, help="usage.toml with your real numbers")
    run.add_argument("--prices-dir", type=Path, default=DEFAULT_PRICE_DIR, help="price snapshots")
    run.add_argument("--tf-mirror", type=Path, default=DEFAULT_MIRROR, help="provider mirror")
    run.add_argument("--summarize", action="store_true", help="add local-LLM summaries (Ollama)")
    run.add_argument("--model", default=DEFAULT_MODEL, help="Ollama model tag for --summarize")
    run.add_argument("--num-ctx", type=int, default=DEFAULT_NUM_CTX, help="context window")
    prices = sub.add_parser("prices", help="manage the local price snapshot")
    prices_sub = prices.add_subparsers(dest="prices_command", required=True)
    update = prices_sub.add_parser("update", help="download the public AWS Price List (networked)")
    update.add_argument("--region", default=Prefs().region, help="region to download")
    update.add_argument("--dest", type=Path, default=DEFAULT_PRICE_DIR, help="snapshot directory")
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


def load_summaries(path: Path) -> Summaries | None:
    if not path.is_file():
        return None
    try:
        return Summaries.model_validate_json(path.read_text(encoding="utf-8"))
    except ValueError as error:
        print(f"note: ignoring unreadable {path.name}: {str(error)[:120]}", file=sys.stderr)
        return None


def write_terraform(out_dir: Path, files: dict[str, str]) -> None:
    target = out_dir / "out" / "terraform"
    shutil.rmtree(target, ignore_errors=True)  # our own output directory; avoids stale files
    target.mkdir(parents=True, exist_ok=True)
    for name, text in sorted(files.items()):
        (target / name).write_text(text, encoding="utf-8", newline="\n")


def run_plan(repo: Path, prefs: Prefs, mirror: Path) -> int:
    repo = repo.resolve()
    out_dir = repo / OUTPUT_DIR
    cache = HashCache(out_dir / "cache.sqlite")
    try:
        inventory, _ = scan_repo(repo, cache)
        system, _ = extract_system(repo, inventory, detect_services(repo, inventory), cache)
    finally:
        cache.close()
    provider = get_provider(prefs.provider)
    arch = provider.choose(system, prefs)
    steps = provider.steps(arch)
    files, checks = run_checks(provider.render_iac(arch), mirror, workdir=out_dir / "tfcheck")
    shutil.rmtree(out_dir / "tfcheck", ignore_errors=True)
    if any(c.name == "self-scan" and c.status == "fail" for c in checks):
        print(
            f"error: generated Terraform failed the self-scan: {checks[0].detail}", file=sys.stderr
        )
        return 1
    report = TerraformReport(sorted(files), provider.iac_gaps(arch), checks) if files else None
    summaries = load_summaries(out_dir / "summaries.json")
    stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    plan = render_plan(system, arch, steps, prefs, summaries, stamp, report)
    (out_dir / "out").mkdir(parents=True, exist_ok=True)
    (out_dir / "architecture.json").write_text(
        arch.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    (out_dir / "out" / "PLAN.md").write_text(plan, encoding="utf-8")
    if files:
        write_terraform(out_dir, files)
    print(f"wrote {out_dir / 'out' / 'PLAN.md'}")
    print(f"{len(arch.components)} components, {len(steps)} steps, {len(arch.unknowns)} unknowns")
    for check in checks:
        print(
            f"  {check.name}: {check.status}"
            + ("" if check.status == "ok" else f" ({check.detail[:160]})")
        )
    if summaries is None:
        print("note: no summaries.json; run `prodpath summarize` to add service purposes")
    return 1 if any(c.status == "fail" for c in checks) else 0


def run_prices_update(region: str, directory: Path) -> int:
    """The only networked command: downloads the public AWS Price List for one region."""
    try:
        path = update_prices(region, directory)
        book = PriceBook.load(path)
    except PriceError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(f"wrote {path}")
    print(book.describe())
    print(f"{book.count} prices extracted")
    for key, reason in sorted(book.missing.items()):
        print(f"warning: no price for {key}: {reason}", file=sys.stderr)
    return 0


def run_forecast(repo: Path, prefs: Prefs, usage_path: Path | None, price_dir: Path) -> int:
    repo = repo.resolve()
    out_dir = repo / OUTPUT_DIR
    cache = HashCache(out_dir / "cache.sqlite")
    try:
        inventory, _ = scan_repo(repo, cache)
        system, _ = extract_system(repo, inventory, detect_services(repo, inventory), cache)
    finally:
        cache.close()
    provider = get_provider(prefs.provider, price_dir)
    arch = provider.choose(system, prefs)
    try:
        usage = load_usage_file(usage_path) if usage_path else UsageBook()
        forecast = provider.forecast(arch, system, usage)
    except (PriceError, UsageError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    traps = provider.traps(arch, system, forecast)
    stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    (out_dir / "out").mkdir(parents=True, exist_ok=True)
    (out_dir / "forecast.json").write_text(
        forecast.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    (out_dir / "out" / "FORECAST.md").write_text(
        render_forecast(arch, forecast, traps, stamp), encoding="utf-8"
    )
    print(f"wrote {out_dir / 'out' / 'FORECAST.md'}")
    print(
        f"expected ${forecast.total_expected:,.2f}/month "
        f"(low ${forecast.total_low:,.2f}, spike ${forecast.total_spike:,.2f}); "
        f"{len(traps)} traps, {len(forecast.not_priced)} items not priced"
    )
    defaults = sum(1 for a in forecast.assumptions if a.source == "default")
    print(f"note: {defaults} assumptions are defaults; pass --usage usage.toml to use your numbers")
    return 0


def _write_stage_outputs(repo: Path) -> int:
    """Leave inventory.json and system.json for inspection; return the service count."""
    out_dir = repo / OUTPUT_DIR
    cache = HashCache(out_dir / "cache.sqlite")
    try:
        inventory, _ = scan_repo(repo, cache)  # a cache hit after the earlier stages: instant
        candidates = detect_services(repo, inventory)
        system, _ = extract_system(repo, inventory, candidates, cache)
    finally:
        cache.close()
    write_inventory(out_dir / "inventory.json", inventory)
    (out_dir / "system.json").write_text(system.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return len(candidates)


def run_all(
    repo: Path,
    prefs: Prefs,
    usage_path: Path | None,
    price_dir: Path,
    mirror: Path,
    summarize: bool,
    model: str,
    num_ctx: int,
) -> int:
    """Everything in order: (summaries,) plan with Terraform, then the forecast."""
    repo = repo.resolve()
    if not snapshot_path(price_dir, prefs.region).is_file():
        # Fail before any work: the forecast is the last stage and needs this file.
        print(
            f"error: no price snapshot for {prefs.region} in {price_dir}. Run "
            f"`prodpath prices update --region {prefs.region}` once (the only networked command).",
            file=sys.stderr,
        )
        return 1
    if summarize and run_summarize(repo, model, num_ctx) != 0:
        return 1  # run_summarize already printed why; do not present a half-finished result
    if (code := run_plan(repo, prefs, mirror)) != 0:
        return code
    if (code := run_forecast(repo, prefs, usage_path, price_dir)) != 0:
        return code
    out = repo / OUTPUT_DIR / "out"
    print(f"\n{_write_stage_outputs(repo)} services detected. Read these next:")
    print(f"  {out / 'PLAN.md'}")
    print(f"  {out / 'FORECAST.md'}")
    print(f"  {out / 'terraform'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING)
    if args.command == "scan":
        return run_scan(args.path)
    if args.command == "facts":
        return run_facts(args.path, args.service)
    if args.command == "plan":
        prefs = Prefs(provider=args.provider, region=args.region, environment=args.env)
        return run_plan(args.path, prefs, args.tf_mirror)
    if args.command == "run":
        prefs = Prefs(provider=args.provider, region=args.region, environment=args.env)
        return run_all(
            args.path,
            prefs,
            args.usage,
            args.prices_dir,
            args.tf_mirror,
            args.summarize,
            args.model,
            args.num_ctx,
        )
    if args.command == "prices":
        return run_prices_update(args.region, args.dest)
    if args.command == "forecast":
        prefs = Prefs(provider=args.provider, region=args.region, environment=args.env)
        return run_forecast(args.path, prefs, args.usage, args.prices_dir)
    if args.command == "summarize":
        return run_summarize(args.path, args.model, args.num_ctx)
    if args.command == "doctor":
        checks = run_doctor(args.model)
        print(format_checks(checks))
        return 1 if any(c.status == "fail" for c in checks) else 0
    return 2  # unreachable: argparse enforces a known command


if __name__ == "__main__":
    sys.exit(main())
