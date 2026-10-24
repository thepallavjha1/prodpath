"""Cost model checks against hand-computed forecasts.

Prices come from tests/fixtures/prices/ap-south-1.json: made-up round numbers (TEST ONLY), so
every figure below can be verified with a calculator. Defaults used: 1 req/s per web service,
10 KB responses, 2 KB of logs per request, 730 hours (2,628,000 s) per month, low = 0.25x and
spike = 5x traffic.

Test prices: alarm 0.10/month, vCPU-h 0.04, GB-h 0.005, ALB 0.02/h + 0.01/LCU-h, public IPv4
0.005/h, interface endpoint 0.01/h + 0.01/GB, logs 0.50/GB ingested + 0.03/GB-month stored,
S3 0.02/GB-month + 0.00001/PUT + 0.000001/GET, SQS 0.000001/request, secret 0.50/month +
0.00001/API call, ECR 0.10/GB-month, data out 0.10/GB, RDS postgres db.t4g.small 0.05/h
single or 0.10/h Multi-AZ, gp3 0.10 or 0.20 per GB-month, Redis cache.t4g.micro 0.02/h.
"""

from pathlib import Path

import pytest

from prodpath.forecast import UsageBook
from prodpath.models import Forecast, Prefs
from prodpath.providers.aws import AwsProvider
from prodpath.providers.aws.pricing import PriceBook
from tests.helpers import ONE_RPS, build_system, kitchen_sink_system

PRICES = Path(__file__).parent / "fixtures" / "prices"
APPROX = {"abs": 0.005}  # "within rounding": half a cent


def forecast_for(
    system,
    usage: UsageBook | None = None,
    env: str = "prod",  # type: ignore[no-untyped-def]
) -> Forecast:
    provider = AwsProvider(PRICES)
    arch = provider.choose(system, Prefs(environment=env))  # type: ignore[arg-type]
    return provider.forecast(arch, system, usage or UsageBook(ONE_RPS))


def line(forecast: Forecast, component: str, dimension: str):  # type: ignore[no-untyped-def]
    return next(
        ln for ln in forecast.lines if ln.component == component and dimension in ln.dimension
    )


def test_mono_b_matches_the_hand_computed_forecast(fixtures_dir: Path, tmp_path: Path) -> None:
    """api (web, 2 tasks of 0.5 vCPU / 1 GB), worker (2 x 0.25 vCPU / 0.5 GB), Redis, 2 secrets.

    Always-on, same in every scenario:
      Fargate api: 730 vCPU-h x 0.04 = 29.20 + 1,460 GB-h x 0.005 = 7.30
      Fargate worker: 365 vCPU-h x 0.04 = 14.60 + 730 GB-h x 0.005 = 3.65       -> 54.75
      ALB hours 730 x 0.02 = 14.60; public IPv4 2 x 730 x 0.005 = 7.30
      Endpoints 4 x 2 AZ x 730 h x 0.01 = 58.40; Redis 2 x 730 x 0.02 = 29.20
      Secrets 2 x 0.50 + 120 calls x 0.00001 = 1.0012; ECR 4 GB x 0.10 = 0.40
      worker logs 1 GB x 0.50 + 1 GB-month x 0.03 = 0.53
      Alarms: api 4 (CPU, memory, 5xx, unhealthy) + worker 2 + Redis 2 = 8 x 0.10 = 0.80
      -> constants 54.75 + 14.60 + 7.30 + 58.40 + 29.20 + 1.0012 + 0.40 + 0.53 + 0.80 = 166.9812
    Traffic-driven (api, expected): requests 2,628,000
      LCU: max(1/25, 1 x 10 x 3600 / 1e6 = 0.036) = 0.04 x 730 = 29.2 LCU-h x 0.01 = 0.292
      api logs: 5.256 GB x 0.50 = 2.628, stored 5.256 x 0.03 = 0.15768
      endpoint data: (5.256 + 1) GB x 0.01 = 0.06256; data out: 26.28 GB x 0.10 = 2.628
      -> expected 0.292 + 2.628 + 0.15768 + 0.06256 + 2.628 = 5.76824 -> total 172.74944
    Low (0.25x): LCU 0.073, logs 0.657 + 0.03942, endpoints (1.314 + 1) x 0.01 = 0.02314,
      out 0.657 -> 1.44956 -> total 168.43076
    Spike (5x): LCU 1.46, logs 13.14 + 0.7884, endpoints (26.28 + 1) x 0.01 = 0.2728, out 13.14
      -> 28.8012 -> total 195.7824
    """
    system = build_system(fixtures_dir / "mono_b", tmp_path)
    forecast = forecast_for(system)
    assert forecast.total_low == pytest.approx(168.43076, **APPROX)
    assert forecast.total_expected == pytest.approx(172.74944, **APPROX)
    assert forecast.total_spike == pytest.approx(195.7824, **APPROX)
    assert forecast.not_priced == []


