"""Facts -> AWS components. Plain rules, each with a `reason` that is printed in the plan.

Defaults here are starting points, not measurements: nothing in the code says how much
traffic the system gets, and the plan says so (see the `unknowns` list).
"""

import re
from collections.abc import Callable
from dataclasses import dataclass, field

from prodpath.models import Architecture, Component, Evidence, Fact, Prefs, Service, SystemModel

DEPLOYABLE_KINDS = {"web", "worker", "cron"}
MAX_EVIDENCE = 3
# Env var names that look like credentials or connection strings. URLs are included on
# purpose: they often embed passwords, and we never see values to check.
SECRET_NAME = re.compile(
    r"(PASSWORD|PASSWD|SECRET|TOKEN|API_?KEY|PRIVATE|CREDENTIAL|_URL$|_URI$|_DSN$)", re.IGNORECASE
)
TYPE_ORDER = [
    "tf-state", "iam-github-oidc", "vpc", "ecs-cluster", "alb", "ecr", "rds", "documentdb",
    "dynamodb", "elasticache", "sqs", "sns", "amazon-mq", "msk", "s3", "secrets", "log-group",
    "iam-task-role", "apprunner", "ecs-service-web", "ecs-service-worker", "scheduled-task",
]  # fmt: skip


@dataclass
class Context:
    system: SystemModel
    prefs: Prefs
    deployable: list[Service]
    unknowns: list[str] = field(default_factory=list)

    @property
    def is_prod(self) -> bool:
        return self.prefs.environment == "prod"


Rule = Callable[[Context], list[Component]]


def _facts(service: Service, kind: str, values: set[str] | None = None) -> list[Fact]:
    return [f for f in service.facts if f.kind == kind and (values is None or f.value in values)]


def _evidence(facts: list[Fact]) -> list[Evidence]:
    return [f.evidence[0] for f in facts][:MAX_EVIDENCE]


def _users(ctx: Context, kind: str, values: set[str]) -> list[tuple[Service, list[Fact]]]:
    found = [(s, _facts(s, kind, values)) for s in ctx.deployable]
    return [(s, facts) for s, facts in found if facts]


def _component(
    ctx_type: str, name: str, sizing: str, reason: str, users: list[tuple[Service, list[Fact]]]
) -> Component:
    return Component(
        type=ctx_type,
        name=name,
        sizing=sizing,
        reason=reason,
        serves=sorted(s.id for s, _ in users),
        evidence=_evidence([f for _, facts in users for f in facts]),
    )


def _uses_app_runner(ctx: Context) -> bool:
    """One web service that needs no VPC-bound resource: App Runner is simpler than Fargate."""
    if len(ctx.deployable) != 1 or ctx.deployable[0].kind != "web":
        return False
    needs_vpc = {"datastore", "cache", "queue"}
    return not any(f.kind in needs_vpc for f in ctx.deployable[0].facts)


ANCHOR_KINDS = ("port", "framework", "worker", "schedule", "runtime", "health_endpoint")


def _anchor(service: Service) -> list[Fact]:
    """The fact that best shows what kind of thing this service is (not just its first fact)."""
    for kind in ANCHOR_KINDS:
        found = _facts(service, kind)
        if found:
            return found[:1]
    return service.facts[:1]


def _service_evidence(services: list[Service]) -> list[Evidence]:
    return [f.evidence[0] for s in services for f in _anchor(s)][:MAX_EVIDENCE]


