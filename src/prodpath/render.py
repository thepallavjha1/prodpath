"""Stage 7: render PLAN.md from the architecture, steps and (optionally) LLM summaries.

Pure string building: no model, no network. The only non-deterministic input is the
timestamp, which the caller passes in so tests can pin it.
"""

import hashlib

from prodpath import __version__
from prodpath.iac_check import TerraformReport
from prodpath.models import (
    Architecture,
    Component,
    Evidence,
    Forecast,
    Prefs,
    Step,
    Summaries,
    SystemModel,
    Trap,
)

SHARED_TYPES = {"rds", "elasticache", "documentdb"}
COMPUTE_TYPES = {
    "ecs-service-web",
    "ecs-service-worker",
    "scheduled-task",
    "apprunner",
    "cloudfront",
}
NOT_VERIFIED = [
    "Load and performance: sizing is a default, not a measurement.",
    "Compliance and legal requirements (data residency, audit, PCI/HIPAA and similar).",
    "Account-level controls: organizations, SCPs, guardrails, existing networking.",
    "Real traffic patterns, data growth, and anything that only shows up at runtime.",
    "That the commands run unchanged in your account: placeholders must be filled and "
    "limits/quotas checked.",
    "Security of your application code. This plan covers infrastructure defaults only.",
]


def input_hash(system: SystemModel, prefs: Prefs) -> str:
    material = system.model_dump_json() + prefs.model_dump_json()
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:12]


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _where(evidence: Evidence) -> str:
    return f"{evidence.path}:{evidence.line}" if evidence.line else evidence.path


def _evidence_cell(component: Component) -> str:
    if not component.evidence:
        return "account-level, no code evidence"
    return "<br>".join(f"`{_where(e)}`" for e in component.evidence)


def _deployed_as(service_id: str, arch: Architecture) -> str:
    names = [c.name for c in arch.components if c.type in COMPUTE_TYPES and service_id in c.serves]
    return ", ".join(names) or "not deployed"


def _services_section(system: SystemModel, arch: Architecture, summaries: Summaries | None) -> str:
    purposes = {s.service_id: s.purpose for s in summaries.services} if summaries else {}
    lines = ["| Service | Kind | Root | Purpose | Deployed as |", "|---|---|---|---|---|"]
    for service in system.services:
        purpose = purposes.get(service.id, "(run `prodpath summarize` for a purpose)")
        row = (service.id, service.kind, f"`{service.root}`", _cell(purpose))
        lines.append("| " + " | ".join(row) + f" | {_deployed_as(service.id, arch)} |")
    return "\n".join(lines)


def _architecture_section(arch: Architecture) -> str:
    lines = ["| Component | Type | Sizing | Why | Evidence |", "|---|---|---|---|---|"]
    for c in arch.components:
        cells = (f"`{c.name}`", c.type, _cell(c.sizing), _cell(c.reason), _evidence_cell(c))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _steps_section(steps: list[Step]) -> str:
    out = []
    for number, step in enumerate(steps, start=1):
        out.append(f"### {number}. {step.title}\n\n{step.why}\n")
        if step.commands:
            out.append("```bash\n" + "\n".join(step.commands) + "\n```\n")
        out.append(f"**Verify:** {step.verify}\n")
    return "\n".join(out)


def _risks_section(arch: Architecture, summaries: Summaries | None) -> str:
    risks = []
    for c in arch.components:
        if c.type in SHARED_TYPES and len(c.serves) > 1:
            risks.append(
                f"`{c.name}` is shared by {', '.join(c.serves)}: one outage or heavy query "
                "affects all of them. Split it if you need isolation."
            )
    if summaries:
        for item in summaries.services:
            for claim in item.risks:
                refs = ", ".join(f"`{ref}`" for ref in claim.evidence_ids)
                risks.append(f"{item.service_id}: {claim.text} (model-written; evidence {refs})")
    if not risks:
        return "No specific risks were derived. See the unknowns below."
    return "\n".join(f"- {risk}" for risk in risks)


