"""Cloud-neutral forecast machinery: usage assumptions, `usage.toml`, and traffic scenarios.

Every assumption that influences a number is recorded with its source (user, default or
inferred) and printed in FORECAST.md. Nothing here knows a price or a cloud.
"""

import tomllib
from pathlib import Path

from prodpath.models import UsageAssumption

SCENARIOS = ("low", "expected", "spike")

# name -> (default value, unit, note). Defaults are placeholders for "a small production app",
# not measurements: the forecast says so, and `usage.toml` overrides them.
DEFAULTS: dict[str, tuple[float, str, str]] = {
    "avg_requests_per_second": (
        1.0,
        "req/s",
        "Average external requests per second per web service.",
    ),
    "response_kb": (10.0, "KB", "Average response size sent to the internet."),
    "log_kb_per_request": (2.0, "KB", "Log volume per request (not extracted from code yet)."),
    "worker_log_gb_per_month": (1.0, "GB", "Log volume per worker or scheduled service."),
    "scenario_low": (0.25, "x", "Traffic multiplier for the low scenario."),
    "scenario_spike": (5.0, "x", "Traffic multiplier for the spike scenario."),
    "s3_stored_gb": (10.0, "GB", "Stored data per bucket."),
    "s3_puts_per_month": (100_000.0, "requests", "S3 PUT/COPY/POST/LIST requests per bucket."),
    "s3_gets_per_month": (1_000_000.0, "requests", "S3 GET requests per bucket."),
    "sqs_messages_per_month": (
        1_000_000.0,
        "messages",
        "Messages through the queue (3 API calls each).",
    ),
    "task_starts_per_month": (
        30.0,
        "starts",
        "Starts per task per month; each start reads its secrets.",
    ),
    "cron_runs_per_month": (30.0, "runs", "Runs per scheduled job per month."),
    "cron_minutes_per_run": (10.0, "min", "Duration of one scheduled job run."),
    "ecr_gb_per_repo": (2.0, "GB", "Image storage per repository."),
    "site_stored_gb": (0.5, "GB", "Built files stored per static site."),
    "cdn_cache_hit_ratio": (
        0.9,
        "ratio",
        "Share of static requests answered by CloudFront without reaching S3.",
    ),
    "hours_per_month": (730.0, "h", "AWS billing convention for a month."),
}
# Only these can be overridden for a single service in `[service."<id>"]`.
PER_SERVICE = {
    "avg_requests_per_second", "response_kb", "log_kb_per_request", "worker_log_gb_per_month",
    "cron_runs_per_month", "cron_minutes_per_run",
}  # fmt: skip


class UsageError(Exception):
    """usage.toml is invalid. The message lists what is allowed."""


class UsageBook:
    """Resolves assumptions (service override > global override > default) and records use."""

    def __init__(
        self,
        overrides: dict[str, float] | None = None,
        service_overrides: dict[str, dict[str, float]] | None = None,
    ) -> None:
        self._overrides = overrides or {}
        self._service_overrides = service_overrides or {}
        self._used: dict[tuple[str, str | None], UsageAssumption] = {}

    def get(self, name: str, service: str | None = None) -> float:
        default, unit, note = DEFAULTS[name]
        key: tuple[str, str | None] = (name, None)
        label, source, value = name, "default", default
        if service and name in self._service_overrides.get(service, {}):
            key, label = (name, service), f"{name}@{service}"
            source, value = "user", self._service_overrides[service][name]
        elif name in self._overrides:
            source, value = "user", self._overrides[name]
        if key not in self._used:
            self._used[key] = UsageAssumption(
                name=label,
                value=value,
                unit=unit,
                source="user" if source == "user" else "default",
                note=note,
            )
        return value

    def infer(self, name: str, value: float, unit: str, note: str) -> float:
        """Record an assumption derived from the code analysis (source: inferred)."""
        self._used[(name, None)] = UsageAssumption(
            name=name, value=value, unit=unit, source="inferred", note=note
        )
        return value

    def factor(self, scenario: str) -> float:
        if scenario == "expected":
            return 1.0
        return self.get("scenario_low" if scenario == "low" else "scenario_spike")

    def assumptions(self) -> list[UsageAssumption]:
        return sorted(self._used.values(), key=lambda a: a.name)


def load_usage_file(path: Path) -> UsageBook:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise UsageError(f"usage file not found: {path}") from error
    except tomllib.TOMLDecodeError as error:
        raise UsageError(f"{path} is not valid TOML: {error}") from error
    allowed = ", ".join(sorted(DEFAULTS))
    overrides: dict[str, float] = {}
    services: dict[str, dict[str, float]] = {}
    for key, value in data.items():
        if key == "service" and isinstance(value, dict):
            for service_id, table in value.items():
                services[service_id] = _checked(table, PER_SERVICE, f"[service.{service_id}]", path)
        elif key in DEFAULTS:
            overrides.update(_checked({key: value}, set(DEFAULTS), "top level", path))
        else:
            raise UsageError(f"{path}: unknown key {key!r}. Allowed: {allowed}, [service.<id>]")
    return UsageBook(overrides, services)


def _checked(table: object, allowed: set[str], where: str, path: Path) -> dict[str, float]:
    if not isinstance(table, dict):
        raise UsageError(f"{path}: {where} must be a table of numbers")
    checked: dict[str, float] = {}
    for name, value in table.items():
        if name not in allowed:
            raise UsageError(
                f"{path}: {where} has unknown key {name!r}. Allowed: {', '.join(sorted(allowed))}"
            )
        if isinstance(value, bool) or not isinstance(value, int | float) or value < 0:
            raise UsageError(f"{path}: {where} {name} must be a non-negative number, got {value!r}")
        checked[name] = float(value)
    return checked
