"""Architecture -> Terraform files, rendered from Jinja2 templates. No LLM, no network.

The context built here is plain dicts and lists so the templates stay readable. Anything the
tool cannot know (certificate, domain, image tags, cron expressions) becomes a required
variable with no default, never a made-up value.
"""

import re
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from prodpath.models import Architecture, Component

TEMPLATE_DIR = Path(__file__).parent / "templates"
COMPUTE_TYPES = {"ecs-service-web", "ecs-service-worker", "scheduled-task"}
GENERATED_TYPES = {
    "tf-state", "iam-github-oidc", "vpc", "ecs-cluster", "alb", "ecr", "rds", "sqs", "sns", "s3",
    "secrets", "log-group", "iam-task-role", *COMPUTE_TYPES,
}  # fmt: skip
DB_PORTS = {"postgres": 5432, "mysql": 3306}
DEFAULT_WEB_PORT = 8080
AZ_COUNT = 2  # subnets and endpoint ENIs per AZ; the network template creates two of each
# File name -> template. Empty renders are skipped, so each template guards itself.
TEMPLATES = [
    "versions.tf", "backend.tf", "main.tf", "variables.tf", "network.tf", "ecr.tf", "iam.tf",
    "secrets.tf", "ecs.tf", "alb.tf", "rds.tf", "elasticache.tf", "messaging.tf", "s3.tf",
    "scheduler.tf", "github_oidc.tf", "outputs.tf", "terraform.tfvars.example", "README.md",
]  # fmt: skip

# Autoescape is off on purpose: the output is HCL, not HTML.
_ENV = Environment(  # noqa: S701
    loader=FileSystemLoader(TEMPLATE_DIR),
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
    keep_trailing_newline=True,
    autoescape=False,
)


def tf_id(name: str) -> str:
    """A valid Terraform identifier from a service id or secret name."""
    cleaned = re.sub(r"[^a-zA-Z0-9_]", "_", name).lower()
    return cleaned if cleaned[:1].isalpha() or cleaned[:1] == "_" else f"s_{cleaned}"


def interface_endpoints(has_secrets: bool) -> list[str]:
    """Interface VPC endpoints the network template creates. Also used by the cost model."""
    return ["ecr.api", "ecr.dkr", "logs", *(["secretsmanager"] if has_secrets else [])]


def iac_gaps(arch: Architecture) -> list[str]:
    """Components that have no template yet. Listed in PLAN.md, never silently skipped."""
    gaps = []
    for c in arch.components:
        if c.type not in GENERATED_TYPES and c.type != "elasticache":
            gaps.append(f"{c.name} ({c.type})")
        elif c.type == "elasticache" and c.name != "elasticache-redis":
            gaps.append(f"{c.name} ({c.type})")
    return gaps


def _item(component: Component, key: str) -> str | None:
    for item in component.items:
        if item.startswith(key + ":"):
            return item.split(":", 1)[1]
    return None


def _serving(arch: Architecture, service_id: str, *types: str) -> list[Component]:
    return [c for c in arch.components if c.type in types and service_id in c.serves]


def _service_context(arch: Architecture, c: Component) -> dict[str, Any]:
    sid = c.serves[0]
    kind = {"ecs-service-web": "web", "ecs-service-worker": "worker", "scheduled-task": "cron"}[
        c.type
    ]
    secret_names = [n for comp in _serving(arch, sid, "secrets") for n in comp.items]
    port = _item(c, "port")
    return {
        "id": sid,
        "tf": tf_id(sid),
        "kind": kind,
        "port": int(port) if port else DEFAULT_WEB_PORT,
        "port_assumed": kind == "web" and port is None,
        "health": _item(c, "health") or "/",
        "health_assumed": kind == "web" and _item(c, "health") is None,
        "tg_prefix": (re.sub(r"[^a-z0-9]", "", sid.lower())[:5].ljust(5, "x") + "-"),
        "cpu": int(c.params["cpu"]),
        "memory": int(c.params["memory"]),
        "desired": int(c.params["desired_count"]),
        "env_names": [i.removeprefix("env:") for i in c.items if i.startswith("env:")],
        "secrets": [{"name": n, "tf": tf_id(f"{sid}_{n}")} for n in secret_names],
        "buckets": [tf_id(b.name) for b in _serving(arch, sid, "s3")],
        "uses_sqs": bool(_serving(arch, sid, "sqs")),
        "uses_sns": bool(_serving(arch, sid, "sns")),
    }


def build_context(arch: Architecture) -> dict[str, Any]:
    compute = [c for c in arch.components if c.type in COMPUTE_TYPES]
    services = sorted((_service_context(arch, c) for c in compute), key=lambda s: s["id"])
    tf_by_id = {s["id"]: s["tf"] for s in services}

    def users(component: Component) -> list[str]:
        return [tf_by_id[sid] for sid in component.serves if sid in tf_by_id]

    types = {c.type for c in arch.components}
    rds = [
        {
            "engine": c.params["engine"],
            "tf": tf_id(c.params["engine"]),
            "instance_class": c.params["instance_class"],
            "storage": int(c.params["allocated_storage"]),
            "multi_az": c.params["multi_az"],
            "port": DB_PORTS[c.params["engine"]],
            "users": users(c),
        }
        for c in arch.components
        if c.type == "rds"
    ]
    redis = next(
        (
            {**c.params, "users": users(c), "clusters": int(c.params["num_cache_clusters"])}
            for c in arch.components
            if c.name == "elasticache-redis"
        ),
        None,
    )
    messaging = {
        kind: next(({"users": users(c)} for c in arch.components if c.type == kind), None)
        for kind in ("sqs", "sns")
    }
    buckets = [
        {"tf": tf_id(c.name), "service": c.serves[0], "prefix": f"{c.serves[0]}-"}
        for c in arch.components
        if c.type == "s3"
    ]
    return {
        "region": arch.region,
        "environment": arch.environment,
        "is_prod": arch.environment == "prod",
        "services": services,
        "web_services": [s for s in services if s["kind"] == "web"],
        "cron_services": [s for s in services if s["kind"] == "cron"],
        "has_vpc": "vpc" in types,
        "has_cluster": "ecs-cluster" in types,
        "has_alb": "alb" in types,
        "has_secrets": any(s["secrets"] for s in services),
        "endpoints": interface_endpoints(any(s["secrets"] for s in services)),
        "has_github": "iam-github-oidc" in types,
        "has_ecr": "ecr" in types,
        "rds": rds,
        "redis": redis,
        "sqs": messaging["sqs"],
        "sns": messaging["sns"],
        "buckets": buckets,
    }


def _tidy(text: str) -> str:
    """Strip trailing spaces and collapse blank-line runs so output is stable and compact."""
    text = "\n".join(line.rstrip() for line in text.splitlines())
    return re.sub(r"\n{3,}", "\n\n", text).strip("\n") + "\n"


def render_iac(arch: Architecture) -> dict[str, str]:
    if not arch.components:
        return {}
    context = build_context(arch)
    files = {}
    for name in TEMPLATES:
        rendered = _tidy(_ENV.get_template(name + ".j2").render(**context))
        if rendered.strip():
            files[name] = rendered
    return files