def rule_foundation(ctx: Context) -> list[Component]:
    everyone = [s.id for s in ctx.deployable]
    components = [
        Component(
            type="tf-state",
            name="tf-state",
            sizing="1 S3 bucket (versioned, encrypted) + 1 lock table",
            reason="Remote state with locking keeps Terraform safe once more than one person or "
            "pipeline applies changes (SECURITY.md section 5).",
            serves=[],
        ),
        Component(
            type="iam-github-oidc",
            name="github-oidc-role",
            sizing="1 IAM role trusted by GitHub Actions via OIDC",
            reason="CI/CD deploys by assuming a role, "
            "so no long-lived AWS keys are stored in GitHub.",
            serves=everyone,
        ),
    ]
    if _uses_app_runner(ctx):
        return components
    return components + [
        Component(
            type="vpc",
            name="vpc",
            sizing="2 AZs, public + private subnets, S3 and ECR VPC endpoints",
            reason="Containers and data stores run in private subnets; endpoints avoid NAT data "
            "charges for image pulls and S3 traffic.",
            serves=everyone,
            evidence=_service_evidence(ctx.deployable),
        ),
        Component(
            type="ecs-cluster",
            name="ecs-cluster",
            sizing="1 Fargate-only cluster",
            reason="One cluster runs every container service; Fargate means no servers to patch.",
            serves=everyone,
            evidence=_service_evidence(ctx.deployable),
        ),
    ]


def _port_items(service: Service, ctx: Context) -> list[str]:
    ports = sorted({f.value for f in _facts(service, "port")}, key=int)
    items = [f"port:{ports[0]}"] if ports else []
    if not ports and service.kind == "web":
        ctx.unknowns.append(f"{service.id}: no listening port found; set the container port.")
    items += [f"health:{f.value}" for f in _facts(service, "health_endpoint")][:1]
    return items


def rule_compute(ctx: Context) -> list[Component]:
    components: list[Component] = []
    tasks = "2 tasks" if ctx.is_prod else "1 task"
    app_runner = _uses_app_runner(ctx)
    for service in ctx.deployable:
        anchor = [(service, _anchor(service))]
        components.append(
            _component(
                "ecr",
                f"ecr-{service.id}",
                "1 repository, scan on push",
                f"Stores the container image for {service.id}.",
                anchor,
            )
        )
        items = _port_items(service, ctx)
        if app_runner:
            comp = _component(
                "apprunner",
                f"apprunner-{service.id}",
                "0.5 vCPU / 1 GB (default)",
                "A single web service with no database or cache needs no VPC; App Runner "
                "gives HTTPS and scaling with the least setup.",
                anchor,
            )
        elif service.kind == "web":
            comp = _component(
                "ecs-service-web",
                f"ecs-svc-{service.id}",
                f"Fargate 0.5 vCPU / 1 GB, {tasks} (default)",
                "Stateless HTTP container behind the shared load balancer.",
                anchor,
            )
        elif service.kind == "worker":
            comp = _component(
                "ecs-service-worker",
                f"ecs-svc-{service.id}",
                f"Fargate 0.25 vCPU / 0.5 GB, {tasks} (default)",
                "Background worker: a Fargate service with no load balancer.",
                anchor,
            )
        else:
            comp = _component(
                "scheduled-task",
                f"cron-{service.id}",
                "Fargate 0.25 vCPU / 0.5 GB per run",
                "Scheduled job: EventBridge Scheduler starts a one-off Fargate task.",
                anchor,
            )
            ctx.unknowns.append(
                f"{service.id}: the schedule was not extracted; set the cron expression yourself."
            )
        comp.items = items
        components.append(comp)
        components.append(
            _component(
                "log-group",
                f"logs-{service.id}",
                "retention 30 days",
                "CloudWatch logs with an explicit retention so they cannot grow forever.",
                anchor,
            )
        )
    web = [s for s in ctx.deployable if s.kind == "web"]
    if web and not app_runner:
        components.append(
            Component(
                type="alb",
                name="alb",
                sizing="1 Application Load Balancer, host/path routing",
                reason="One shared load balancer for all web services "
                "avoids paying for one per service.",
                serves=sorted(s.id for s in web),
                evidence=_service_evidence(web),
            )
        )
        ctx.unknowns.append(
            "Domain name and ACM certificate are needed for HTTPS on the load balancer."
        )
    return components


