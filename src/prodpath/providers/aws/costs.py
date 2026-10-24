"""Architecture + usage + price snapshot -> cost lines for the AWS provider.

Every line carries the `price_ref` of the SKU it used. A dimension whose price is not in the
snapshot is reported in `not_priced` and contributes nothing: prices are never guessed.
Traffic-driven quantities scale with the scenario factor; always-on resources do not, because
nothing generated here autoscales.
"""

import math
from dataclasses import dataclass, field

from prodpath.forecast import SCENARIOS, UsageBook
from prodpath.models import Architecture, Component, CostLine, Forecast, SystemModel
from prodpath.providers.aws.iac import AZ_COUNT, build_alarms, interface_endpoints
from prodpath.providers.aws.pricing import PriceBook

Qty = tuple[float, float, float]  # low, expected, spike
LCU_REQUESTS_PER_SECOND = 25.0  # one ALB LCU covers 25 new connections per second
KB_PER_GB = 1_000_000.0

NOT_MODELLED = {
    "sns": "SNS requests and deliveries are not modelled.",
    "apprunner": "App Runner pricing is not modelled.",
    "documentdb": "DocumentDB pricing is not modelled.",
    "dynamodb": "DynamoDB pricing is not modelled.",
    "amazon-mq": "Amazon MQ pricing is not modelled.",
    "msk": "Amazon MSK pricing is not modelled.",
}
NOT_INCLUDED = [
    "NAT gateway (not in the downloaded price files; the generated Terraform has none by default).",
    "KMS, Route 53, ACM, WAF, CloudWatch metrics and alarms, Container Insights metrics.",
    "Cross-AZ and service-to-service data transfer; image pull traffic through VPC endpoints.",
    "RDS backup storage beyond the free allowance; RDS IOPS and throughput above baseline.",
    "Always-free allowances and credits are not applied, so figures lean high.",
    "Taxes, support plans, reserved or savings-plan discounts, volume discounts.",
]
COMPUTE_TYPES = {"ecs-service-web", "ecs-service-worker", "scheduled-task"}


@dataclass
class _Costing:
    arch: Architecture
    system: SystemModel
    usage: UsageBook
    prices: PriceBook
    lines: list[CostLine] = field(default_factory=list)
    not_priced: list[str] = field(default_factory=list)

    @property
    def hours(self) -> float:
        return self.usage.get("hours_per_month")

    def constant(self, quantity: float) -> Qty:
        return (quantity, quantity, quantity)

    def traffic(self, expected: float) -> Qty:
        return (
            expected * self.usage.factor("low"),
            expected,
            expected * self.usage.factor("spike"),
        )

    def add(self, component: str, dimension: str, unit: str, key: str, qty: Qty) -> None:
        price = self.prices.get(key)
        if price is None:
            reason = self.prices.missing.get(key, "no such price in the snapshot")
            self.not_priced.append(f"{component} / {dimension}: {key} ({reason})")
            return
        low, expected, spike = qty
        self.lines.append(
            CostLine(
                component=component,
                dimension=dimension,
                unit=unit,
                qty_low=low,
                qty_expected=expected,
                qty_spike=spike,
                unit_price=price.usd,
                price_ref=price.ref,
                usd_low=low * price.usd,
                usd_expected=expected * price.usd,
                usd_spike=spike * price.usd,
            )
        )


def _services(arch: Architecture, *types: str) -> list[Component]:
    return [c for c in arch.components if c.type in types]


def _http_edges(system: SystemModel) -> list[tuple[str, str]]:
    return sorted({(e.src, e.dst) for e in system.edges if e.via == "http"})


@dataclass
class _Web:
    sid: str
    rps: float  # external requests per second
    inbound: float  # extra requests per second from other services through the load balancer
    response_kb: float
    log_kb: float


def _web_services(costing: _Costing) -> list[_Web]:
    usage = costing.usage
    ids = sorted(c.serves[0] for c in _services(costing.arch, "ecs-service-web"))
    rps = {sid: usage.get("avg_requests_per_second", sid) for sid in ids}
    edges = [(s, d) for s, d in _http_edges(costing.system) if s in rps and d in rps]
    if edges:
        usage.infer(
            "internal_http_calls_per_request",
            1.0,
            "calls",
            "One internal request through the load balancer per request, for each service-to-"
            "service URL found in the code: " + ", ".join(f"{s}->{d}" for s, d in edges),
        )
    inbound = {sid: sum(rps[s] for s, d in edges if d == sid) for sid in ids}
    return [
        _Web(
            sid,
            rps[sid],
            inbound[sid],
            usage.get("response_kb", sid),
            usage.get("log_kb_per_request", sid),
        )
        for sid in ids
    ]


