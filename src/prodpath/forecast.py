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
    "peak_requests_per_second": (
        20.0,
        "req/s",
        "Busiest sustained requests per second per web service (the peak, not the average).",
    ),
    "peak_to_average_ratio": (
        5.0,
        "x",
        "How many times busier the peak is than the monthly average.",
    ),
    "avg_requests_per_second": (
        4.0,
        "req/s",
        "Average external requests per second per web service (monthly volume follows this).",
    ),
    "response_kb": (10.0, "KB", "Average response size sent to the internet."),
    "log_kb_per_request": (2.0, "KB", "Log volume per request (not extracted from code yet)."),
    "worker_log_gb_per_month": (1.0, "GB", "Log volume per worker or scheduled service."),
    "rps_per_task": (25.0, "req/s", "Requests per second one task handles at the CPU target."),
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
    "avg_requests_per_second", "peak_requests_per_second", "response_kb", "log_kb_per_request",
    "worker_log_gb_per_month", "rps_per_task",
    "cron_runs_per_month", "cron_minutes_per_run",
}  # fmt: skip


class UsageError(Exception):
    """usage.toml is invalid. The message lists what is allowed."""


class UsageBook:
    """Resolves assumptions (service override > global override > default) and records use.

    Traffic is modelled as a peak and an average (ADR-020): monthly volume follows the average,
    capacity follows the peak, and the spike scenario is a month at the peak.
    """

    def __init__(
        self,
        overrides: dict[str, float] | None = None,
        service_overrides: dict[str, dict[str, float]] | None = None,
    ) -> None:
        self._overrides = overrides or {}
        self._service_overrides = service_overrides or {}
        self._used: dict[tuple[str, str | None], UsageAssumption] = {}

    def _override(self, name: str, service: str | None) -> tuple[float, bool] | None:
        """(value, set for this service) when the user gave one, else None."""
        if service and name in self._service_overrides.get(service, {}):
            return self._service_overrides[service][name], True
        if name in self._overrides:
            return self._overrides[name], False
        return None

    def _record(
        self, name: str, service: str | None, value: float, source: str, note: str | None = None
    ) -> None:
        key = (name, service)
        if key not in self._used:
            _, unit, default_note = DEFAULTS[name]
            label = f"{name}@{service}" if service else name
            self._used[key] = UsageAssumption(
                name=label,
                value=value,
                unit=unit,
                source="user" if source == "user" else "default",
                note=note or default_note,
            )

    def _traffic(self, service: str | None) -> tuple[float, float, str, str | None]:
        """(average, peak, source, service the answer is specific to)."""
        ratio = self.get("peak_to_average_ratio")
        average = self._override("avg_requests_per_second", service)
        peak = self._override("peak_requests_per_second", service)
        specific = service if any(o is not None and o[1] for o in (average, peak)) else None
        if average is not None:
            avg_value = average[0]
            peak_value = peak[0] if peak is not None else avg_value * ratio
            return avg_value, peak_value, "user", specific
        if peak is not None:
            return peak[0] / ratio, peak[0], "user", specific
        default_peak = DEFAULTS["peak_requests_per_second"][0]
        return default_peak / ratio, default_peak, "default", None

    def get(self, name: str, service: str | None = None) -> float:
        if name == "avg_requests_per_second":
            return self._average(service)
        default = DEFAULTS[name][0]
        override = self._override(name, service)
        value = default if override is None else override[0]
        specific = service if override is not None and override[1] else None
        self._record(name, specific, value, "default" if override is None else "user")
        return value

    def _average(self, service: str | None) -> float:
        average, peak, source, specific = self._traffic(service)
        ratio = self.get("peak_to_average_ratio")
        explicit_average = self._override("avg_requests_per_second", service) is not None
        explicit_peak = self._override("peak_requests_per_second", service) is not None
        if explicit_average:
            avg_note = None  # the plain description from DEFAULTS
        else:
            avg_note = (
                f"Derived: peak {peak:g} req/s divided by the peak-to-average ratio {ratio:g}. "
                "Set it directly in usage.toml if you know the average."
            )
        self._record("avg_requests_per_second", specific, average, source, avg_note)
        if explicit_peak:
            peak_note = None
        elif explicit_average:
            peak_note = f"Implied: average {average:g} req/s times the ratio {ratio:g}."
        else:
            peak_note = None
        self._record("peak_requests_per_second", specific, peak, source, peak_note)
        return average

    def infer(self, name: str, value: float, unit: str, note: str) -> float:
        """Record an assumption derived from the code analysis (source: inferred)."""
        self._used[(name, None)] = UsageAssumption(
            name=name, value=value, unit=unit, source="inferred", note=note
        )
        return value

    def factor(self, scenario: str) -> float:
        if scenario == "expected":
            return 1.0
        if scenario == "low":
            return self.get("scenario_low")
        if self._override("scenario_spike", None) is not None:
            return self.get("scenario_spike")
        average, peak, source, _ = self._traffic(None)
        self._average(None)  # records the global average, peak and ratio the spike is based on
        factor = peak / average if average else self.get("peak_to_average_ratio")
        self._record(
            "scenario_spike", None, factor, source,
            "A month run at the peak: the peak divided by the average.",
        )  # fmt: skip
        return factor

    def assumptions(self) -> list[UsageAssumption]:
        return sorted(self._used.values(), key=lambda a: a.name)


def _format_number(value: float) -> str:
    return str(int(value)) if value == int(value) else repr(value)


def usage_template() -> str:
    """A usage.toml with every assumption, its default and a comment. Changes nothing as is."""
    lines = [
        "# prodpath usage.toml: your real numbers. Every line is optional.",
        "# The values below are the defaults, so this file changes nothing until you edit it.",
        "# Traffic is a peak and an average: volume follows the average, capacity the peak.",
        "",
    ]
    derived = {
        "avg_requests_per_second": "derived as peak / ratio; uncomment to set the average directly",
        "scenario_spike": "derived as peak / average; uncomment to force a spike multiplier",
    }
    for name, (value, unit, note) in DEFAULTS.items():
        if name in derived:
            lines.append(f"# {name} = {_format_number(value)}  # {unit}: {note} ({derived[name]})")
        else:
            lines.append(f"{name} = {_format_number(value)}  # {unit}: {note}")
    lines += [
        "",
        "# Per-service overrides (service ids are listed by `prodpath scan`):",
        '# [service."apps-api"]',
        "# peak_requests_per_second = 60",
        "# rps_per_task = 40",
        "",
    ]
    return "\n".join(lines)


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
    ratio = overrides.get("peak_to_average_ratio")
    if ratio is not None and ratio < 1:
        raise UsageError(
            f"{path}: peak_to_average_ratio must be at least 1 (the peak cannot be quieter than "
            f"the average), got {ratio:g}"
        )
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