def rule_datastores(ctx: Context) -> list[Component]:
    multi_az = "Multi-AZ" if ctx.is_prod else "single-AZ"
    instance = "db.t4g.small" if ctx.is_prod else "db.t4g.micro"
    components = []
    for engine in ("postgres", "mysql"):
        users = _users(ctx, "datastore", {engine})
        if users:
            reason = (
                f"{engine} is a managed relational database on RDS. One instance serves every "
                "service that uses it (give each its own database and user)."
            )
            components.append(
                _component(
                    "rds",
                    f"rds-{engine}",
                    f"{instance}, 20 GB gp3, {multi_az}, backups on",
                    reason,
                    users,
                )
            )
    for engine, comp_type, label in (
        ("mongodb", "documentdb", "Amazon DocumentDB (MongoDB-compatible)"),
        ("dynamodb", "dynamodb", "DynamoDB on-demand tables"),
    ):
        users = _users(ctx, "datastore", {engine})
        if users:
            components.append(
                _component(
                    comp_type,
                    f"{comp_type}",
                    "default sizing",
                    f"Code uses {engine}: {label}.",
                    users,
                )
            )
            if engine == "mongodb":
                ctx.unknowns.append(
                    "MongoDB: DocumentDB is not fully MongoDB-compatible; confirm the "
                    "driver features you use, or consider MongoDB Atlas."
                )
    return components


def rule_cache_and_queues(ctx: Context) -> list[Component]:
    components = []
    redis_users = (
        _users(ctx, "cache", {"redis"})
        + _users(ctx, "queue", {"bull", "bullmq"})
        + _users(ctx, "worker", {"rq"})
    )
    by_id: dict[str, tuple[Service, list[Fact]]] = {}
    for service, facts in redis_users:
        by_id.setdefault(service.id, (service, []))[1].extend(facts)
    if by_id:
        ctx.unknowns.append(
            "Redis: in-transit encryption is on, so clients must connect with TLS (rediss://); "
            "check each service's Redis client settings."
        )
        node = "2 nodes, Multi-AZ" if ctx.is_prod else "1 node"
        components.append(
            _component(
                "elasticache",
                "elasticache-redis",
                f"cache.t4g.micro, {node}",
                "Redis (cache, Celery/BullMQ/RQ broker) on ElastiCache.",
                list(by_id.values()),
            )
        )
    memcached = _users(ctx, "cache", {"memcached"})
    if memcached:
        components.append(
            _component(
                "elasticache",
                "elasticache-memcached",
                "cache.t4g.micro, 1 node",
                "Memcached on ElastiCache.",
                memcached,
            )
        )
    sqs = _users(ctx, "queue", {"sqs"})
    if sqs:
        components.append(
            _component(
                "sqs",
                "sqs",
                "standard queue + dead-letter queue",
                "Code uses SQS; queue names were not extracted.",
                sqs,
            )
        )
        ctx.unknowns.append(
            "SQS: queue names and visibility timeouts were not extracted; set them per consumer."
        )
    sns = _users(ctx, "queue", {"sns"})
    if sns:
        components.append(_component("sns", "sns", "standard topic", "Code uses SNS.", sns))
    rabbit = _users(ctx, "queue", {"rabbitmq"})
    if rabbit:
        components.append(
            _component(
                "amazon-mq",
                "amazon-mq-rabbitmq",
                "mq.t3.micro single instance (default)",
                "Code uses RabbitMQ: Amazon MQ runs it managed.",
                rabbit,
            )
        )
    kafka = _users(ctx, "queue", {"kafka"})
    if kafka:
        components.append(
            _component(
                "msk",
                "msk-kafka",
                "smallest provisioned cluster (default)",
                "Code uses Kafka: Amazon MSK. It is one of the costlier pieces; "
                "confirm Kafka is really required.",
                kafka,
            )
        )
    for service, _ in _users(ctx, "queue", {"kombu"}):
        ctx.unknowns.append(
            f"{service.id}: kombu is used but the broker was not detected; "
            "decide Redis, SQS or RabbitMQ."
        )
    for service, _ in _users(ctx, "worker", {"celery"}):
        if not (redis_users or sqs or rabbit):
            ctx.unknowns.append(f"{service.id}: Celery is used but no broker was detected.")
    return components