def _uncertainty_section(
    system: SystemModel, arch: Architecture, summaries: Summaries | None
) -> str:
    heuristic = sum(1 for s in system.services for f in s.facts if f.certainty == "heuristic")
    total = sum(len(s.facts) for s in system.services)
    lines = [
        f"- {heuristic} of {total} extracted facts are heuristic (pattern matches, not parsed).",
        "- All sizing and counts are defaults; there is no traffic data (see unknowns).",
    ]
    if summaries is None:
        lines.append("- No model summaries were used (`.prodpath/summaries.json` not found).")
    else:
        lines.append(f"- Service purposes and some risks are model-written ({summaries.model}).")
    lines.append(f"- Environment assumed: `{arch.environment}`; region: `{arch.region}`.")
    return "\n".join(lines)


def _terraform_section(report: TerraformReport) -> str:
    names = ", ".join(f"`{name}`" for name in report.files)
    lines = [
        f"{len(report.files)} files were written to `.prodpath/out/terraform/`: {names}.",
        "",
        "**Checks run by this tool**",
        "",
    ]
    labels = {"ok": "passed", "fail": "FAILED", "skipped": "not run"}
    for check in report.checks:
        lines.append(f"- {check.name}: {labels[check.status]}: {check.detail}")
    lines += ["", "**Terraform coverage**", ""]
    if report.gaps:
        lines.append("No template exists yet for these planned components (create them yourself):")
        lines += [f"- {gap}" for gap in report.gaps]
    else:
        lines.append("Every planned component has a template.")
    lines += [
        "",
        "`terraform validate` checks syntax and provider schema, not whether the design is right "
        "or safe for your account. Read `terraform plan` before applying.",
    ]
    return "\n".join(lines)


def render_plan(
    system: SystemModel,
    arch: Architecture,
    steps: list[Step],
    prefs: Prefs,
    summaries: Summaries | None,
    generated_at: str,
    terraform: TerraformReport | None = None,
) -> str:
    header = (
        f"<!-- prodpath {__version__} | generated {generated_at} | "
        f"input {input_hash(system, prefs)} -->"
    )
    open_questions = [*arch.unknowns, f"Confirm the AWS region (assumed `{arch.region}`)."]
    not_analyzed = system.not_analyzed or ["nothing was skipped"]
    sections = [
        header,
        "# Production plan",
        f"Target: **{arch.provider.upper()}**, region `{arch.region}`, environment "
        f"`{arch.environment}`. {len(system.services)} services detected, "
        f"{len(arch.components)} components planned.",
        "## Services\n\n" + _services_section(system, arch, summaries),
        "## Architecture\n\n" + _architecture_section(arch),
        "## Steps\n\nCommands use `<PLACEHOLDERS>` for values only you know.\n\n"
        + _steps_section(steps),
        *(["## Terraform\n\n" + _terraform_section(terraform)] if terraform else []),
        "## Risks\n\n" + _risks_section(arch, summaries),
        "## Unknowns and open questions\n\n" + "\n".join(f"- {q}" for q in open_questions),
        "## Not analyzed\n\n" + "\n".join(f"- {n}" for n in not_analyzed),
        "## What this plan is based on\n\n" + _uncertainty_section(system, arch, summaries),
        "## Not verified by this tool\n\n" + "\n".join(f"- {n}" for n in NOT_VERIFIED),
    ]
    return "\n\n".join(sections) + "\n"


def _usd(amount: float) -> str:
    return f"${amount:,.2f}"


def _assumptions_table(forecast: Forecast) -> str:
    lines = ["| Assumption | Value | Unit | Source | Note |", "|---|---|---|---|---|"]
    for a in forecast.assumptions:
        lines.append(f"| `{a.name}` | {a.value:g} | {a.unit} | **{a.source}** | {_cell(a.note)} |")
    return "\n".join(lines)


