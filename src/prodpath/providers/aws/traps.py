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


def _severity_by_share(share: float, high: float = HIGH_SHARE, medium: float = MEDIUM_SHARE) -> str:
    return "high" if share >= high else "medium" if share >= medium else "low"


def _budget(ctx: TrapContext) -> bool:
    return any(c.params.get("mode") == "budget" for c in ctx.components("vpc"))


def trap_no_outbound_path(ctx: TrapContext) -> Trap | None:
    if not ctx.components("vpc") or _budget(ctx):  # budget tasks have public IPs: outbound works
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


def trap_public_task_addresses(ctx: TrapContext) -> Trap | None:
    if not _budget(ctx):
        return None
    tasks = sorted(
        {
            s
            for c in ctx.components("ecs-service-web", "ecs-service-worker", "scheduled-task")
            for s in c.serves
        }
    )
    return Trap(
        id="public-task-addresses",
        severity="medium",
        where="ecs.tf (assign_public_ip = true)",
        why=f"Budget mode gives every task of {', '.join(tasks)} a public IPv4 address so it can "
        "pull images and call AWS without endpoints or NAT. Only the load balancer security group "
        "may reach them, so one wrong security group rule would expose a task directly.",
        fix="Keep the task security group limited to the load balancer, or leave budget mode "
        "once the endpoint cost is acceptable.",
        est_monthly_usd_impact=round(ctx.cost(component="task-public-ips"), 2),
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
    expected = ctx.cost(dimension="data transfer out")
    if not expected:
        return None
    spike = ctx.cost(dimension="data transfer out", scenario="spike")
    return Trap(
        id="internet-egress",
        severity=_severity_by_share(ctx.share(spike, "spike")),
        where="alb.tf / static_site.tf (every service that serves users)",
        why="Data transferred out to the internet is billed per GB and scales with traffic and "
        f"response size. At the spike scenario it is about ${spike:,.2f}/month.",
        fix="Compress responses, cache at a CDN, and avoid returning large payloads by default.",
        est_monthly_usd_impact=round(expected, 2),
    )


def _hours(ctx: TrapContext) -> float:
    return next((a.value for a in ctx.forecast.assumptions if a.name == "hours_per_month"), 730.0)


def trap_autoscaling_max_cost(ctx: TrapContext) -> Trap | None:
    """Extra monthly spend if every scalable service ran at its maximum task count all month."""
    extra, listed = 0.0, []
    for scaling in ctx.components("autoscaling"):
        sid = scaling.serves[0]
        service = next(
            (
                c
                for c in ctx.components("ecs-service-web", "ecs-service-worker")
                if c.serves == [sid]
            ),
            None,
        )
        if service is None:
            continue
        vcpu_hours = int(service.params["cpu"]) / 1024 * _hours(ctx)
        lines = [ln for ln in ctx.forecast.lines if ln.component == service.name]
        spend = sum(ln.usd_expected for ln in lines)
        vcpu_line = next((ln for ln in lines if ln.dimension == "vCPU-hours"), None)
        if vcpu_line is None or not vcpu_line.qty_expected:
            continue
        tasks = vcpu_line.qty_expected / vcpu_hours
        maximum = int(scaling.params["max_count"])
        extra += max(0.0, (maximum - tasks) * spend / tasks)
        listed.append(f"{sid} up to {maximum} tasks")
    if not listed:
        return None
    return Trap(
        id="autoscaling-max-cost",
        severity=_severity_by_share(ctx.share(extra), high=1.0, medium=HIGH_SHARE),
        where="autoscaling.tf (var.service_scaling max_count)",
        why=f"Services scale out on CPU ({'; '.join(listed)}). Held at those maximums all month "
        f"they would cost about ${extra:,.2f} more than the expected forecast. A traffic spike, "
        "a retry storm or a slow dependency can push a service there.",
        fix="Set max_count to what you are willing to pay for, alarm on running task count, and "
        "load-test one task to replace the default rps_per_task assumption with a real number.",
        est_monthly_usd_impact=round(extra, 2),
    )


def trap_alarm_subscription(ctx: TrapContext) -> Trap | None:
    if not ctx.components("alarms"):
        return None
    return Trap(
        id="alarm-subscription-unconfirmed",
        severity="medium",
        where="alarms.tf (aws_sns_topic_subscription.alerts_email)",
        why="AWS sends a confirmation e-mail to alert_email when the subscription is created. "
        "Until someone clicks the link, every alarm fires into a topic with no listeners and "
        "nobody is told that something is wrong.",
        fix="Apply, open the confirmation e-mail immediately, and test with "
        "`aws cloudwatch set-alarm-state` on one alarm. Consider a shared mailbox so alerts do "
        "not depend on one person.",
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


def trap_cloudfront_certificate(ctx: TrapContext) -> Trap | None:
    sites = ctx.components("cloudfront")
    if not sites:
        return None
    names = ", ".join(c.serves[0] for c in sites)
    return Trap(
        id="cloudfront-certificate-region",
        severity="medium",
        where="variables.tf (site_certificate_arn), static_site.tf",
        why=f"CloudFront only accepts ACM certificates from us-east-1, whatever region the rest of "
        f"the stack uses, and Terraform does not create it. Without one, {names} cannot be "
        "served on its own domain.",
        fix="Request one certificate in us-east-1 covering <service-id>.<domain_name> for each "
        "site (or a wildcard), validate it by DNS, and pass its ARN as site_certificate_arn.",
        est_monthly_usd_impact=None,
    )


def trap_spa_fallback(ctx: TrapContext) -> Trap | None:
    spas = [c.serves[0] for c in ctx.components("cloudfront") if c.params.get("spa") == "true"]
    if not spas:
        return None
    return Trap(
        id="spa-fallback-hides-404s",
        severity="low",
        where="static_site.tf (custom_error_response)",
        why=f"{', '.join(spas)} answer every unknown path with /index.html and status 200, so "
        "broken links and missing assets look like successes and never show up as 404s in "
        "monitoring.",
        fix="Have the app render its own not-found page, and watch for missing assets with "
        "client-side error reporting. Turn the fallback off for multi-page sites.",
        est_monthly_usd_impact=None,
    )


def trap_stateful_sessions(ctx: TrapContext) -> Trap | None:
    sticky = [c.serves[0] for c in ctx.components("ecs-service-web") if "sticky:true" in c.items]
    if not sticky:
        return None
    return Trap(
        id="stateful-sessions",
        severity="medium",
        where="alb.tf (aws_lb_target_group stickiness), autoscaling.tf",
        why=f"{', '.join(sticky)} keep each visitor's session inside one task (Streamlit, Gradio "
        "and similar). Sticky sessions are enabled, but a task restart, a deployment or "
        "autoscaling scale-in ends the sessions on that task, and one busy session cannot be "
        "spread across tasks.",
        fix="Keep the minimum task count at 2 or more, raise the scale-in cooldown, deploy "
        "outside busy hours, and keep state you cannot lose in a database, not in the session.",
        est_monthly_usd_impact=None,
    )


def trap_heavy_ml_image(ctx: TrapContext) -> Trap | None:
    heavy = {}
    for service in ctx.system.services:
        found = sorted(
            {f.value for f in service.facts if f.kind == "dependency"} & {"torch", "tensorflow"}
        )
        if found and any(
            c.serves == [service.id]
            for c in ctx.components("ecs-service-web", "ecs-service-worker")
        ):
            heavy[service.id] = found
    if not heavy:
        return None
    listing = "; ".join(f"{sid} ({', '.join(libs)})" for sid, libs in sorted(heavy.items()))
    return Trap(
        id="heavy-ml-image",
        severity="medium",
        where="ecr.tf, ecs.tf (task size)",
        why=f"{listing} pull in a machine-learning framework: the container image is several GB, "
        "slow to build, push and start, and uses a lot of memory per task. Fargate has no GPU, "
        "so heavy inference or any training would be slow or not possible there.",
        fix="Use CPU-only wheels and a slim base image, load the model once at start-up, run "
        "training or batch scoring outside this service, and measure real memory before keeping "
        "the default 1 vCPU / 4 GB size.",
        est_monthly_usd_impact=None,
    )


TRAPS: list[TrapFn] = [
    trap_no_outbound_path, trap_interface_endpoints, trap_log_ingestion, trap_public_ipv4,
    trap_internet_egress, trap_autoscaling_max_cost, trap_alarm_subscription,
    trap_redis_replica, trap_multi_az_nonprod,
    trap_container_insights, trap_cross_az, trap_cloudfront_certificate, trap_spa_fallback,
    trap_stateful_sessions, trap_heavy_ml_image, trap_public_task_addresses,
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