def _task_counts(costing: _Costing, c: Component, web: dict[str, _Web]) -> Qty:
    """Tasks per scenario. Web services follow traffic between their autoscaling bounds; workers
    and scheduled jobs stay at their starting count (their load is not known)."""
    minimum = int(c.params["desired_count"])
    scaling = next(
        (s for s in _services(costing.arch, "autoscaling") if s.serves == c.serves), None
    )
    sid = c.serves[0]
    if scaling is None or sid not in web:
        return costing.constant(float(minimum))
    maximum = int(scaling.params["max_count"])
    per_task = costing.usage.get("rps_per_task", sid)
    requests = web[sid].rps + web[sid].inbound
    low, expected, spike = (
        float(min(max(math.ceil(requests * costing.usage.factor(s) / per_task), minimum), maximum))
        for s in SCENARIOS
    )
    return (low, expected, spike)


def _budget(arch: Architecture) -> bool:
    return any(c.type == "vpc" and c.params.get("mode") == "budget" for c in arch.components)


def _fargate(costing: _Costing, web: list[_Web]) -> None:
    usage, hours = costing.usage, costing.hours
    address_hours: Qty = (0.0, 0.0, 0.0)
    web_by_id = {w.sid: w for w in web}
    for c in sorted(_services(costing.arch, *COMPUTE_TYPES), key=lambda x: x.name):
        sid = c.serves[0]
        vcpu, memory_gb = int(c.params["cpu"]) / 1024, int(c.params["memory"]) / 1024
        if c.type == "scheduled-task":
            runs = usage.get("cron_runs_per_month", sid)
            active = runs * usage.get("cron_minutes_per_run", sid) / 60
            tasks: Qty = costing.constant(float(c.params["desired_count"]))
        else:
            active = hours
            tasks = _task_counts(costing, c, web_by_id)
        costing.add(
            c.name, "vCPU-hours", "vCPU-h", "fargate.vcpu_hour", _times(tasks, vcpu * active)
        )
        costing.add(
            c.name, "memory GB-hours", "GB-h", "fargate.gb_hour", _times(tasks, memory_gb * active)
        )
        address_hours = _plus(address_hours, _times(tasks, active))
    if _budget(costing.arch):  # budget mode: every running task holds a public IPv4 address
        costing.add(
            "task-public-ips",
            "public IPv4 addresses (one per running task)",
            "address-h",
            "vpc.public_ipv4_hour",
            address_hours,
        )


def _plus(a: Qty, b: Qty) -> Qty:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _times(quantity: Qty, factor: float) -> Qty:
    return (quantity[0] * factor, quantity[1] * factor, quantity[2] * factor)


def _alarms(costing: _Costing) -> None:
    count = len(build_alarms(costing.arch))
    if count:
        costing.add(
            "alarms",
            f"{count} standard alarms",
            "alarm-month",
            "cloudwatch.alarm_month",
            costing.constant(float(count)),
        )


def _load_balancer(costing: _Costing, web: list[_Web]) -> None:
    if not _services(costing.arch, "alb"):
        return
    hours = costing.hours
    seconds_per_hour = 3600.0
    connections = sum(w.rps + w.inbound for w in web) / LCU_REQUESTS_PER_SECOND
    gb_per_hour = (
        sum((w.rps + w.inbound) * w.response_kb for w in web) * seconds_per_hour / KB_PER_GB
    )
    lcu = max(connections, gb_per_hour)  # the busiest LCU dimension sets the bill (simplified)
    costing.add("alb", "load balancer hours", "h", "alb.hour", costing.constant(hours))
    costing.add(
        "alb", "capacity units (LCU-hours)", "LCU-h", "alb.lcu_hour", costing.traffic(lcu * hours)
    )
    costing.add(
        "alb",
        "public IPv4 addresses (one per AZ)",
        "address-h",
        "vpc.public_ipv4_hour",
        costing.constant(AZ_COUNT * hours),
    )