def _cost_table(forecast: Forecast) -> str:
    lines = [
        "| Component | Dimension | Expected qty | Unit | Unit price | Price ref "
        "| Low | Expected | Spike |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for line in forecast.lines:
        cells = (
            f"`{line.component}`",
            _cell(line.dimension),
            f"{line.qty_expected:,.2f}",
            line.unit,
            f"${line.unit_price:.6g}",
            f"`{line.price_ref}`",
            _usd(line.usd_low),
            _usd(line.usd_expected),
            _usd(line.usd_spike),
        )
        lines.append("| " + " | ".join(cells) + " |")
    totals = (
        "**Total**",
        "",
        "",
        "",
        "",
        "",
        _usd(forecast.total_low),
        _usd(forecast.total_expected),
        _usd(forecast.total_spike),
    )
    lines.append("| " + " | ".join(totals) + " |")
    return "\n".join(lines)


def _drivers_section(forecast: Forecast) -> str:
    by_component: dict[str, float] = {}
    for line in forecast.lines:
        by_component[line.component] = by_component.get(line.component, 0.0) + line.usd_expected
    ranked = sorted(by_component.items(), key=lambda kv: (-kv[1], kv[0]))[:5]
    total = forecast.total_expected or 1.0
    return "\n".join(
        f"{i}. `{name}`: {_usd(cost)} ({cost / total:.0%})"
        for i, (name, cost) in enumerate(ranked, 1)
    )


def _traps_section(traps: list[Trap]) -> str:
    if not traps:
        return "No traps were detected for this architecture."
    lines = []
    for number, trap in enumerate(traps, start=1):
        impact = (
            f"about {_usd(trap.est_monthly_usd_impact)}/month"
            if trap.est_monthly_usd_impact is not None
            else "not priced"
        )
        lines.append(
            f"### {number}. {trap.id} ({trap.severity})\n\n"
            f"**Where:** {trap.where}  \n**Impact:** {impact}\n\n"
            f"**Why it bites:** {trap.why}\n\n**Fix:** {trap.fix}\n"
        )
    return "\n".join(lines)


def forecast_hash(forecast: Forecast, arch: Architecture) -> str:
    material = forecast.model_dump_json() + arch.model_dump_json()
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:12]


def render_forecast(
    arch: Architecture, forecast: Forecast, traps: list[Trap], generated_at: str
) -> str:
    defaults = sum(1 for a in forecast.assumptions if a.source == "default")
    low = next((a.value for a in forecast.assumptions if a.name == "scenario_low"), 0.0)
    spike = next((a.value for a in forecast.assumptions if a.name == "scenario_spike"), 0.0)
    header = (
        f"<!-- prodpath {__version__} | generated {generated_at} | "
        f"input {forecast_hash(forecast, arch)} -->"
    )
    summary = (
        f"Target: **{forecast.provider.upper()}**, region `{forecast.region}`, environment "
        f"`{arch.environment}`.\n\n"
        f"**Expected: about {_usd(forecast.total_expected)} per month**, ranging from "
        f"{_usd(forecast.total_low)} (low) to {_usd(forecast.total_spike)} (spike).\n\n"
        "| Scenario | Traffic vs expected | USD per month |\n|---|---|---|\n"
        f"| Low | {low:g}x | {_usd(forecast.total_low)} |\n"
        f"| Expected | 1x | {_usd(forecast.total_expected)} |\n"
        f"| Spike | {spike:g}x | {_usd(forecast.total_spike)} |\n\n"
        f"{defaults} of {len(forecast.assumptions)} assumptions are defaults, not measurements: "
        "supply a `usage.toml` to replace them with your real numbers."
    )
    not_priced = forecast.not_priced or [
        "nothing: every planned component with a price model was priced"
    ]
    sections = [
        header,
        "# What will this cost me, and what can bite me?",
        summary,
        "## Biggest cost drivers\n\n" + _drivers_section(forecast),
        "## Assumptions\n\nEvery number below depends on these. **Source** says where each came "
        "from: `user` (your usage.toml), `default` (a placeholder), or `inferred` "
        "(from your code).\n\n" + _assumptions_table(forecast),
        "## Cost breakdown\n\nQuantities are monthly (730 hours). Always-on resources do not "
        "change "
        "between scenarios because nothing here autoscales; traffic-driven lines scale with the "
        "scenario multiplier.\n\n" + _cost_table(forecast),
        "## What can bite me\n\nRanked by severity, then estimated monthly impact.\n\n"
        + _traps_section(traps),
        "## Not priced\n\n" + "\n".join(f"- {item}" for item in not_priced),
        "## Not included in any figure\n\n"
        + "\n".join(f"- {item}" for item in forecast.not_included),
        "## What this forecast is based on\n\n"
        f"- Prices: {forecast.price_snapshot}.\n"
        "- On-demand, first paid tier prices only. Every cost line cites its `price_ref` "
        "(`<offer>/<sku>/<rateCode>`) in that public price file.\n"
        "- Quantities come from the architecture and the assumptions above, not from measured "
        "traffic. Treat the range as an order-of-magnitude guide until calibrated against a "
        "real bill.",
    ]
    return "\n\n".join(sections) + "\n"
