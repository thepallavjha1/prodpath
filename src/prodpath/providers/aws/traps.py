"""Trap registry: things that make the bill or the system surprising.

Each trap is one function from a context to an optional `Trap`. A trap fires only when its
condition is visible in the architecture or code analysis; it carries a fix and, when the
forecast allows, an estimated monthly impact computed from the snapshot (never invented).
"""

from collections.abc import Callable
from dataclasses import dataclass

from prodpath.models import Architecture, Forecast, SystemModel, Trap
from prodpath.providers.aws.pricing import PriceBook

SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}
HIGH_SHARE, MEDIUM_SHARE = 0.25, 0.10  # share of the total that makes a cost trap high / medium


@dataclass
class TrapContext:
    arch: Architecture
    system: SystemModel
    forecast: Forecast
    prices: PriceBook

    def cost(
        self, *, component: str = "", dimension: str = "", scenario: str = "expected"
    ) -> float:
        total = 0.0
        for line in self.forecast.lines:
            if line.component.startswith(component) and dimension in line.dimension:
                total += getattr(line, f"usd_{scenario}")
        return total

    def share(self, amount: float, scenario: str = "expected") -> float:
        total = getattr(self.forecast, f"total_{scenario}")
        return amount / total if total else 0.0

    def components(self, *types: str) -> list:  # type: ignore[type-arg]
        return [c for c in self.arch.components if c.type in types]


TrapFn = Callable[[TrapContext], Trap | None]


def _severity_by_share(share: float) -> str:
    return "high" if share >= HIGH_SHARE else "medium" if share >= MEDIUM_SHARE else "low"


def trap_no_outbound_path(ctx: TrapContext) -> Trap | None:
    if not ctx.components("vpc"):
        return None
    reasons = []
    callers = [
        s.id
        for s in ctx.system.services
        if any(f.kind == "external_call" and f.value == "http-client" for f in s.facts)
    ]
    if callers:
        reasons.append(f"{', '.join(callers)} make outbound HTTP calls")
    edges = sorted({f"{e.src}->{e.dst}" for e in ctx.system.edges if e.via == "http"})
    if edges:
        reasons.append(
            f"services call each other by URL ({', '.join(edges)}), "
            "i.e. through the public load balancer"
        )
    if ctx.components("sqs", "sns"):
        reasons.append("SQS/SNS have no VPC endpoint in the generated network")
    if not reasons:
        return None
    return Trap(
        id="no-outbound-path",
        severity="high",
        where="network.tf (enable_nat_gateway = false by default)",
        why="Private tasks have no route to the internet or to AWS APIs that lack an endpoint: "
        + "; ".join(reasons)
        + ". Those calls will time out in production.",
        fix="Either set enable_nat_gateway = true (a NAT gateway bills per hour and per GB "
        "processed; its price is not in this forecast), add VPC endpoints for the AWS services "
        "you use, or route service-to-service calls through an internal address.",
        est_monthly_usd_impact=None,
    )


def trap_interface_endpoints(ctx: TrapContext) -> Trap | None:
    fixed = ctx.cost(component="vpc-endpoints", dimension="interface endpoints")
    if not fixed:
        return None
    return Trap(
        id="interface-endpoint-fixed-cost",
        severity=_severity_by_share(ctx.share(fixed)),
        where="network.tf (aws_vpc_endpoint.interface)",
        why="Interface VPC endpoints bill for every AZ-hour whether or not traffic flows. For a "
        "small system this fixed cost can exceed the compute it supports.",
        fix="Keep only the endpoints you need, run one AZ in non-production, or compare against a "
        "NAT gateway for your traffic before deciding.",
        est_monthly_usd_impact=round(fixed, 2),
    )


def trap_log_ingestion(ctx: TrapContext) -> Trap | None:
    expected = ctx.cost(dimension="log ingestion")
    if not expected:
        return None
    spike = ctx.cost(dimension="log ingestion", scenario="spike")
    return Trap(
        id="log-ingestion",
        severity=_severity_by_share(ctx.share(spike, "spike")),
        where="ecs.tf (aws_cloudwatch_log_group)",
        why="CloudWatch bills every GB of logs ingested, and ingestion grows with traffic and "
        f"log verbosity. At the spike scenario ingestion alone is about ${spike:,.2f}/month.",
        fix="Log at INFO or above in production, do not log request bodies, sample noisy lines, "
        "and keep retention short (set to 30 days here).",
        est_monthly_usd_impact=round(expected, 2),
    )


def trap_public_ipv4(ctx: TrapContext) -> Trap | None:
    cost = ctx.cost(component="alb", dimension="public IPv4")
    if not cost:
        return None
    return Trap(
        id="public-ipv4",
        severity="low",
        where="alb.tf (aws_lb.main)",
        why="Every public IPv4 address bills per hour; an internet-facing load balancer uses one "
        "per AZ.",
        fix="Accept it for the one shared load balancer; never add a load balancer per service.",
        est_monthly_usd_impact=round(cost, 2),
    )


def trap_internet_egress(ctx: TrapContext) -> Trap | None:
    expected = ctx.cost(component="internet-egress")
    if not expected:
        return None
    spike = ctx.cost(component="internet-egress", scenario="spike")
    return Trap(
        id="internet-egress",
        severity=_severity_by_share(ctx.share(spike, "spike")),
        where="alb.tf / every web service",
        why="Data transferred out to the internet is billed per GB and scales with traffic and "
        f"response size. At the spike scenario it is about ${spike:,.2f}/month.",
        fix="Compress responses, cache at a CDN, and avoid returning large payloads by default.",
        est_monthly_usd_impact=round(expected, 2),
    )