def test_mono_a_matches_the_hand_computed_forecast(fixtures_dir: Path, tmp_path: Path) -> None:
    """root (web, 2 tasks), Postgres db.t4g.small Multi-AZ 20 GB, one S3 bucket, 2 secret slots.

    Constants: Fargate 29.20 + 7.30 = 36.50; ALB 14.60 + IPv4 7.30; endpoints 58.40;
      RDS 730 x 0.10 = 73.00 + 20 x 0.20 = 4.00; S3 storage 10 x 0.02 = 0.20;
      secrets (2 slots + 1 RDS-managed) 1.50 + 120 x 0.00001 = 1.5012; ECR 2 x 0.10 = 0.20
      alarms: root 4 + Postgres 2 = 6 x 0.10 = 0.60 -> 196.3012
    Traffic, expected: LCU 0.292; logs 2.628 + 0.15768; endpoint data 5.256 x 0.01 = 0.05256;
      S3 100,000 PUT x 0.00001 = 1.00 + 1,000,000 GET x 0.000001 = 1.00; data out 2.628
      -> 7.75824 -> total 204.05944
    Low: 0.073 + (0.657 + 0.03942) + 0.01314 + 0.50 + 0.657 = 1.93956 -> 198.24076
    Spike: 1.46 + (13.14 + 0.7884) + 0.2628 + 10.00 + 13.14 = 38.7912 -> 235.0924
    """
    forecast = forecast_for(build_system(fixtures_dir / "mono_a", tmp_path))
    assert forecast.total_low == pytest.approx(198.24076, **APPROX)
    assert forecast.total_expected == pytest.approx(204.05944, **APPROX)
    assert forecast.total_spike == pytest.approx(235.0924, **APPROX)


def test_mono_c_matches_the_hand_computed_forecast(fixtures_dir: Path, tmp_path: Path) -> None:
    """5 web services (2 tasks each), 1 cron job, Postgres, Redis, 3 slots, gateway calls
    billing and users through the load balancer (2 internal requests per gateway request).

    Constants: Fargate 5 x 36.50 = 182.50 + cron (1.25 vCPU-h x 0.04 + 2.5 GB-h x 0.005 = 0.0625)
      ALB 14.60 + IPv4 7.30; endpoints 58.40; RDS 77.00; Redis 29.20;
      secrets (3 + 1 managed) x 0.50 = 2.00 + 180 calls x 0.00001 = 0.0018; ECR 6 x 2 x 0.10 = 1.20;
      cron logs 0.50 + 0.03; alarms 5 web x 4 + Postgres 2 + Redis 2 = 24 x 0.10 = 2.40
      -> 375.1943
    Traffic, expected: LCU (5 + 2 = 7 req/s: max(0.28, 0.252) = 0.28) x 730 x 0.01 = 2.044;
      web logs 5 x (2.628 + 0.15768) = 13.9284; endpoint data (26.28 + 1) x 0.01 = 0.2728;
      data out 5 x 26.28 = 131.4 GB x 0.10 = 13.14 -> 29.3852 -> total 404.5795
    Low: 0.511 + 3.4821 + 0.0757 + 3.285 = 7.3538 -> 382.5481
    Spike: 10.22 + 69.642 + 1.324 + 65.70 = 146.886 -> 522.0803
    """
    forecast = forecast_for(build_system(fixtures_dir / "mono_c", tmp_path))
    assert forecast.total_low == pytest.approx(382.5481, **APPROX)
    assert forecast.total_expected == pytest.approx(404.5795, **APPROX)
    assert forecast.total_spike == pytest.approx(522.0803, **APPROX)
    inferred = [a for a in forecast.assumptions if a.source == "inferred"]
    assert [a.name for a in inferred] == ["internal_http_calls_per_request"]
    assert "apps-gateway->apps-billing" in inferred[0].note


