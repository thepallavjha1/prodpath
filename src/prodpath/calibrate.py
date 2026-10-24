"""Compare a forecast with a real AWS bill (ADR-022). Pure functions plus one file writer.

Input is a Cost Explorer CSV grouped by service. Nothing here reads credentials or calls AWS:
the user exports the CSV from the console and hands it over.
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from prodpath.models import Forecast

GROUPS = (
    "compute", "load-balancer", "database", "cache", "network", "monitoring",
    "secrets", "registry", "storage-cdn", "messaging", "other",
)  # fmt: skip

# Substring (lower case) of the AWS service name in the bill -> forecast group. First match wins.
SERVICE_GROUPS = (
    ("container service", "compute"),
    ("fargate", "compute"),
    ("elastic load balancing", "load-balancer"),
    ("relational database", "database"),
    ("elasticache", "cache"),
    ("virtual private cloud", "network"),
    ("ec2 - other", "network"),
    ("amazoncloudwatch", "monitoring"),
    ("cloudwatch", "monitoring"),
    ("secrets manager", "secrets"),
    ("container registry", "registry"),
    ("simple storage service", "storage-cdn"),
    ("cloudfront", "storage-cdn"),
    ("simple queue service", "messaging"),
    ("simple notification service", "messaging"),
)
IGNORED_ROWS = ("total", "tax", "credit", "refund")  # not services; would double count

# Forecast component-name prefix -> group. Data transfer is matched by its dimension first.
COMPONENT_GROUPS = (
    ("ecs-svc-", "compute"), ("cron-", "compute"), ("worker-", "compute"),
    ("alb", "load-balancer"), ("rds", "database"), ("elasticache", "cache"),
    ("vpc-endpoints", "network"), ("task-public-ips", "network"), ("nat", "network"),
    ("logs-", "monitoring"), ("alarms", "monitoring"),
    ("secrets", "secrets"), ("ecr", "registry"),
    ("s3", "storage-cdn"), ("cloudfront", "storage-cdn"), ("static", "storage-cdn"),
    ("sqs", "messaging"), ("sns", "messaging"),
)  # fmt: skip


class CalibrationError(ValueError):
    """The CSV could not be understood; the message says what was expected."""


def group_of_line(component: str, dimension: str) -> str:
    if "data transfer" in dimension:
        return "network"
    for prefix, group in COMPONENT_GROUPS:
        if component.startswith(prefix):
            return group
    return "other"


def group_of_service(service: str) -> str:
    name = service.lower()
    for needle, group in SERVICE_GROUPS:
        if needle in name:
            return group
    return "other"


def _number(text: str) -> float | None:
    cleaned = text.strip().replace("$", "").replace(",", "")
    try:
        return float(cleaned)
    except ValueError:
        return None


def parse_cost_csv(text: str) -> dict[str, float]:
    """Return USD per AWS service. Uses a 'total' column when present, else sums the months."""
    rows = list(csv.reader(io.StringIO(text.lstrip("﻿"))))
    rows = [r for r in rows if any(cell.strip() for cell in r)]
    if len(rows) < 2:
        raise CalibrationError(
            "the CSV has no data rows (expected a header and one row per service)"
        )
    header = [h.strip().lower() for h in rows[0]]
    if not header[0].startswith("service"):
        raise CalibrationError(
            "the first column must be 'Service' (Cost Explorer: group by Service, download CSV)"
        )
    totals = [i for i, h in enumerate(header) if "total" in h and i > 0]
    columns = totals[:1] or list(range(1, len(header)))
    actual: dict[str, float] = {}
    for row in rows[1:]:
        name = row[0].strip()
        if not name or name.lower().startswith(IGNORED_ROWS):
            continue
        values = [_number(row[i]) for i in columns if i < len(row)]
        amount = sum(v for v in values if v is not None)
        actual[name] = actual.get(name, 0.0) + amount
    if not actual:
        raise CalibrationError("no service rows found in the CSV")
    return actual


@dataclass
class GroupResult:
    group: str
    predicted_low: float
    predicted: float
    predicted_spike: float
    actual: float
    error_pct: float | None  # (predicted - actual) / actual; None when actual is 0
    within_range: bool  # actual fell between the low and spike scenarios


@dataclass
class Calibration:
    groups: list[GroupResult]
    total: GroupResult
    months: float
    services: dict[str, str]  # AWS service name -> group it was assigned to


def _result(name: str, low: float, expected: float, spike: float, actual: float) -> GroupResult:
    error = (expected - actual) / actual if actual else None
    return GroupResult(name, low, expected, spike, actual, error, low <= actual <= spike)


def compare(forecast: Forecast, actual: dict[str, float], months: float = 1.0) -> Calibration:
    if months <= 0:
        raise CalibrationError("--months must be greater than 0")
    predicted = {g: [0.0, 0.0, 0.0] for g in GROUPS}
    for line in forecast.lines:
        bucket = predicted[group_of_line(line.component, line.dimension)]
        bucket[0] += line.usd_low
        bucket[1] += line.usd_expected
        bucket[2] += line.usd_spike
    billed = dict.fromkeys(GROUPS, 0.0)
    assigned = {}
    for service, usd in actual.items():
        group = group_of_service(service)
        assigned[service] = group
        billed[group] += usd / months
    results = [
        _result(g, predicted[g][0], predicted[g][1], predicted[g][2], billed[g])
        for g in GROUPS
        if any(predicted[g]) or billed[g]
    ]
    total = _result(
        "total",
        forecast.total_low,
        forecast.total_expected,
        forecast.total_spike,
        sum(billed.values()),
    )
    return Calibration(results, total, months, assigned)


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:+.0f}%"


def render_calibration(result: Calibration, stamp: str) -> str:
    lines = [
        f"<!-- prodpath calibration | {stamp} -->",
        "# Forecast versus real bill",
        f"Actual spend is divided by {result.months:g} month(s). Error is "
        "(predicted - actual) / actual, so a negative number means the forecast was too low.",
        "| Group | Low | Expected | Spike | Actual | Error | Actual inside range |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in [*result.groups, result.total]:
        label = f"**{r.group}**" if r is result.total else r.group
        lines.append(
            f"| {label} | ${r.predicted_low:,.2f} | ${r.predicted:,.2f} | "
            f"${r.predicted_spike:,.2f} | ${r.actual:,.2f} | {_pct(r.error_pct)} | "
            f"{'yes' if r.within_range else 'no'} |"
        )
    other = sorted(s for s, g in result.services.items() if g == "other")
    if other:
        lines.append(
            "## Not mapped\n\nThese bill lines matched no forecast group and sit under 'other': "
            + ", ".join(other)
            + "."
        )
    verdict = result.total.error_pct
    if verdict is not None:
        lines.append(
            "## Reading this\n\n"
            + (
                "Within the 25% accuracy target."
                if abs(verdict) <= 0.25
                else "Outside the 25% accuracy target: look at the groups with the largest error "
                "and update the matching assumptions in usage.toml."
            )
        )
    return "\n\n".join(lines) + "\n"


def append_dataset(path: Path, result: Calibration, stamp: str) -> None:
    """One JSON line per calibration run, kept locally (never committed)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {"at": stamp, "months": result.months, "total": asdict(result.total)}
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(row) + "\n")


def now_stamp() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
