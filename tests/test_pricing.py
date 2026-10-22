"""Price extraction against synthetic offer files that mimic the real AWS structure.

The numbers are made up. Real files were inspected once (Oct 2026) to learn the structure:
usagetype carries a region prefix ("APS3-"), prices sit in terms.OnDemand[sku][term]
.priceDimensions with tiered ranges, and "Global-" SKUs hold free allowances.
"""

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from prodpath.providers.aws import pricing
from prodpath.providers.aws.pricing import (
    OFFERS,
    SPECS,
    PriceBook,
    PriceError,
    extract_offer,
    update_prices,
)

Tier = tuple[str, str, str]  # begin, end, usd


def offer(
    version: str, products: list[tuple[str, dict[str, str], list[Tier], str]]
) -> dict[str, Any]:
    """products: (sku, attributes, tiers, unit)."""
    data: dict[str, Any] = {
        "version": version,
        "publicationDate": "2000-01-01T00:00:00Z",
        "products": {},
        "terms": {"OnDemand": {}},
    }
    for sku, attrs, tiers, unit in products:
        data["products"][sku] = {"sku": sku, "attributes": attrs}
        dimensions = {}
        for index, (begin, end, usd) in enumerate(tiers):
            rate = f"{sku}.TERM.{index}"
            dimensions[rate] = {
                "rateCode": rate,
                "unit": unit,
                "beginRange": begin,
                "endRange": end,
                "pricePerUnit": {"USD": usd},
                "description": f"synthetic {sku} tier {index}",
            }
        data["terms"]["OnDemand"][sku] = {f"{sku}.TERM": {"priceDimensions": dimensions}}
    return data


FLAT = [("0", "Inf", "0.25")]


def test_region_prefixed_usagetype_matches_and_global_does_not() -> None:
    data = offer(
        "v1",
        [
            ("SKU1", {"usagetype": "APS3-Fargate-vCPU-Hours:perCPU"}, FLAT, "hours"),
            ("SKU2", {"usagetype": "Global-Fargate-vCPU-Hours:perCPU"}, FLAT, "hours"),
            ("SKU3", {"usagetype": "APS3-Fargate-vCPU-Hours:perCPU-ARM"}, FLAT, "hours"),
        ],
    )
    prices, missing = extract_offer("AmazonECS", data)
    assert prices["fargate.vcpu_hour"].ref == "AmazonECS/SKU1/SKU1.TERM.0"
    assert prices["fargate.vcpu_hour"].usd == 0.25
    assert "fargate.gb_hour" in missing  # nothing matched: reported, not guessed


def test_first_paid_tier_is_used_when_the_first_tier_is_free() -> None:
    tiers = [("0", "100", "0.0"), ("100", "10240", "0.1093"), ("10240", "Inf", "0.085")]
    data = offer(
        "v1",
        [
            (
                "DT1",
                {"usagetype": "APS3-DataTransfer-Out-Bytes", "toLocation": "External",
                 "transferType": "AWS Outbound"},
                tiers,
                "GB",
            )
        ],
    )  # fmt: skip
    prices, _ = extract_offer("AWSDataTransfer", data)
    assert prices["dt.out_gb"].usd == pytest.approx(0.1093)
    assert prices["dt.out_gb"].ref.endswith("DT1.TERM.1")


def test_ambiguous_matches_are_reported_not_guessed() -> None:
    data = offer(
        "v1",
        [
            ("A", {"usagetype": "APS3-Fargate-GB-Hours"}, FLAT, "hours"),
            ("B", {"usagetype": "APS3-Fargate-GB-Hours"}, FLAT, "hours"),
        ],
    )
    prices, missing = extract_offer("AmazonECS", data)
    assert "fargate.gb_hour" not in prices
    assert "2 matching SKUs" in missing["fargate.gb_hour"]


def elb(sku: str, operation: str, usd: str) -> tuple[str, dict[str, str], list[Tier], str]:
    attrs = {"usagetype": "APS3-LoadBalancerUsage", "operation": operation}
    return (sku, attrs, [("0", "Inf", usd)], "Hrs")


def test_attribute_filters_pick_the_right_sku() -> None:
    data = offer(
        "v1",
        [
            elb("APP", "LoadBalancing:Application", "0.0239"),
            elb("NET", "LoadBalancing:Network", "0.0239"),
            elb("GW", "LoadBalancing:Gateway", "0.0133"),
        ],
    )
    prices, _ = extract_offer("AWSELB", data)
    assert prices["alb.hour"].ref.startswith("AWSELB/APP/")


def rds(
    sku: str, usagetype: str, engine: str, usd: str, **extra: str
) -> tuple[str, dict[str, str], list[Tier], str]:
    attrs = {
        "usagetype": usagetype,
        "databaseEngine": engine,
        "licenseModel": "No license required",
        **extra,
    }
    return (sku, attrs, [("0", "Inf", usd)], "Hrs")