@pytest.fixture(params=["mono_a", "mono_b", "mono_c", "mono_d"])
def fixture_forecast(
    request: pytest.FixtureRequest, fixtures_dir: Path, tmp_path: Path
) -> Forecast:
    return forecast_for(build_system(fixtures_dir / request.param, tmp_path))


def test_every_cost_line_traces_to_a_price_in_the_snapshot(fixture_forecast: Forecast) -> None:
    refs = PriceBook.load(PRICES / "ap-south-1.json").refs()
    assert fixture_forecast.lines
    for ln in fixture_forecast.lines:
        assert ln.price_ref in refs, ln
        assert ln.usd_expected == pytest.approx(ln.qty_expected * ln.unit_price)
        assert ln.usd_low == pytest.approx(ln.qty_low * ln.unit_price)
        assert ln.usd_spike == pytest.approx(ln.qty_spike * ln.unit_price)


def test_totals_are_the_sum_of_the_lines(fixture_forecast: Forecast) -> None:
    assert fixture_forecast.total_expected == pytest.approx(
        sum(ln.usd_expected for ln in fixture_forecast.lines)
    )
    assert (
        fixture_forecast.total_low
        <= fixture_forecast.total_expected
        <= fixture_forecast.total_spike
    )


def test_every_assumption_has_a_source_and_a_note(fixture_forecast: Forecast) -> None:
    assert fixture_forecast.assumptions
    for a in fixture_forecast.assumptions:
        assert a.source in {"user", "default", "inferred"} and a.note


def test_always_on_lines_do_not_change_between_scenarios(
    fixtures_dir: Path, tmp_path: Path
) -> None:
    forecast = forecast_for(build_system(fixtures_dir / "mono_a", tmp_path))
    for component, dimension in [
        ("ecs-svc-root", "vCPU"),
        ("alb", "load balancer hours"),
        ("rds-postgres", "instance"),
    ]:
        ln = line(forecast, component, dimension)
        assert ln.usd_low == ln.usd_expected == ln.usd_spike
    ingestion = line(forecast, "logs-root", "ingestion")
    assert ingestion.usd_low == pytest.approx(ingestion.usd_expected * 0.25)
    assert ingestion.usd_spike == pytest.approx(ingestion.usd_expected * 5)


def test_user_overrides_replace_defaults_and_are_labelled_user(
    fixtures_dir: Path, tmp_path: Path
) -> None:
    system = build_system(fixtures_dir / "mono_a", tmp_path)
    base = forecast_for(system)
    doubled = forecast_for(system, UsageBook({"avg_requests_per_second": 2.0}))
    assert line(doubled, "internet-egress", "data transfer").usd_expected == pytest.approx(
        2 * line(base, "internet-egress", "data transfer").usd_expected
    )
    assumption = next(a for a in doubled.assumptions if a.name == "avg_requests_per_second")
    assert (assumption.value, assumption.source) == (2.0, "user")


def test_a_service_override_applies_to_that_service_only(
    fixtures_dir: Path, tmp_path: Path
) -> None:
    system = build_system(fixtures_dir / "mono_c", tmp_path)
    usage = UsageBook(service_overrides={"apps-web": {"avg_requests_per_second": 10.0}})
    forecast = forecast_for(system, usage)
    heavy = line(forecast, "logs-apps-web", "ingestion").qty_expected
    light = line(forecast, "logs-apps-users", "ingestion").qty_expected
    assert heavy == pytest.approx(2.5 * light)  # 10 req/s for apps-web against the default 4
    names = {a.name: a.source for a in forecast.assumptions}
    assert names["avg_requests_per_second@apps-web"] == "user"
    assert names["avg_requests_per_second"] == "default"


def test_nonprod_uses_single_az_micro_database(fixtures_dir: Path, tmp_path: Path) -> None:
    """db.t4g.micro single-AZ: 730 x 0.03 = 21.90 and 20 GB x 0.10 = 2.00 (test prices)."""
    forecast = forecast_for(build_system(fixtures_dir / "mono_a", tmp_path), env="nonprod")
    assert line(forecast, "rds-postgres", "instance").usd_expected == pytest.approx(21.90)
    assert line(forecast, "rds-postgres", "storage").usd_expected == pytest.approx(2.00)


