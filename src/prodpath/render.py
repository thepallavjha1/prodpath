"""Stage 7: render PLAN.md from the architecture, steps and (optionally) LLM summaries.

Pure string building: no model, no network. The only non-deterministic input is the
timestamp, which the caller passes in so tests can pin it.
"""

import hashlib

from prodpath import __version__
from prodpath.models import (
    Architecture,
    Component,
    Evidence,
    Prefs,
    Step,
    Summaries,
    SystemModel,
)

SHARED_TYPES = {"rds", "elasticache", "documentdb"}
COMPUTE_TYPES = {"ecs-service-web", "ecs-service-worker", "scheduled-task", "apprunner"}
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


def render_plan(
    system: SystemModel,
    arch: Architecture,
    steps: list[Step],
    prefs: Prefs,
    summaries: Summaries | None,
    generated_at: str,
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
        "## Steps\n\nCommands use `<PLACEHOLDERS>` for values only you know. Terraform for these "
        "resources is not generated yet, so these are the by-hand route.\n\n"
        + _steps_section(steps),
        "## Risks\n\n" + _risks_section(arch, summaries),
        "## Unknowns and open questions\n\n" + "\n".join(f"- {q}" for q in open_questions),
        "## Not analyzed\n\n" + "\n".join(f"- {n}" for n in not_analyzed),
        "## What this plan is based on\n\n" + _uncertainty_section(system, arch, summaries),
        "## Not verified by this tool\n\n" + "\n".join(f"- {n}" for n in NOT_VERIFIED),
    ]
    return "\n\n".join(sections) + "\n"