def rule_storage_and_secrets(ctx: Context) -> list[Component]:
    components = []
    for service in ctx.deployable:
        buckets = _facts(service, "object_store")
        if buckets:
            components.append(
                _component(
                    "s3",
                    f"s3-{service.id}",
                    "private bucket, encryption on, versioning on",
                    "Code uses object storage (S3). Bucket names were not extracted.",
                    [(service, buckets)],
                )
            )
        names = sorted({f.value for f in _facts(service, "env_var") if SECRET_NAME.search(f.value)})
        if names:
            comp = _component(
                "secrets",
                f"secrets-{service.id}",
                f"{len(names)} secret slot{'' if len(names) == 1 else 's'}, no values",
                "These variables look like credentials or connection strings. Slots are "
                "created empty; set values yourself, out of band.",
                [(service, [f for f in _facts(service, "env_var") if f.value in names])],
            )
            comp.items = names
            components.append(comp)
        components.append(
            _component(
                "iam-task-role",
                f"role-{service.id}",
                "least-privilege task role",
                f"{service.id} gets its own role limited to the resources it uses.",
                [(service, _anchor(service))],
            )
        )
        if _facts(service, "local_state"):
            ctx.unknowns.append(
                f"{service.id}: writes local files; container disk is ephemeral. "
                "Move that state to S3 or a database before relying on it."
            )
    return components


def _fill_params(ctx: Context, components: list[Component]) -> None:
    """Machine-readable sizing for the Terraform templates; defaults, not measurements."""
    by_id = {s.id: s for s in ctx.deployable}
    desired = "2" if ctx.is_prod else "1"
    for c in components:
        if c.type in {"ecs-service-web", "ecs-service-worker", "scheduled-task"}:
            web = c.type == "ecs-service-web"
            c.params = {
                "cpu": "512" if web else "256",
                "memory": "1024" if web else "512",
                "desired_count": "1" if c.type == "scheduled-task" else desired,
            }
            names = {f.value for f in _facts(by_id[c.serves[0]], "env_var")}
            c.items += [f"env:{n}" for n in sorted(names) if not SECRET_NAME.search(n)]
        elif c.type == "rds":
            c.params = {
                "engine": c.name.removeprefix("rds-"),
                "instance_class": "db.t4g.small" if ctx.is_prod else "db.t4g.micro",
                "allocated_storage": "20",
                "multi_az": "true" if ctx.is_prod else "false",
            }
        elif c.name == "elasticache-redis":
            c.params = {"node_type": "cache.t4g.micro", "num_cache_clusters": desired}
        elif c.type == "log-group":
            c.params = {"retention_days": "30"}


RULES: list[Rule] = [
    rule_foundation,
    rule_compute,
    rule_datastores,
    rule_cache_and_queues,
    rule_storage_and_secrets,
]


def choose_architecture(system: SystemModel, prefs: Prefs) -> Architecture:
    ctx = Context(
        system=system,
        prefs=prefs,
        deployable=sorted(
            (s for s in system.services if s.kind in DEPLOYABLE_KINDS and s.facts),
            key=lambda s: s.id,
        ),
    )
    for service in system.services:
        if service.kind == "unknown" and service.facts:
            ctx.unknowns.append(
                f"{service.id}: could not be classified (web, worker or cron); not planned."
            )
    components: list[Component] = []
    if ctx.deployable:
        for rule in RULES:
            components += rule(ctx)
        ctx.unknowns.append(
            "Traffic and data volume are unknown: all sizing is a default starting point."
        )
    else:
        ctx.unknowns.append(
            "No deployable services with facts were found; there is nothing to plan."
        )
    _fill_params(ctx, components)
    order = {t: i for i, t in enumerate(TYPE_ORDER)}
    components.sort(key=lambda c: (order.get(c.type, len(order)), c.name))
    return Architecture(
        provider="aws",
        region=prefs.region,
        environment=prefs.environment,
        components=components,
        unknowns=sorted(dict.fromkeys(ctx.unknowns)),
    )