def test_unpriced_dimensions_are_listed_never_guessed(fixtures_dir: Path, tmp_path: Path) -> None:
    system = build_system(fixtures_dir / "mono_a", tmp_path)
    provider = AwsProvider(PRICES)
    arch = provider.choose(system, Prefs(environment="prod"))
    book = provider.price_book("ap-south-1")
    del book._prices["alb.lcu_hour"]  # simulate a snapshot without that price
    forecast = provider.forecast(arch, system, UsageBook(ONE_RPS))
    assert any(
        "alb / capacity units" in item and "alb.lcu_hour" in item for item in forecast.not_priced
    )
    assert not any(ln.dimension.startswith("capacity units") for ln in forecast.lines)


def test_components_without_a_price_model_are_listed(tmp_path: Path) -> None:
    forecast = forecast_for(kitchen_sink_system())
    text = " ".join(forecast.not_priced)
    for name in ("sns", "documentdb"):
        assert name in text
    assert "elasticache-memcached" in text


def test_nat_gateway_and_free_tiers_are_declared_out_of_scope(fixture_forecast: Forecast) -> None:
    text = " ".join(fixture_forecast.not_included)
    assert "NAT gateway" in text and "free" in text.lower()


def test_mono_d_matches_the_hand_computed_forecast(fixtures_dir: Path, tmp_path: Path) -> None:
    """Mixed monorepo: Flask API + Postgres, SSR Next dashboard, and three static sites
    (Vite SPA, exported Next, nginx docs). Extra test prices: CloudFront data out 0.10/GB and
    0.000001 per HTTPS request (India edge, the ap-south-1 geography); static defaults:
    0.5 GB stored per site, 90% cache hit ratio, 1 req/s and 10 KB per request per site.

    Compute and data (2 web services, 2 tasks each):
      Fargate 2 x 36.50 = 73.00; ALB 14.60 + IPv4 7.30; endpoints 4 x 2 x 730 x 0.01 = 58.40;
      RDS 73.00 + 4.00 = 77.00; secrets (1 slot + 1 managed) 1.00 + 60 calls x 0.00001 = 1.0006;
      ECR 2 x 2 GB x 0.10 = 0.40; alarms (api 4 + dashboard 4 + Postgres 2) 10 x 0.10 = 1.00
      -> constants 232.7006 + static storage 3 x 0.5 x 0.02 = 0.03
    Traffic, expected: LCU (2 req/s: max(0.08, 0.072) x 730 x 0.01) = 0.584;
      logs 2 x 2.78568 = 5.57136; endpoint data 10.512 GB x 0.01 = 0.10512;
      internet egress 52.56 GB x 0.10 = 5.256
    Static, per site: requests 2,628,000 x 0.000001 = 2.628; data out 26.28 GB x 0.10 = 2.628;
      S3 GET misses 262,800 x 0.000001 = 0.2628 -> 5.5188 x 3 = 16.5564 (+ storage counted above)
    Expected = 232.7306 + 0.584 + 5.57136 + 0.10512 + 5.256 + 16.5564 = 260.80348
    Low (0.25x): 232.7306 + 0.146 + 1.39284 + 0.02628 + 1.314 + 3 x 1.3797 = 239.74882
    Spike (5x): 232.7306 + 2.92 + 27.8568 + 0.5256 + 26.28 + 3 x 27.594 = 373.095
    """
    forecast = forecast_for(build_system(fixtures_dir / "mono_d", tmp_path))
    assert forecast.total_low == pytest.approx(239.74882, **APPROX)
    assert forecast.total_expected == pytest.approx(260.80348, **APPROX)
    assert forecast.total_spike == pytest.approx(373.095, **APPROX)
    assert forecast.not_priced == []
    geography = [a for a in forecast.assumptions if a.name == "cloudfront_edge_geography"]
    assert geography and geography[0].source == "inferred" and "IN" in geography[0].note


