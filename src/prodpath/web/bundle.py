"""Turn a finished Run into the JSON the browser renders, plus the downloadable zip."""

from __future__ import annotations

import io
import zipfile
from typing import Any

from prodpath.calibrate import GROUPS, group_of_line
from prodpath.models import Evidence
from prodpath.web.github import RepoRef, evidence_url
from prodpath.web.jobs import Run


def _evidence(items: list[Evidence], ref: RepoRef | None, sha: str) -> list[dict[str, Any]]:
    return [
        {
            "path": e.path,
            "line": e.line,
            "snippet": e.snippet,
            "url": evidence_url(ref, sha, e.path, e.line) if ref else None,
        }
        for e in items
    ]


def _ref(run: Run) -> tuple[RepoRef | None, str]:
    source = run.source
    if source.get("sample"):
        return None, ""
    branch = source.get("branch")
    ref = RepoRef(str(source["owner"]), str(source["repo"]), str(branch) if branch else None)
    return ref, str(source["sha"])


def _cost_groups(run: Run) -> list[dict[str, Any]]:
    totals = {g: [0.0, 0.0, 0.0] for g in GROUPS}
    for line in run.forecast.lines:
        bucket = totals[group_of_line(line.component, line.dimension)]
        bucket[0] += line.usd_low
        bucket[1] += line.usd_expected
        bucket[2] += line.usd_spike
    return [
        {"group": g, "low": v[0], "expected": v[1], "spike": v[2]}
        for g, v in totals.items()
        if any(v)
    ]


def build_bundle(run: Run, run_id: str) -> dict[str, Any]:
    ref, sha = _ref(run)
    system, forecast = run.system, run.forecast

    def facts(items: list[Any]) -> list[dict[str, Any]]:
        return [
            {
                "kind": f.kind,
                "value": f.value,
                "certainty": f.certainty,
                "evidence": _evidence(f.evidence, ref, sha),
            }
            for f in items
        ]

    return {
        "id": run_id,
        "source": run.source,
        "prefs": run.prefs.model_dump(),
        "usage": run.usage_values,
        "summary": {
            "services": len(system.services),
            "components": len(run.arch.components),
            "steps": len(run.steps),
            "traps": len(run.traps),
            "low": forecast.total_low,
            "expected": forecast.total_expected,
            "spike": forecast.total_spike,
        },
        "services": [
            {"id": s.id, "root": s.root, "kind": s.kind, "facts": facts(s.facts)}
            for s in system.services
        ],
        "edges": [
            {"src": e.src, "dst": e.dst, "via": e.via, "evidence": _evidence(e.evidence, ref, sha)}
            for e in system.edges
        ],
        "shared_infra": facts(system.shared_infra),
        "not_analyzed": system.not_analyzed,
        "components": [
            {
                "type": c.type,
                "name": c.name,
                "sizing": c.sizing,
                "reason": c.reason,
                "serves": c.serves,
                "items": c.items,
                "params": c.params,
                "evidence": _evidence(c.evidence, ref, sha),
            }
            for c in run.arch.components
        ],
        "unknowns": run.arch.unknowns,
        "steps": [s.model_dump() for s in run.steps],
        "forecast": {
            "region": forecast.region,
            "lines": [line.model_dump() for line in forecast.lines],
            "groups": _cost_groups(run),
            "assumptions": [a.model_dump() for a in forecast.assumptions],
            "not_priced": forecast.not_priced,
            "not_included": forecast.not_included,
            "price_snapshot": forecast.price_snapshot,
        },
        "traps": [t.model_dump() for t in run.traps],
        "terraform": {
            "files": run.files,
            "checks": [
                {"name": c.name, "status": c.status, "detail": c.detail} for c in run.checks
            ],
            "gaps": run.gaps,
        },
        "plan_md": run.plan_md,
        "forecast_md": run.forecast_md,
    }


def build_zip(run: Run) -> bytes:
    """PLAN.md, FORECAST.md and the Terraform files, in memory."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("PLAN.md", run.plan_md)
        archive.writestr("FORECAST.md", run.forecast_md)
        for name, text in sorted(run.files.items()):
            archive.writestr(f"terraform/{name}", text)
    return buffer.getvalue()