def _logs(costing: _Costing, web: list[_Web]) -> tuple[float, float]:
    """Log lines per component. Returns (traffic-driven GB, constant GB) ingested per month."""
    seconds = costing.hours * 3600
    traffic_gb = constant_gb = 0.0
    web_by_id = {w.sid: w for w in web}
    for c in sorted(_services(costing.arch, "log-group"), key=lambda x: x.name):
        sid = c.name.removeprefix("logs-")
        retention = int(c.params.get("retention_days", "30"))
        if sid in web_by_id:
            w = web_by_id[sid]
            gb = w.rps * seconds * w.log_kb / KB_PER_GB
            quantity = costing.traffic(gb)
            traffic_gb += gb
        else:
            gb = costing.usage.get("worker_log_gb_per_month", sid)
            quantity = costing.constant(gb)
            constant_gb += gb
        costing.add(c.name, "log ingestion", "GB", "cloudwatch.logs_ingest_gb", quantity)
        stored = tuple(q * retention / 30 for q in quantity)  # steady-state retained volume
        costing.add(c.name, "log storage", "GB-month", "cloudwatch.logs_storage_gb_month", stored)  # type: ignore[arg-type]
    return traffic_gb, constant_gb


def _endpoints(costing: _Costing, traffic_gb: float, constant_gb: float) -> None:
    if not _services(costing.arch, "vpc") or _budget(costing.arch):
        return
    has_secrets = bool(_services(costing.arch, "secrets"))
    count = len(interface_endpoints(has_secrets))
    hours = costing.hours
    costing.add(
        "vpc-endpoints",
        f"{count} interface endpoints x {AZ_COUNT} AZs",
        "endpoint-h",
        "vpc.endpoint_hour",
        costing.constant(count * AZ_COUNT * hours),
    )
    low, expected, spike = costing.traffic(traffic_gb)
    costing.add(
        "vpc-endpoints",
        "data processed (logs)",
        "GB",
        "vpc.endpoint_gb",
        (low + constant_gb, expected + constant_gb, spike + constant_gb),
    )


def _data_stores(costing: _Costing) -> None:
    hours = costing.hours
    for c in sorted(_services(costing.arch, "rds"), key=lambda x: x.name):
        engine, klass = c.params["engine"], c.params["instance_class"]
        deployment = "multi_az" if c.params["multi_az"] == "true" else "single_az"
        costing.add(
            c.name,
            f"{klass} instance hours ({deployment})",
            "h",
            f"rds.instance.{engine}.{klass}.{deployment}",
            costing.constant(hours),
        )
        costing.add(
            c.name,
            "gp3 storage",
            "GB-month",
            f"rds.storage.gp3.{deployment}.{engine}",
            costing.constant(float(c.params["allocated_storage"])),
        )
    for c in _services(costing.arch, "elasticache"):
        if c.name == "elasticache-redis":
            nodes = int(c.params["num_cache_clusters"])
            node_type = c.params["node_type"]
            costing.add(
                c.name,
                f"{node_type} node hours x {nodes}",
                "node-h",
                f"elasticache.node.redis.{node_type}",
                costing.constant(nodes * hours),
            )
        else:
            costing.not_priced.append(f"{c.name} ({c.type}): only Redis nodes are modelled.")
    usage = costing.usage
    for c in sorted(_services(costing.arch, "s3"), key=lambda x: x.name):
        costing.add(
            c.name,
            "storage",
            "GB-month",
            "s3.storage_gb_month",
            costing.constant(usage.get("s3_stored_gb")),
        )
        costing.add(
            c.name,
            "PUT/COPY/POST/LIST requests",
            "requests",
            "s3.put_request",
            costing.traffic(usage.get("s3_puts_per_month")),
        )
        costing.add(
            c.name,
            "GET requests",
            "requests",
            "s3.get_request",
            costing.traffic(usage.get("s3_gets_per_month")),
        )
    if _services(costing.arch, "sqs"):
        messages = usage.get("sqs_messages_per_month")
        costing.add(
            "sqs",
            "API requests (send + receive + delete)",
            "requests",
            "sqs.request",
            costing.traffic(3 * messages),
        )


def _secrets_and_registry(costing: _Costing) -> None:
    usage, arch = costing.usage, costing.arch
    starts = usage.get("task_starts_per_month")
    slots = 0
    api_calls = 0.0
    desired = {c.serves[0]: int(c.params["desired_count"]) for c in _services(arch, *COMPUTE_TYPES)}
    for c in _services(arch, "secrets"):
        slots += len(c.items)
        api_calls += len(c.items) * desired.get(c.serves[0], 1) * starts
    managed = len(_services(arch, "rds"))  # RDS keeps each master password in its own secret
    if slots + managed:
        costing.add(
            "secrets",
            f"{slots} slots + {managed} RDS-managed",
            "secret-month",
            "secrets.secret_month",
            costing.constant(slots + managed),
        )
        costing.add(
            "secrets",
            "API requests at task start",
            "requests",
            "secrets.api_request",
            costing.constant(api_calls),
        )
    repos = len(_services(arch, "ecr"))
    if repos:
        costing.add(
            "ecr",
            f"{repos} repositories",
            "GB-month",
            "ecr.storage_gb_month",
            costing.constant(repos * usage.get("ecr_gb_per_repo")),
        )


