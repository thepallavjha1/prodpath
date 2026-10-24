"""Analysis pipeline for web mode plus the job queue around it (ADR-019).

`analyze_repo` is the CLI's plan + forecast path without writing into the repository.
`JobManager` runs it in worker threads with a concurrency cap, a per-client rate limit and a
retention window, and always deletes the cloned workspace.
"""

from __future__ import annotations

import logging
import secrets
import shutil
import tempfile
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path

from prodpath.cache import HashCache
from prodpath.detect import detect_services
from prodpath.extract import extract_system
from prodpath.forecast import DEFAULTS, UsageBook
from prodpath.iac_check import CheckResult, TerraformReport, run_checks
from prodpath.models import Architecture, Forecast, Prefs, Step, SystemModel, Trap
from prodpath.providers import get_provider
from prodpath.providers.aws.pricing import PriceError
from prodpath.render import render_forecast, render_plan
from prodpath.scan import scan_repo
from prodpath.web.github import (
    RepoError,
    RepoRef,
    check_limits,
    clone,
    parse_github_url,
)

log = logging.getLogger(__name__)
STAGES = ("clone", "scan", "facts", "plan", "forecast")
SAMPLE = "sample"
Progress = Callable[[str, str], None]
CloneFn = Callable[[RepoRef, Path], str]


class JobError(Exception):
    """Refused before running (rate limit, busy, bad option); the message is safe to show."""


@dataclass
class Run:
    source: dict[str, object]
    system: SystemModel
    prefs: Prefs
    usage_values: dict[str, float]
    arch: Architecture
    steps: list[Step]
    files: dict[str, str]
    checks: list[CheckResult]
    gaps: list[str]
    forecast: Forecast
    traps: list[Trap]
    plan_md: str
    forecast_md: str
    created: float = 0.0


@dataclass
class Job:
    id: str
    client: str
    status: str = "queued"  # queued | running | done | error
    stage: str = "queued"
    log: list[str] = field(default_factory=list)
    error: str = ""
    created: float = 0.0


def usage_from_values(values: dict[str, float]) -> UsageBook:
    """Validate numbers from the web form the same way a usage.toml is validated."""
    clean: dict[str, float] = {}
    for name, value in values.items():
        if name not in DEFAULTS:
            raise JobError(f"unknown usage setting {name!r}")
        if isinstance(value, bool) or not isinstance(value, int | float) or value < 0:
            raise JobError(f"{name} must be a non-negative number")
        clean[name] = float(value)
    if clean.get("peak_to_average_ratio", 1.0) < 1:
        raise JobError("peak_to_average_ratio must be at least 1")
    return UsageBook(clean)


def _stamp() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_run(
    system: SystemModel,
    source: dict[str, object],
    prefs: Prefs,
    usage_values: dict[str, float],
    price_dir: Path,
    mirror: Path,
    workdir: Path,
    validate: bool,
) -> Run:
    """Everything after extraction: choose, render, check, forecast, traps, documents."""
    provider = get_provider(prefs.provider, price_dir)
    usage = usage_from_values(usage_values)
    arch = provider.choose(system, prefs)
    steps = provider.steps(arch)
    files, checks = run_checks(
        provider.render_iac(arch), mirror, workdir=workdir / "tfcheck" if validate else None
    )
    if any(c.name == "self-scan" and c.status == "fail" for c in checks):
        raise JobError(f"the generated Terraform failed its safety scan: {checks[0].detail}")
    gaps = provider.iac_gaps(arch)
    forecast = provider.forecast(arch, system, usage)
    traps = provider.traps(arch, system, forecast)
    stamp = _stamp()
    report = TerraformReport(sorted(files), gaps, checks) if files else None
    return Run(
        source=source, system=system, prefs=prefs, usage_values=usage_values, arch=arch,
        steps=steps, files=files, checks=checks, gaps=gaps, forecast=forecast, traps=traps,
        plan_md=render_plan(system, arch, steps, prefs, None, stamp, report),
        forecast_md=render_forecast(arch, forecast, traps, stamp),
        created=time.time(),
    )  # fmt: skip