def test_static_site_lines_use_the_edge_geography_prices_and_scale_with_traffic(
    fixtures_dir: Path, tmp_path: Path
) -> None:
    forecast = forecast_for(build_system(fixtures_dir / "mono_d", tmp_path))
    data_out = line(forecast, "cloudfront-apps-spa", "data transfer out")
    assert data_out.price_ref == "TEST/cloudfront.out_gb.in/cloudfront.out_gb.in"
    assert data_out.qty_expected == pytest.approx(26.28)
    assert data_out.usd_low == pytest.approx(data_out.usd_expected * 0.25)
    assert data_out.usd_spike == pytest.approx(data_out.usd_expected * 5)
    requests = line(forecast, "cloudfront-apps-spa", "HTTPS requests")
    assert requests.price_ref.endswith("cloudfront.requests_https.in")
    storage = line(forecast, "s3-site-apps-spa", "storage")
    assert storage.usd_low == storage.usd_expected == storage.usd_spike == pytest.approx(0.01)


def test_a_higher_cache_hit_ratio_removes_s3_origin_requests(
    fixtures_dir: Path, tmp_path: Path
) -> None:
    system = build_system(fixtures_dir / "mono_d", tmp_path)
    base = forecast_for(system)
    perfect = forecast_for(system, UsageBook({"cdn_cache_hit_ratio": 1.0}))
    assert line(base, "s3-site-apps-spa", "GET").usd_expected == pytest.approx(0.2628)
    assert line(perfect, "s3-site-apps-spa", "GET").usd_expected == 0.0
    ratio = next(a for a in perfect.assumptions if a.name == "cdn_cache_hit_ratio")
    assert (ratio.value, ratio.source) == (1.0, "user")


def test_the_edge_geography_follows_the_aws_region() -> None:
    from prodpath.providers.aws.costs import edge_geography

    expected = {
        "ap-south-1": "in", "ap-northeast-1": "jp", "ap-southeast-2": "au", "ap-southeast-1": "ap",
        "eu-west-1": "eu", "us-east-1": "us", "ca-central-1": "ca", "sa-east-1": "sa",
        "me-south-1": "me", "af-south-1": "za", "mars-north-1": "us",
    }  # fmt: skip
    assert {region: edge_geography(region) for region in expected} == expected


def test_missing_cloudfront_prices_are_listed_not_guessed(
    fixtures_dir: Path, tmp_path: Path
) -> None:
    system = build_system(fixtures_dir / "mono_d", tmp_path)
    provider = AwsProvider(PRICES)
    arch = provider.choose(system, Prefs())
    del provider.price_book("ap-south-1")._prices["cloudfront.out_gb.in"]
    forecast = provider.forecast(arch, system, UsageBook(ONE_RPS))
    assert any(
        "cloudfront-apps-spa" in item and "cloudfront.out_gb.in" in item
        for item in forecast.not_priced
    )
    assert not any(ln.dimension == "data transfer out" for ln in forecast.lines)


def test_web_tasks_scale_with_traffic_between_the_bounds(
    fixtures_dir: Path, tmp_path: Path
) -> None:
    """mono_a root (0.5 vCPU, bounds 2 to 10, 25 req/s per task) at 100 req/s expected:
    low 25 req/s -> ceil(1) = 1 -> held at the minimum 2: 0.5 x 2 x 730 x 0.04 = 29.20
    expected 100 req/s -> 4 tasks: 0.5 x 4 x 730 x 0.04 = 58.40
    spike 500 req/s -> 20 tasks -> capped at the maximum 10: 0.5 x 10 x 730 x 0.04 = 146.00
    """
    system = build_system(fixtures_dir / "mono_a", tmp_path)
    forecast = forecast_for(system, UsageBook({"avg_requests_per_second": 100.0}))
    vcpu = line(forecast, "ecs-svc-root", "vCPU")
    assert (vcpu.usd_low, vcpu.usd_expected, vcpu.usd_spike) == pytest.approx(
        (29.20, 58.40, 146.00)
    )
    memory = line(forecast, "ecs-svc-root", "memory")  # 1 GB each: 2, 4 and 10 tasks x 730 x 0.005
    assert (memory.usd_low, memory.usd_expected, memory.usd_spike) == pytest.approx(
        (7.30, 14.60, 36.50)
    )
    assumption = next(a for a in forecast.assumptions if a.name == "rps_per_task")
    assert (assumption.value, assumption.source) == (25.0, "default")


