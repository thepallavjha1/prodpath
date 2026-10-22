"""Each trap has a case where it fires and a case where it must not (TESTING.md section 7)."""

from pathlib import Path

import pytest

from prodpath.forecast import UsageBook
from prodpath.models import Architecture, Edge, Evidence, Prefs, Service, SystemModel, Trap
from prodpath.providers.aws import AwsProvider
from prodpath.providers.aws.traps import TRAPS, TrapContext, find_traps
from tests.helpers import make_fact as f
from tests.helpers import make_service as svc

PRICES = Path(__file__).parent / "fixtures" / "prices"
WEB = [f("port", "8000"), f("health_endpoint", "/health")]


def traps_for(
    services: list[Service], env: str = "prod", edges: list[Edge] | None = None
) -> tuple[dict[str, Trap], Architecture]:
    provider = AwsProvider(PRICES)
    system = SystemModel(services=services, edges=edges or [])
    arch = provider.choose(system, Prefs(environment=env))  # type: ignore[arg-type]
    forecast = provider.forecast(arch, system, UsageBook())
    return {t.id: t for t in provider.traps(arch, system, forecast)}, arch


DB_APP = [svc("api", "web", [*WEB, f("datastore", "postgres"), f("env_var", "DATABASE_URL")])]


def test_no_outbound_path_fires_for_http_clients_edges_and_queues() -> None:
    caller = svc(
        "api", "web", [*WEB, f("datastore", "postgres"), f("external_call", "http-client")]
    )
    traps, _ = traps_for([caller])
    assert traps["no-outbound-path"].severity == "high"
    assert "api make outbound HTTP calls" in traps["no-outbound-path"].why

    edge = Edge(
        src="a",
        dst="b",
        via="http",
        evidence=[Evidence(path="a.py", line=1, snippet="BILLING_URL")],
    )
    pair = [
        svc("a", "web", [*WEB, f("datastore", "postgres")]),
        svc("b", "web", [*WEB, f("datastore", "postgres")]),
    ]
    traps, _ = traps_for(pair, edges=[edge])
    assert "a->b" in traps["no-outbound-path"].why

    queued = svc("api", "web", [*WEB, f("queue", "sqs")])
    traps, _ = traps_for([queued])
    assert "SQS/SNS" in traps["no-outbound-path"].why


def test_no_outbound_path_stays_quiet_without_a_reason() -> None:
    traps, _ = traps_for(DB_APP)
    assert "no-outbound-path" not in traps


def test_interface_endpoint_cost_is_priced_from_the_forecast() -> None:
    """4 endpoints x 2 AZs x 730 h x 0.01 = 58.40 with the test prices."""
    traps, _ = traps_for(DB_APP)
    assert traps["interface-endpoint-fixed-cost"].est_monthly_usd_impact == pytest.approx(58.40)
    lone = [svc("site", "web", WEB)]  # App Runner: no VPC, no endpoints
    traps, _ = traps_for(lone)
    assert "interface-endpoint-fixed-cost" not in traps


def test_log_ingestion_fires_with_a_computed_impact_and_share_based_severity() -> None:
    """Expected ingestion 5.256 GB x 0.50 = 2.628; spike 13.14 is small next to the fixed costs."""
    traps, _ = traps_for(DB_APP)
    assert traps["log-ingestion"].est_monthly_usd_impact == pytest.approx(2.63, abs=0.005)
    assert traps["log-ingestion"].severity == "low"


def test_log_ingestion_becomes_high_when_logs_dominate_the_bill() -> None:
    provider = AwsProvider(PRICES)
    system = SystemModel(services=DB_APP)
    arch = provider.choose(system, Prefs())
    usage = UsageBook({"log_kb_per_request": 2000.0})  # 2 MB of logs per request
    forecast = provider.forecast(arch, system, usage)
    found = {t.id: t for t in provider.traps(arch, system, forecast)}
    assert found["log-ingestion"].severity == "high"


def test_public_ipv4_trap_needs_a_load_balancer() -> None:
    traps, _ = traps_for(DB_APP)
    assert traps["public-ipv4"].est_monthly_usd_impact == pytest.approx(7.30)
    traps, _ = traps_for(
        [svc("job", "worker", [f("worker", "celery"), f("datastore", "postgres")])]
    )
    assert "public-ipv4" not in traps


def test_internet_egress_trap_only_exists_with_web_services() -> None:
    traps, _ = traps_for(DB_APP)
    assert traps["internet-egress"].est_monthly_usd_impact == pytest.approx(2.63, abs=0.005)
    traps, _ = traps_for(
        [svc("job", "worker", [f("worker", "celery"), f("datastore", "postgres")])]
    )
    assert "internet-egress" not in traps


def test_no_autoscaling_lists_fixed_task_counts_and_skips_workers_only_systems() -> None:
    traps, _ = traps_for(DB_APP)
    assert "api=2" in traps["no-autoscaling"].why
    assert traps["no-autoscaling"].est_monthly_usd_impact is None
    traps, _ = traps_for(
        [svc("job", "worker", [f("worker", "celery"), f("datastore", "postgres")])]
    )
    assert "no-autoscaling" not in traps