def analyze_repo(
    repo_dir: Path,
    source: dict[str, object],
    prefs: Prefs,
    usage_values: dict[str, float],
    price_dir: Path,
    mirror: Path,
    workdir: Path,
    validate: bool,
    progress: Progress,
) -> Run:
    cache = HashCache(workdir / "cache.sqlite")  # outside the analysed repository
    try:
        progress("scan", "Listing files and detecting services")
        inventory, _ = scan_repo(repo_dir, cache)
        candidates = detect_services(repo_dir, inventory)
        progress("scan", f"Found {len(candidates)} deployable candidates")
        progress("facts", "Reading code, Dockerfiles and manifests (names only, never values)")
        system, _ = extract_system(repo_dir, inventory, candidates, cache)
    finally:
        cache.close()
    progress(
        "facts",
        f"{len(system.services)} services, {sum(len(s.facts) for s in system.services)} facts",
    )
    progress("plan", "Choosing AWS components and writing Terraform")
    run = build_run(system, source, prefs, usage_values, price_dir, mirror, workdir, validate)
    progress("forecast", f"Expected about ${run.forecast.total_expected:,.0f} per month")
    return run


def recompute(
    run: Run, prefs: Prefs, usage_values: dict[str, float], price_dir: Path, mirror: Path
) -> Run:
    """What-if: new traffic or budget choices on the stored system, without re-cloning."""
    with tempfile.TemporaryDirectory(prefix="prodpath-whatif-") as tmp:
        updated = build_run(
            run.system, run.source, prefs, usage_values, price_dir, mirror, Path(tmp), False
        )
    return replace(updated, created=run.created)