def test_rds_instances_storage_and_exclusions() -> None:
    data = offer(
        "v1",
        [
            rds("S1", "APS3-InstanceUsage:db.t4g.small", "PostgreSQL", "0.042"),
            rds("M1", "APS3-Multi-AZUsage:db.t4g.small", "PostgreSQL", "0.084"),
            rds("U1", "APS3-UnusedBox:db.t4g.small", "PostgreSQL", "0.042"),
            rds("X1", "APS3-ExtendedSupportYr1-InstanceUsage:db.t4g.small", "PostgreSQL", "0.9"),
            rds("A1", "APS3-InstanceUsage:db.t4g.small", "Aurora PostgreSQL", "0.5"),
            rds("B1", "APS3-InstanceUsage:db.m5.large", "Oracle", "1.0", licenseModel="BYOL"),
            rds("ST1", "APS3-RDS:GP3-Storage", "PostgreSQL", "0.131"),
            rds("ST2", "APS3-RDS:GP3-Storage", "MySQL", "0.133"),
            rds("MA", "APS3-RDS:Multi-AZ-GP3-Storage", "Any", "0.262"),
            rds("MP", "APS3-RDS:Multi-AZ-GP3-Storage", "PostgreSQL", "0.270"),
        ],
    )  # fmt: skip
    prices, _ = extract_offer("AmazonRDS", data)
    assert prices["rds.instance.postgres.db.t4g.small.single_az"].usd == 0.042
    assert prices["rds.instance.postgres.db.t4g.small.multi_az"].usd == 0.084
    assert not any("m5.large" in k for k in prices)  # BYOL excluded
    assert (
        len([k for k in prices if k.startswith("rds.instance.")]) == 2
    )  # no Unused/Extended/Aurora
    assert prices["rds.storage.gp3.single_az.postgres"].usd == 0.131
    assert prices["rds.storage.gp3.single_az.mysql"].usd == 0.133
    assert prices["rds.storage.gp3.multi_az.postgres"].usd == 0.270  # engine-specific beats "Any"
    assert prices["rds.storage.gp3.multi_az.mysql"].usd == 0.262  # falls back to "Any"


def test_elasticache_nodes_by_engine_without_extended_support() -> None:
    def node(
        sku: str, usagetype: str, engine: str, usd: str
    ) -> tuple[str, dict[str, str], list[Tier], str]:
        return (sku, {"usagetype": usagetype, "cacheEngine": engine}, [("0", "Inf", usd)], "Hrs")

    data = offer(
        "v1",
        [
            node("R", "APS3-NodeUsage:cache.t4g.micro", "Redis", "0.02"),
            node("V", "APS3-NodeUsage:cache.t4g.micro", "Valkey", "0.016"),
            node("M", "APS3-NodeUsage:cache.t4g.micro", "Memcached", "0.02"),
            node("E", "APS3-ExtendedSupportYr3-NodeUsage:cache.t4g.micro", "Redis", "0.032"),
        ],
    )
    prices, _ = extract_offer("AmazonElastiCache", data)
    assert {k: v.usd for k, v in prices.items()} == {
        "elasticache.node.redis.cache.t4g.micro": 0.02,
        "elasticache.node.valkey.cache.t4g.micro": 0.016,
        "elasticache.node.memcached.cache.t4g.micro": 0.02,
    }


def cloudfront(usagetype: str, usd: str, unit: str) -> tuple[str, dict[str, str], list[Tier], str]:
    return (f"CF-{usagetype}", {"usagetype": usagetype}, [("0", "Inf", usd)], unit)


def all_offers() -> dict[str, dict[str, Any]]:
    """One synthetic offer file per real offer, holding a SKU for every spec we model."""
    by_offer: dict[str, list[tuple[str, dict[str, str], list[Tier], str]]] = {o: [] for o in OFFERS}
    for index, spec in enumerate(SPECS):
        attrs = {"usagetype": f"APS3-{spec.suffix}"}
        for name, pattern in spec.attrs:
            attrs[name] = pattern.strip("^$").replace("\\", "")
        by_offer[spec.offer].append(
            (f"SKU{index}", attrs, [("0", "Inf", f"{index + 1}.5")], "unit")
        )
    by_offer["AmazonRDS"].append(rds("RDS1", "APS3-InstanceUsage:db.t4g.small", "MySQL", "0.04"))
    by_offer["AmazonCloudFront"].append(cloudfront("IN-DataTransfer-Out-Bytes", "0.109", "GB"))
    by_offer["AmazonCloudFront"].append(
        cloudfront("IN-Requests-Tier2-HTTPS", "0.0000012", "Requests")
    )
    by_offer["AmazonElastiCache"].append(
        (
            "EC1",
            {"usagetype": "APS3-NodeUsage:cache.t4g.micro", "cacheEngine": "Redis"},
            FLAT,
            "Hrs",
        )
    )
    return {name: offer(f"ver-{name}", products) for name, products in by_offer.items()}