def test_a_per_service_capacity_override_changes_only_that_service(
    fixtures_dir: Path, tmp_path: Path
) -> None:
    system = build_system(fixtures_dir / "mono_c", tmp_path)
    usage = UsageBook(
        {"avg_requests_per_second": 100.0},
        {"apps-web": {"rps_per_task": 100.0}},  # a fast service: one task per 100 req/s
    )
    forecast = forecast_for(system, usage)
    fast = line(forecast, "ecs-svc-apps-web", "vCPU").qty_expected  # 100 / 100 -> 1 -> min 2
    slow = line(forecast, "ecs-svc-apps-notifier", "vCPU").qty_expected  # 100 / 25 -> 4 tasks
    assert fast == pytest.approx(0.5 * 2 * 730) and slow == pytest.approx(0.5 * 4 * 730)
    sources = {a.name: a.source for a in forecast.assumptions}
    assert sources["rps_per_task@apps-web"] == "user" and sources["rps_per_task"] == "default"


def test_internal_calls_count_towards_the_callee_s_load(fixtures_dir: Path, tmp_path: Path) -> None:
    """apps-billing receives its own 100 req/s plus apps-gateway's 100: 200 / 25 = 8 tasks."""
    system = build_system(fixtures_dir / "mono_c", tmp_path)
    forecast = forecast_for(system, UsageBook({"avg_requests_per_second": 100.0}))
    assert line(forecast, "ecs-svc-apps-billing", "vCPU").qty_expected == pytest.approx(
        0.5 * 8 * 730
    )
    assert line(forecast, "ecs-svc-apps-notifier", "vCPU").qty_expected == pytest.approx(
        0.5 * 4 * 730
    )


def test_workers_and_scheduled_jobs_do_not_scale_with_web_traffic(
    fixtures_dir: Path, tmp_path: Path
) -> None:
    system = build_system(fixtures_dir / "mono_b", tmp_path)
    forecast = forecast_for(system, UsageBook({"avg_requests_per_second": 500.0}))
    worker = line(forecast, "ecs-svc-worker", "vCPU")
    assert worker.usd_low == worker.usd_expected == worker.usd_spike == pytest.approx(14.60)


def test_alarms_are_priced_from_the_same_list_the_terraform_uses(
    fixtures_dir: Path, tmp_path: Path
) -> None:
    from prodpath.providers.aws.iac import build_alarms

    system = build_system(fixtures_dir / "mono_c", tmp_path)
    provider = AwsProvider(PRICES)
    arch = provider.choose(system, Prefs())
    forecast = provider.forecast(arch, system, UsageBook(ONE_RPS))
    alarms = line(forecast, "alarms", "standard alarms")
    assert alarms.qty_expected == len(build_alarms(arch)) == 24
    assert alarms.usd_expected == pytest.approx(2.40)
    assert alarms.usd_low == alarms.usd_expected == alarms.usd_spike


def test_default_peak_semantics_match_the_hand_computed_forecast(
    fixtures_dir: Path, tmp_path: Path
) -> None:
    """mono_a with the defaults: peak 20 req/s, ratio 5, so average 4 req/s and spike = 5x.

    Constants (unchanged by traffic): 196.3012, as in the average-1 case above.
    One task handles 25 req/s, so 4 and 20 req/s both fit in the minimum of 2 tasks.
    Traffic, expected (4 req/s): LCU max(4/25, 4 x 10 x 3600 / 1e6) = 0.16 x 730 x 0.01 = 1.168;
      logs 21.024 GB x 0.50 = 10.512, stored 21.024 x 0.03 = 0.63072;
      endpoint data 21.024 x 0.01 = 0.21024; data out 105.12 GB x 0.10 = 10.512;
      S3 PUT + GET do not follow requests per second: 1.00 + 1.00 = 2.00
      -> 1.168 + 10.512 + 0.63072 + 0.21024 + 10.512 = 23.03296 request-driven, + 2.00 S3
      = 25.03296 -> total 221.33416
    Low (0.25x): 25.03296 x 0.25 = 6.25824 -> 202.55944
    Spike (5x, a month at the 20 req/s peak): 25.03296 x 5 = 125.1648 -> 321.466
    """
    system = build_system(fixtures_dir / "mono_a", tmp_path)
    provider = AwsProvider(PRICES)
    arch = provider.choose(system, Prefs())
    forecast = provider.forecast(arch, system, UsageBook())  # all defaults
    assert forecast.total_low == pytest.approx(202.55944, **APPROX)
    assert forecast.total_expected == pytest.approx(221.33416, **APPROX)
    assert forecast.total_spike == pytest.approx(321.466, **APPROX)
    named = {a.name: (a.value, a.source) for a in forecast.assumptions}
    assert named["peak_requests_per_second"] == (20.0, "default")
    assert named["avg_requests_per_second"] == (4.0, "default")
    assert named["scenario_spike"] == (5.0, "default")