class JobManager:
    def __init__(
        self,
        price_dir: Path,
        mirror: Path,
        sample_dir: Path | None = None,
        clone_fn: CloneFn | None = None,
        max_concurrent: int = 2,
        rate_limit: int = 6,
        rate_window: float = 3600.0,
        retention: float = 3600.0,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.price_dir, self.mirror, self.sample_dir = price_dir, mirror, sample_dir
        self._clone = clone_fn or self._default_clone
        self.max_concurrent, self.rate_limit = max_concurrent, rate_limit
        self.rate_window, self.retention, self._clock = rate_window, retention, clock
        self._pool = ThreadPoolExecutor(max_workers=max_concurrent)
        self._lock = threading.Lock()
        self._jobs: dict[str, Job] = {}
        self._runs: dict[str, Run] = {}
        self._hits: dict[str, list[float]] = {}

    @staticmethod
    def _default_clone(ref: RepoRef, dest: Path) -> str:
        return clone(ref, dest)

    # -- public API ------------------------------------------------------------------------
    def submit(self, client: str, url: str, options: dict[str, object]) -> Job:
        prefs, usage_values, validate = self._options(options)
        ref = None if url.strip() == SAMPLE else parse_github_url(url)
        if ref is None and not (self.sample_dir and self.sample_dir.is_dir()):
            raise JobError("The built-in sample is not installed.")
        with self._lock:
            self._prune()
            self._check_rate(client)
            active = sum(1 for j in self._jobs.values() if j.status in ("queued", "running"))
            if active >= self.max_concurrent * 3:
                raise JobError("The server is busy right now; try again in a minute.")
            job = Job(id=secrets.token_urlsafe(9), client=client, created=self._clock())
            self._jobs[job.id] = job
        self._pool.submit(self._work, job, ref, prefs, usage_values, validate)
        return job

    def job(self, job_id: str) -> Job | None:
        with self._lock:
            self._prune()
            return self._jobs.get(job_id)

    def run(self, run_id: str) -> Run | None:
        with self._lock:
            self._prune()
            return self._runs.get(run_id)

    def whatif(self, run_id: str, options: dict[str, object]) -> Run:
        run = self.run(run_id)
        if run is None:
            raise JobError("That result has expired; analyse the repository again.")
        prefs, usage_values, _ = self._options(options, base=run.prefs)
        try:
            updated = recompute(run, prefs, usage_values, self.price_dir, self.mirror)
        except PriceError as error:
            raise JobError(str(error)) from error
        with self._lock:
            self._runs[run_id] = updated
        return updated

    def shutdown(self) -> None:
        self._pool.shutdown(wait=True, cancel_futures=True)

    # -- internals ---------------------------------------------------------------------------
    def _options(
        self, options: dict[str, object], base: Prefs | None = None
    ) -> tuple[Prefs, dict[str, float], bool]:
        base = base or Prefs()
        environment = options.get("environment", base.environment)
        region = options.get("region", base.region)
        if environment not in ("prod", "nonprod"):
            raise JobError("environment must be prod or nonprod")
        if not isinstance(region, str) or not (self.price_dir / f"{region}.json").is_file():
            raise JobError(
                f"No price snapshot for region {region!r}; run `prodpath prices update`."
            )
        raw = options.get("usage", {})
        if not isinstance(raw, dict):
            raise JobError("usage must be an object of numbers")
        usage_values = {str(k): v for k, v in raw.items()}
        usage_from_values(usage_values)  # validate now so the visitor gets the error immediately
        prefs = Prefs(
            region=region, environment=environment, budget=bool(options.get("budget", base.budget))
        )
        return prefs, usage_values, bool(options.get("validate", False))

    def _check_rate(self, client: str) -> None:
        now = self._clock()
        hits = [t for t in self._hits.get(client, []) if now - t < self.rate_window]
        if len(hits) >= self.rate_limit:
            raise JobError("Too many analyses from your address; please wait a while.")
        hits.append(now)
        self._hits[client] = hits

    def _prune(self) -> None:
        cutoff = self._clock() - self.retention
        for job_id in [
            j for j, v in self._jobs.items() if v.created < cutoff and v.status != "running"
        ]:
            self._jobs.pop(job_id, None)
            self._runs.pop(job_id, None)

    def _say(self, job: Job, stage: str, message: str) -> None:
        with self._lock:
            job.stage = stage
            job.log.append(f"[{stage}] {message}")

    def _work(
        self,
        job: Job,
        ref: RepoRef | None,
        prefs: Prefs,
        usage_values: dict[str, float],
        validate: bool,
    ) -> None:
        job.status = "running"
        workdir = Path(tempfile.mkdtemp(prefix="prodpath-job-"))
        try:
            repo_dir = workdir / "repo"
            if ref is None:
                assert self.sample_dir is not None
                shutil.copytree(self.sample_dir, repo_dir)
                source: dict[str, object] = {"sample": True, "name": "built-in sample"}
                self._say(job, "clone", "Using the built-in sample project (no network)")
            else:
                self._say(job, "clone", f"Fetching {ref.web_url} (shallow, read-only)")
                sha = self._clone(ref, repo_dir)
                check_limits(repo_dir)
                source = {
                    "sample": False, "owner": ref.owner, "repo": ref.repo,
                    "branch": ref.branch, "sha": sha, "url": ref.web_url,
                }  # fmt: skip
                self._say(job, "clone", f"Cloned commit {sha[:7]}")
            run = analyze_repo(
                repo_dir, source, prefs, usage_values, self.price_dir, self.mirror, workdir,
                validate, lambda stage, message: self._say(job, stage, message),
            )  # fmt: skip
            with self._lock:
                self._runs[job.id] = run
                job.status, job.stage = "done", "done"
        except (RepoError, JobError, PriceError) as error:
            self._fail(job, str(error))
        except Exception:  # a bug on our side: say so without leaking internals
            log.exception("analysis crashed")  # details stay in the server log
            self._fail(job, "Something went wrong while analysing this repository.")
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

    def _fail(self, job: Job, message: str) -> None:
        with self._lock:
            job.status, job.error = "error", message
            job.log.append(f"[error] {message}")