def test_redis_replica_costs_one_extra_node_in_prod_and_nothing_in_nonprod() -> None:
    app = [svc("api", "web", [*WEB, f("cache", "redis")])]
    prod, _ = traps_for(app)
    assert prod["redis-replica"].est_monthly_usd_impact == pytest.approx(14.60)  # 1 x 730 x 0.02
    nonprod, _ = traps_for(app, env="nonprod")
    assert "redis-replica" not in nonprod


def test_multi_az_in_nonprod_fires_only_when_a_multi_az_database_is_planned() -> None:
    provider = AwsProvider(PRICES)
    system = SystemModel(services=DB_APP)
    arch = provider.choose(system, Prefs(environment="nonprod"))
    assert all(c.params["multi_az"] == "false" for c in arch.components if c.type == "rds")
    assert "multi-az-rds-in-nonprod" not in {
        t.id for t in provider.traps(arch, system, provider.forecast(arch, system, UsageBook()))
    }

    # Force the situation the rules never produce: Multi-AZ chosen in a non-production plan.
    for component in arch.components:
        if component.type == "rds":
            component.params.update({"multi_az": "true", "instance_class": "db.t4g.small"})
    forecast = provider.forecast(arch, system, UsageBook())
    found = {t.id: t for t in provider.traps(arch, system, forecast)}
    # (0.10 - 0.05) x 730 + (0.20 - 0.10) x 20 = 36.50 + 2.00
    assert found["multi-az-rds-in-nonprod"].est_monthly_usd_impact == pytest.approx(38.50)


def test_multi_az_trap_never_fires_in_prod() -> None:
    traps, _ = traps_for(DB_APP, env="prod")
    assert "multi-az-rds-in-nonprod" not in traps


def test_container_insights_and_cross_az_traps() -> None:
    traps, _ = traps_for(DB_APP)
    assert "container-insights" in traps and "cross-az-traffic" in traps
    nonprod, _ = traps_for(DB_APP, env="nonprod")
    assert "cross-az-traffic" not in nonprod  # one task, one AZ worth of data stores
    lone, _ = traps_for([svc("site", "web", WEB)])
    assert "container-insights" not in lone


def test_every_trap_has_a_reason_a_fix_and_a_location() -> None:
    traps, _ = traps_for(
        [
            svc(
                "api",
                "web",
                [
                    *WEB,
                    f("datastore", "postgres"),
                    f("cache", "redis"),
                    f("external_call", "http-client"),
                ],
            ),
        ]
    )
    assert len(traps) >= 8
    for trap in traps.values():
        assert trap.why and trap.fix and trap.where
        assert trap.severity in {"high", "medium", "low"}


def test_traps_are_ranked_by_severity_then_impact() -> None:
    provider = AwsProvider(PRICES)
    system = SystemModel(
        services=[
            svc(
                "api",
                "web",
                [
                    *WEB,
                    f("datastore", "postgres"),
                    f("cache", "redis"),
                    f("external_call", "http-client"),
                ],
            )
        ]
    )
    arch = provider.choose(system, Prefs())
    forecast = provider.forecast(arch, system, UsageBook())
    ranked = provider.traps(arch, system, forecast)
    assert ranked[0].id == "no-outbound-path"  # high severity first even though it is unpriced
    order = {"high": 0, "medium": 1, "low": 2}
    keys = [(order[t.severity], -(t.est_monthly_usd_impact or 0)) for t in ranked]
    assert keys == sorted(keys)


def test_the_registry_has_one_function_per_seeded_trap() -> None:
    assert len(TRAPS) == 12
    assert find_traps.__name__ == "find_traps" and TrapContext.__name__ == "TrapContext"


SITE = [f("framework", "vite"), f("framework", "react")]


def test_cloudfront_certificate_trap_fires_for_any_static_site_only() -> None:
    traps, _ = traps_for([svc("web", "static", SITE)])
    assert traps["cloudfront-certificate-region"].severity == "medium"
    assert "us-east-1" in traps["cloudfront-certificate-region"].why
    other, _ = traps_for(DB_APP)
    assert "cloudfront-certificate-region" not in other


def test_spa_fallback_trap_only_fires_for_client_routed_sites() -> None:
    spa, _ = traps_for([svc("web", "static", SITE)])
    assert "spa-fallback-hides-404s" in spa
    plain, _ = traps_for([svc("blog", "static", [f("framework", "gatsby")])])
    assert "spa-fallback-hides-404s" not in plain


def test_internet_egress_trap_counts_cloudfront_traffic_too() -> None:
    """A static site alone: 26.28 GB x 0.10 = 2.628 of CloudFront data out, no web services."""
    traps, _ = traps_for([svc("web", "static", SITE)])
    assert traps["internet-egress"].est_monthly_usd_impact == pytest.approx(2.63, abs=0.005)
    assert "no-autoscaling" not in traps and "interface-endpoint-fixed-cost" not in traps