def test_a_higher_peak_scales_capacity_at_the_peak_not_the_monthly_volume(
    fixtures_dir: Path, tmp_path: Path
) -> None:
    """Peak 200 req/s (average 40): the spike month needs ceil(200 / 25) = 8 tasks, while the
    expected month needs ceil(40 / 25) = 2. Expected vCPU: 0.5 x 2 x 730 x 0.04 = 29.20;
    spike: 0.5 x 8 x 730 x 0.04 = 116.80."""
    system = build_system(fixtures_dir / "mono_a", tmp_path)
    forecast = forecast_for(system, UsageBook({"peak_requests_per_second": 200.0}))
    vcpu = line(forecast, "ecs-svc-root", "vCPU")
    assert (vcpu.usd_expected, vcpu.usd_spike) == pytest.approx((29.20, 116.80))


def budget_forecast(system, usage=None):  # type: ignore[no-untyped-def]
    provider = AwsProvider(PRICES)
    arch = provider.choose(system, Prefs(budget=True))
    return provider.forecast(arch, system, usage or UsageBook(ONE_RPS)), arch


def test_budget_mode_matches_the_hand_computed_forecast(fixtures_dir: Path, tmp_path: Path) -> None:
    """mono_a (2 tasks) with average 1 req/s. Against the standard figures 196.3012 constants:
    remove the interface endpoints (4 x 2 AZ x 730 h x 0.01 = 58.40) and their data
    (5.256 GB x 0.01 = 0.05256 expected, 0.01314 low, 0.2628 spike), add one public IPv4 per
    running task (2 tasks x 730 h x 0.005 = 7.30).
    Expected 204.05944 - 58.40 - 0.05256 + 7.30 = 152.90688
    Low      198.24076 - 58.40 - 0.01314 + 7.30 = 147.12762
    Spike    235.0924  - 58.40 - 0.2628  + 7.30 = 183.7296
    """
    forecast, _ = budget_forecast(build_system(fixtures_dir / "mono_a", tmp_path))
    assert forecast.total_low == pytest.approx(147.12762, **APPROX)
    assert forecast.total_expected == pytest.approx(152.90688, **APPROX)
    assert forecast.total_spike == pytest.approx(183.7296, **APPROX)
    assert not any(ln.component == "vpc-endpoints" for ln in forecast.lines)
    ips = line(forecast, "task-public-ips", "public IPv4")
    assert ips.price_ref.endswith("vpc.public_ipv4_hour") and ips.qty_expected == 2 * 730


def test_public_ip_cost_follows_the_task_count(fixtures_dir: Path, tmp_path: Path) -> None:
    """At 100 req/s: 2, 4 and 10 tasks -> 1,460 / 2,920 / 7,300 address-hours x 0.005."""
    system = build_system(fixtures_dir / "mono_a", tmp_path)
    forecast, _ = budget_forecast(system, UsageBook({"avg_requests_per_second": 100.0}))
    ips = line(forecast, "task-public-ips", "public IPv4")
    assert (ips.usd_low, ips.usd_expected, ips.usd_spike) == pytest.approx((7.30, 14.60, 36.50))


def test_scheduled_jobs_only_hold_an_address_while_they_run(
    fixtures_dir: Path, tmp_path: Path
) -> None:
    """mono_c: 5 web services x 2 tasks x 730 h plus the cron job's 1.25 hours of runtime."""
    forecast, _ = budget_forecast(build_system(fixtures_dir / "mono_c", tmp_path))
    ips = line(forecast, "task-public-ips", "public IPv4")
    assert ips.qty_expected == pytest.approx(5 * 2 * 730 + 5 * 0 + 30 * 10 / 60 * 1)
