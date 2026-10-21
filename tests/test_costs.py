"""Cost model checks against hand-computed forecasts.

Prices come from tests/fixtures/prices/ap-south-1.json: made-up round numbers (TEST ONLY), so
every figure below can be verified with a calculator. Defaults used: 1 req/s per web service,
10 KB responses, 2 KB of logs per request, 730 hours (2,628,000 s) per month, low = 0.25x and
spike = 5x traffic.

Test prices: vCPU-h 0.04, GB-h 0.005, ALB 0.02/h + 0.01/LCU-h, public IPv4 0.005/h, interface
endpoint 0.01/h + 0.01/GB, logs 0.50/GB ingested + 0.03/GB-month stored, S3 0.02/GB-month +
0.00001/PUT + 0.000001/GET, SQS 0.000001/request, secret 0.50/month + 0.00001/API call, ECR
0.10/GB-month, data out 0.10/GB, RDS postgres db.t4g.small 0.05/h single or 0.10/h Multi-AZ,
gp3 0.10 or 0.20 per GB-month, Redis cache.t4g.micro 0.02/h.
"""

from pathlib import Path

import pytest

from prodpath.forecast import UsageBook
from prodpath.models import Forecast, Prefs
from prodpath.providers.aws import AwsProvider
from prodpath.providers.aws.pricing import PriceBook
from tests.helpers import build_system, kitchen_sink_system

PRICES = Path(__file__).parent / "fixtures" / "prices"
APPROX = {"abs": 0.005}  # "within rounding": half a cent


def forecast_for(
    system,
    usage: UsageBook | None = None,
    env: str = "prod",  # type: ignore[no-untyped-def]
) -> Forecast:
    provider = AwsProvider(PRICES)
    arch = provider.choose(system, Prefs(environment=env))  # type: ignore[arg-type]
    return provider.forecast(arch, system, usage or UsageBook())


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
      -> constants 54.75 + 14.60 + 7.30 + 58.40 + 29.20 + 1.0012 + 0.40 + 0.53 = 166.1812
    Traffic-driven (api, expected): requests 2,628,000
      LCU: max(1/25, 1 x 10 x 3600 / 1e6 = 0.036) = 0.04 x 730 = 29.2 LCU-h x 0.01 = 0.292
      api logs: 5.256 GB x 0.50 = 2.628, stored 5.256 x 0.03 = 0.15768
      endpoint data: (5.256 + 1) GB x 0.01 = 0.06256; data out: 26.28 GB x 0.10 = 2.628
      -> expected 0.292 + 2.628 + 0.15768 + 0.06256 + 2.628 = 5.76824 -> total 171.94944
    Low (0.25x): LCU 0.073, logs 0.657 + 0.03942, endpoints (1.314 + 1) x 0.01 = 0.02314,
      out 0.657 -> 1.44956 -> total 167.63076
    Spike (5x): LCU 1.46, logs 13.14 + 0.7884, endpoints (26.28 + 1) x 0.01 = 0.2728, out 13.14
      -> 28.8012 -> total 194.9824
    """
    system = build_system(fixtures_dir / "mono_b", tmp_path)
    forecast = forecast_for(system)
    assert forecast.total_low == pytest.approx(167.63076, **APPROX)
    assert forecast.total_expected == pytest.approx(171.94944, **APPROX)
    assert forecast.total_spike == pytest.approx(194.9824, **APPROX)
    assert forecast.not_priced == []


def test_mono_a_matches_the_hand_computed_forecast(fixtures_dir: Path, tmp_path: Path) -> None:
    """root (web, 2 tasks), Postgres db.t4g.small Multi-AZ 20 GB, one S3 bucket, 2 secret slots.

    Constants: Fargate 29.20 + 7.30 = 36.50; ALB 14.60 + IPv4 7.30; endpoints 58.40;
      RDS 730 x 0.10 = 73.00 + 20 x 0.20 = 4.00; S3 storage 10 x 0.02 = 0.20;
      secrets (2 slots + 1 RDS-managed) 1.50 + 120 x 0.00001 = 1.5012; ECR 2 x 0.10 = 0.20
      -> 195.7012
    Traffic, expected: LCU 0.292; logs 2.628 + 0.15768; endpoint data 5.256 x 0.01 = 0.05256;
      S3 100,000 PUT x 0.00001 = 1.00 + 1,000,000 GET x 0.000001 = 1.00; data out 2.628
      -> 7.75824 -> total 203.45944
    Low: 0.073 + (0.657 + 0.03942) + 0.01314 + 0.50 + 0.657 = 1.93956 -> 197.64076
    Spike: 1.46 + (13.14 + 0.7884) + 0.2628 + 10.00 + 13.14 = 38.7912 -> 234.4924
    """
    forecast = forecast_for(build_system(fixtures_dir / "mono_a", tmp_path))
    assert forecast.total_low == pytest.approx(197.64076, **APPROX)
    assert forecast.total_expected == pytest.approx(203.45944, **APPROX)
    assert forecast.total_spike == pytest.approx(234.4924, **APPROX)


def test_mono_c_matches_the_hand_computed_forecast(fixtures_dir: Path, tmp_path: Path) -> None:
    """5 web services (2 tasks each), 1 cron job, Postgres, Redis, 3 slots, gateway calls
    billing and users through the load balancer (2 internal requests per gateway request).

    Constants: Fargate 5 x 36.50 = 182.50 + cron (1.25 vCPU-h x 0.04 + 2.5 GB-h x 0.005 = 0.0625)
      ALB 14.60 + IPv4 7.30; endpoints 58.40; RDS 77.00; Redis 29.20;
      secrets (3 + 1 managed) x 0.50 = 2.00 + 180 calls x 0.00001 = 0.0018; ECR 6 x 2 x 0.10 = 1.20;
      cron logs 0.50 + 0.03 -> 372.7943
    Traffic, expected: LCU (5 + 2 = 7 req/s: max(0.28, 0.252) = 0.28) x 730 x 0.01 = 2.044;
      web logs 5 x (2.628 + 0.15768) = 13.9284; endpoint data (26.28 + 1) x 0.01 = 0.2728;
      data out 5 x 26.28 = 131.4 GB x 0.10 = 13.14 -> 29.3852 -> total 402.1795
    Low: 0.511 + 3.4821 + 0.0757 + 3.285 = 7.3538 -> 380.1481
    Spike: 10.22 + 69.642 + 1.324 + 65.70 = 146.886 -> 519.6803
    """
    forecast = forecast_for(build_system(fixtures_dir / "mono_c", tmp_path))
    assert forecast.total_low == pytest.approx(380.1481, **APPROX)
    assert forecast.total_expected == pytest.approx(402.1795, **APPROX)
    assert forecast.total_spike == pytest.approx(519.6803, **APPROX)
    inferred = [a for a in forecast.assumptions if a.source == "inferred"]
    assert [a.name for a in inferred] == ["internal_http_calls_per_request"]
    assert "apps-gateway->apps-billing" in inferred[0].note


@pytest.fixture(params=["mono_a", "mono_b", "mono_c"])
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
    assert heavy == pytest.approx(10 * light)
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
    forecast = provider.forecast(arch, system, UsageBook())
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