def test_update_prices_downloads_every_offer_from_the_price_list_host_only(tmp_path: Path) -> None:
    served = all_offers()
    requested: list[httpx.URL] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requested.append(request.url)
        name = request.url.path.split("/")[4]  # /offers/v1.0/aws/<offer>/current/...
        return httpx.Response(200, json=served[name])

    client = httpx.Client(transport=httpx.MockTransport(respond))
    path = update_prices("ap-south-1", tmp_path, client)

    assert path == tmp_path / "ap-south-1.json"
    assert {u.host for u in requested} == {"pricing.us-east-1.amazonaws.com"}
    assert sorted(u.path.split("/")[4] for u in requested) == sorted(OFFERS)
    regional = [u for u in requested if "AmazonCloudFront" not in u.path]
    assert all(u.path.endswith("/current/ap-south-1/index.json") for u in regional)
    (cloudfront_url,) = [u for u in requested if "AmazonCloudFront" in u.path]
    assert cloudfront_url.path == "/offers/v1.0/aws/AmazonCloudFront/current/index.json"  # global
    book = PriceBook.load(path)
    assert book.missing == {}
    assert book.get("fargate.vcpu_hour") is not None
    assert book.get("rds.instance.mysql.db.t4g.small.single_az").usd == 0.04  # type: ignore[union-attr]
    assert book.offers["AmazonECS"]["version"] == "ver-AmazonECS"
    assert not list(tmp_path.glob("*.tmp"))  # written atomically


def test_update_prices_reports_the_failing_offer(tmp_path: Path) -> None:
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(404)))
    with pytest.raises(PriceError, match=r"could not download \w+ for ap-south-1"):
        update_prices("ap-south-1", tmp_path, client)
    assert not list(tmp_path.glob("*.json"))  # no half-written snapshot


def test_price_book_errors_are_actionable(tmp_path: Path) -> None:
    with pytest.raises(PriceError, match="prodpath prices update"):
        PriceBook.load(tmp_path / "missing.json")
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    with pytest.raises(PriceError, match="not a valid price snapshot"):
        PriceBook.load(broken)
    wrong = tmp_path / "wrong.json"
    wrong.write_text(json.dumps({"schema_version": 99}), encoding="utf-8")
    with pytest.raises(PriceError, match="unsupported schema_version"):
        PriceBook.load(wrong)


def test_the_price_list_host_is_the_only_destination_in_the_module() -> None:
    assert pricing.PRICE_LIST_URL.startswith("https://pricing.us-east-1.amazonaws.com/")


def test_committed_test_snapshot_is_clearly_labelled_and_loadable() -> None:
    book = PriceBook.load(Path(__file__).parent / "fixtures" / "prices" / "ap-south-1.json")
    assert book.count >= 30
    assert all(p.description.startswith("TEST ONLY") for p in book._prices.values())


def test_cloudfront_prices_are_keyed_by_edge_geography_and_use_the_first_paid_tier() -> None:
    def priced(
        usagetype: str, tiers: list[Tier], unit: str
    ) -> tuple[str, dict[str, str], list[Tier], str]:
        return (f"S-{usagetype}", {"usagetype": usagetype}, tiers, unit)

    data = offer(
        "v1",
        [
            priced(
                "IN-DataTransfer-Out-Bytes",
                [("0", "10240", "0.109"), ("10240", "51200", "0.085")],
                "GB",
            ),
            priced("IN-Requests-Tier2-HTTPS", [("0", "Inf", "0.0000012")], "Requests"),
            priced("US-DataTransfer-Out-Bytes", [("0", "10240", "0.085")], "GB"),
            priced("Global-DataTransfer-Out-Bytes", [("0", "1024", "0.0")], "GB"),
            priced("APS3-Requests-OriginShield", [("0", "Inf", "0.0000009")], "Requests"),
            priced("IN-Requests-Tier2-HTTP", [("0", "Inf", "0.0000010")], "Requests"),
        ],
    )
    prices, missing = extract_offer("AmazonCloudFront", data)
    assert {k: v.usd for k, v in prices.items()} == {
        "cloudfront.out_gb.in": 0.109,
        "cloudfront.requests_https.in": 0.0000012,
        "cloudfront.out_gb.us": 0.085,
    }  # no Global free tier, no Origin Shield, no plain-HTTP requests
    assert missing == {}
    assert (
        prices["cloudfront.out_gb.in"].ref
        == "AmazonCloudFront/S-IN-DataTransfer-Out-Bytes/S-IN-DataTransfer-Out-Bytes.TERM.0"
    )