def _internet_egress(costing: _Costing, web: list[_Web]) -> None:
    if not web:
        return
    seconds = costing.hours * 3600
    gb = sum(w.rps * seconds * w.response_kb / KB_PER_GB for w in web)
    costing.add(
        "internet-egress",
        "data transfer out to the internet",
        "GB",
        "dt.out_gb",
        costing.traffic(gb),
    )


# Viewers are assumed to sit in the same geography as the AWS region; CloudFront bills by the
# geography of the edge that serves them. First matching prefix wins.
EDGE_GEOGRAPHY_BY_REGION = (
    ("ap-south-", "in"), ("ap-northeast", "jp"), ("ap-southeast-2", "au"), ("ap-", "ap"),
    ("eu-", "eu"), ("us-", "us"), ("ca-", "ca"), ("sa-", "sa"), ("me-", "me"), ("il-", "me"),
    ("af-", "za"),
)  # fmt: skip


def edge_geography(region: str) -> str:
    return next(
        (geo for prefix, geo in EDGE_GEOGRAPHY_BY_REGION if region.startswith(prefix)), "us"
    )


def _static_sites(costing: _Costing) -> None:
    sites = sorted(_services(costing.arch, "cloudfront"), key=lambda c: c.name)
    if not sites:
        return
    usage, seconds = costing.usage, costing.hours * 3600
    geography = edge_geography(costing.arch.region)
    usage.infer(
        "cloudfront_edge_geography",
        1.0,
        "geography",
        f"Viewers are assumed to be in the same geography as {costing.arch.region}, so "
        f"CloudFront is priced at its {geography.upper()} edge rates.",
    )
    hit_ratio = usage.get("cdn_cache_hit_ratio")
    for c in sites:
        sid = c.serves[0]
        requests = usage.get("avg_requests_per_second", sid) * seconds
        gigabytes = requests * usage.get("response_kb", sid) / KB_PER_GB
        edge = f"cloudfront-{sid}"
        costing.add(
            edge,
            "HTTPS requests",
            "requests",
            f"cloudfront.requests_https.{geography}",
            costing.traffic(requests),
        )
        costing.add(
            edge,
            "data transfer out",
            "GB",
            f"cloudfront.out_gb.{geography}",
            costing.traffic(gigabytes),
        )
        bucket = f"s3-site-{sid}"
        costing.add(
            bucket,
            "storage",
            "GB-month",
            "s3.storage_gb_month",
            costing.constant(usage.get("site_stored_gb")),
        )
        costing.add(
            bucket,
            "GET requests (cache misses)",
            "requests",
            "s3.get_request",
            costing.traffic(requests * (1 - hit_ratio)),
        )


def build_forecast(
    arch: Architecture, system: SystemModel, usage: UsageBook, prices: PriceBook
) -> Forecast:
    costing = _Costing(arch, system, usage, prices)
    web = _web_services(costing)
    _fargate(costing, web)
    _load_balancer(costing, web)
    traffic_gb, constant_gb = _logs(costing, web)
    _endpoints(costing, traffic_gb, constant_gb)
    _data_stores(costing)
    _secrets_and_registry(costing)
    _internet_egress(costing, web)
    _static_sites(costing)
    _alarms(costing)
    for c in arch.components:
        if c.type in NOT_MODELLED:
            costing.not_priced.append(f"{c.name} ({c.type}): {NOT_MODELLED[c.type]}")
    lines = costing.lines
    return Forecast(
        provider="aws",
        region=arch.region,
        lines=lines,
        total_low=sum(line.usd_low for line in lines),
        total_expected=sum(line.usd_expected for line in lines),
        total_spike=sum(line.usd_spike for line in lines),
        assumptions=usage.assumptions(),
        not_priced=sorted(dict.fromkeys(costing.not_priced)),
        not_included=NOT_INCLUDED,
        price_snapshot=prices.describe(),
    )