def trap_no_autoscaling(ctx: TrapContext) -> Trap | None:
    web = ctx.components("ecs-service-web")
    if not web:
        return None
    counts = ", ".join(f"{c.serves[0]}={c.params['desired_count']}" for c in web)
    return Trap(
        id="no-autoscaling",
        severity="medium",
        where="ecs.tf (aws_ecs_service desired_count)",
        why=f"Task counts are fixed ({counts}) and nothing scales them. A traffic spike can "
        "saturate the tasks, and quiet periods still pay for full capacity.",
        fix="Add aws_appautoscaling_target and a target-tracking policy on CPU or request count "
        "per service, with sensible minimum and maximum counts.",
        est_monthly_usd_impact=None,
    )


def trap_redis_replica(ctx: TrapContext) -> Trap | None:
    for c in ctx.components("elasticache"):
        nodes = int(c.params.get("num_cache_clusters", "1"))
        if c.name == "elasticache-redis" and nodes > 1:
            line_cost = ctx.cost(component=c.name)
            return Trap(
                id="redis-replica",
                severity="low",
                where="elasticache.tf (num_cache_clusters)",
                why=f"{nodes} Redis nodes means paying for {nodes - 1} replica(s) for failover.",
                fix="Use one node if Redis is only a rebuildable cache; keep replicas if it is a "
                "broker or holds data you cannot lose.",
                est_monthly_usd_impact=round(line_cost * (nodes - 1) / nodes, 2),
            )
    return None


def trap_multi_az_nonprod(ctx: TrapContext) -> Trap | None:
    if ctx.arch.environment == "prod":
        return None
    multi = [c for c in ctx.components("rds") if c.params.get("multi_az") == "true"]
    if not multi:
        return None
    extra: float | None = 0.0
    for c in multi:
        engine, klass = c.params["engine"], c.params["instance_class"]
        single = ctx.prices.get(f"rds.instance.{engine}.{klass}.single_az")
        double = ctx.prices.get(f"rds.instance.{engine}.{klass}.multi_az")
        storage_single = ctx.prices.get(f"rds.storage.gp3.single_az.{engine}")
        storage_double = ctx.prices.get(f"rds.storage.gp3.multi_az.{engine}")
        hours = next(
            (
                line.qty_expected
                for line in ctx.forecast.lines
                if line.component == c.name and "instance hours" in line.dimension
            ),
            None,
        )
        if hours is None or None in (single, double, storage_single, storage_double):
            extra = None  # cannot compute the difference without both prices: say so, do not guess
            break
        assert single and double and storage_single and storage_double
        gigabytes = float(c.params["allocated_storage"])
        extra = (extra or 0.0) + (double.usd - single.usd) * hours
        extra += (storage_double.usd - storage_single.usd) * gigabytes
    return Trap(
        id="multi-az-rds-in-nonprod",
        severity="medium",
        where="rds.tf (multi_az)",
        why="Multi-AZ roughly doubles database cost and is rarely needed outside production.",
        fix="Set multi_az = false for non-production environments.",
        est_monthly_usd_impact=None if extra is None else round(extra, 2),
    )


def trap_container_insights(ctx: TrapContext) -> Trap | None:
    if not ctx.components("ecs-cluster"):
        return None
    return Trap(
        id="container-insights",
        severity="low",
        where="ecs.tf (aws_ecs_cluster.main, containerInsights = enabled)",
        why="Container Insights publishes extra metrics and log events that are billed separately "
        "and are not in this forecast.",
        fix="Set the setting to disabled until you need the dashboards, or budget for it.",
        est_monthly_usd_impact=None,
    )


def trap_cross_az(ctx: TrapContext) -> Trap | None:
    multi_task = any(
        int(c.params.get("desired_count", "1")) > 1
        for c in ctx.components("ecs-service-web", "ecs-service-worker")
    )
    has_data = bool(ctx.components("rds", "elasticache"))
    if ctx.arch.environment != "prod" or not (multi_task and has_data):
        return None
    return Trap(
        id="cross-az-traffic",
        severity="low",
        where="ecs.tf / rds.tf / elasticache.tf",
        why="Tasks, load balancer nodes and data store replicas spread across two AZs; traffic "
        "that crosses AZs is billed in both directions and is not in this forecast.",
        fix="Keep chatty paths within one AZ where you can; watch inter-AZ bytes in Cost Explorer.",
        est_monthly_usd_impact=None,
    )


TRAPS: list[TrapFn] = [
    trap_no_outbound_path, trap_interface_endpoints, trap_log_ingestion, trap_public_ipv4,
    trap_internet_egress, trap_no_autoscaling, trap_redis_replica, trap_multi_az_nonprod,
    trap_container_insights, trap_cross_az,
]  # fmt: skip


def find_traps(ctx: TrapContext) -> list[Trap]:
    """Run every trap; rank by severity, then estimated impact (largest first), then id."""
    found = [t for fn in TRAPS if (t := fn(ctx)) is not None]
    return sorted(
        found,
        key=lambda t: (
            SEVERITY_ORDER[t.severity],
            -(t.est_monthly_usd_impact or 0.0),
            t.id,
        ),
    )
