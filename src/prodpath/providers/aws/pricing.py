"""AWS Price List: download (explicit `prices update` only), extract, and read the snapshot.

This is the ONLY module that talks to the network (host pricing.us-east-1.amazonaws.com), and
only from `update_prices`. Everything else reads the compact snapshot it writes. Prices are
on-demand, first paid tier; free tiers, reserved pricing and volume discounts are ignored.
A dimension that cannot be found or matched uniquely goes to `missing`, never guessed.
"""

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

PRICE_LIST_URL = (
    "https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/{offer}/current/{region}/index.json"
)
# CloudFront prices (data out, HTTPS requests) are in one global file keyed by edge geography;
# the per-region file only holds Origin Shield and Lambda@Edge.
GLOBAL_OFFERS = {"AmazonCloudFront"}
GLOBAL_URL = "https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/{offer}/current/index.json"
EDGE_GEOGRAPHIES = "IN|US|EU|AP|AU|CA|JP|ME|SA|ZA"
DEFAULT_PRICE_DIR = Path.home() / ".cache" / "prodpath" / "prices"
SNAPSHOT_VERSION = 1
TIMEOUT_SECONDS = 600.0
ENGINES = {"PostgreSQL": "postgres", "MySQL": "mysql"}
CACHE_ENGINES = {"Redis": "redis", "Valkey": "valkey", "Memcached": "memcached"}
# usagetype prefix is the region code ("APS3-"); "Global-" has lowercase letters and never matches.
PREFIX = r"^[A-Z0-9]+-"


class PriceError(Exception):
    """The price snapshot is missing, unreadable or could not be built."""


@dataclass(frozen=True)
class Price:
    ref: str  # "<offer>/<sku>/<rateCode>", auditable against the public file
    usd: float
    unit: str
    description: str


@dataclass(frozen=True)
class Spec:
    key: str
    offer: str
    suffix: str  # usagetype without the region prefix
    attrs: tuple[tuple[str, str], ...] = ()  # product attribute -> regex that must match


_ALB = (("operation", "^LoadBalancing:Application$"),)
SPECS = [
    Spec("fargate.vcpu_hour", "AmazonECS", "Fargate-vCPU-Hours:perCPU"),
    Spec("fargate.gb_hour", "AmazonECS", "Fargate-GB-Hours"),
    Spec("alb.hour", "AWSELB", "LoadBalancerUsage", _ALB),
    Spec("alb.lcu_hour", "AWSELB", "LCUUsage", _ALB),
    Spec("vpc.public_ipv4_hour", "AmazonVPC", "PublicIPv4:InUseAddress"),
    Spec("vpc.endpoint_hour", "AmazonVPC", "VpcEndpoint-Hours", (("operation", "^VpcEndpoint$"),)),
    Spec("vpc.endpoint_gb", "AmazonVPC", "VpcEndpoint-Bytes"),
    Spec("cloudwatch.logs_ingest_gb", "AmazonCloudWatch", "DataProcessing-Bytes",
         (("operation", "^PutLogEvents$"), ("group", "^Ingested Logs$"))),
    Spec("cloudwatch.alarm_month", "AmazonCloudWatch", "CW:AlarmMonitorUsage"),
    Spec("cloudwatch.logs_storage_gb_month", "AmazonCloudWatch", "TimedStorage-ByteHrs",
         (("group", "Standard Storage"),)),
    Spec("s3.storage_gb_month", "AmazonS3", "TimedStorage-ByteHrs",
         (("storageClass", "^General Purpose$"), ("volumeType", "^Standard$"))),
    Spec("s3.put_request", "AmazonS3", "Requests-Tier1"),
    Spec("s3.get_request", "AmazonS3", "Requests-Tier2"),
    Spec("sqs.request", "AWSQueueService", "Requests-Tier1"),
    Spec("secrets.secret_month", "AWSSecretsManager", "AWSSecretsManager-Secrets"),
    Spec("secrets.api_request", "AWSSecretsManager", "AWSSecretsManagerAPIRequest"),
    Spec("ecr.storage_gb_month", "AmazonECR", "TimedStorage-ByteHrs"),
    Spec("dt.out_gb", "AWSDataTransfer", "DataTransfer-Out-Bytes",
         (("toLocation", "^External$"), ("transferType", "^AWS Outbound$"))),
]  # fmt: skip
OFFERS = sorted({spec.offer for spec in SPECS} | {"AmazonRDS", "AmazonElastiCache", *GLOBAL_OFFERS})


def _first_paid_price(offer: str, data: dict[str, Any], sku: str) -> Price | None:
    """The first tier with a non-zero price (or the first tier if all are free)."""
    tiers = []
    for term in data["terms"].get("OnDemand", {}).get(sku, {}).values():
        for dim in term["priceDimensions"].values():
            tiers.append((float(dim["beginRange"]), dim))
    if not tiers:
        return None
    tiers.sort(key=lambda t: t[0])
    chosen = next((d for _, d in tiers if float(d["pricePerUnit"].get("USD", 0)) > 0), tiers[0][1])
    return Price(
        ref=f"{offer}/{sku}/{chosen['rateCode']}",
        usd=float(chosen["pricePerUnit"]["USD"]),
        unit=chosen["unit"],
        description=chosen["description"][:120],
    )


def _spec_matches(spec: Spec, attrs: dict[str, str]) -> bool:
    if not re.match(rf"{PREFIX}{re.escape(spec.suffix)}$", attrs.get("usagetype", "")):
        return False
    return all(re.search(pattern, attrs.get(name, "")) for name, pattern in spec.attrs)


def _extract_specs(offer: str, data: dict[str, Any]) -> tuple[dict[str, Price], dict[str, str]]:
    specs = [s for s in SPECS if s.offer == offer]
    found: dict[str, list[tuple[str, dict[str, str]]]] = {s.key: [] for s in specs}
    for sku, product in data["products"].items():
        attrs = product.get("attributes", {})
        for spec in specs:
            if _spec_matches(spec, attrs):
                found[spec.key].append((sku, attrs))
    prices: dict[str, Price] = {}
    missing: dict[str, str] = {}
    for key, candidates in found.items():
        if len(candidates) != 1:
            missing[key] = f"{len(candidates)} matching SKUs in {offer} (need exactly 1)"
            continue
        price = _first_paid_price(offer, data, candidates[0][0])
        if price is None:
            missing[key] = f"SKU {candidates[0][0]} has no on-demand price"
        else:
            prices[key] = price
    return prices, missing


def _extract_rds(data: dict[str, Any]) -> dict[str, Price]:
    prices: dict[str, Price] = {}
    storage: dict[str, dict[str, str]] = {}  # key -> {engine attr -> sku}
    for sku, product in data["products"].items():
        attrs = product.get("attributes", {})
        usage, engine = attrs.get("usagetype", ""), attrs.get("databaseEngine", "")
        if attrs.get("licenseModel", "No license required") != "No license required":
            continue
        instance = re.match(rf"{PREFIX}(InstanceUsage|Multi-AZUsage):(db\.[a-z0-9.]+)$", usage)
        if instance and engine in ENGINES:
            deployment = "multi_az" if instance.group(1) == "Multi-AZUsage" else "single_az"
            key = f"rds.instance.{ENGINES[engine]}.{instance.group(2)}.{deployment}"
            if (price := _first_paid_price("AmazonRDS", data, sku)) is not None:
                prices[key] = price
        gp3 = re.match(rf"{PREFIX}RDS:(Multi-AZ-)?GP3-Storage$", usage)
        if gp3 and (engine in ENGINES or engine == "Any"):
            deployment = "multi_az" if gp3.group(1) else "single_az"
            for name in ENGINES.values():
                storage.setdefault(f"rds.storage.gp3.{deployment}.{name}", {})[engine] = sku
    for key, by_engine in storage.items():
        engine_name = key.rsplit(".", 1)[1]
        wanted = next((e for e, n in ENGINES.items() if n == engine_name), "")
        sku = by_engine.get(wanted) or by_engine.get("Any")
        if sku and (price := _first_paid_price("AmazonRDS", data, sku)) is not None:
            prices[key] = price
    return prices


def _extract_elasticache(data: dict[str, Any]) -> dict[str, Price]:
    prices: dict[str, Price] = {}
    for sku, product in data["products"].items():
        attrs = product.get("attributes", {})
        node = re.match(rf"{PREFIX}NodeUsage:(cache\.[a-z0-9.]+)$", attrs.get("usagetype", ""))
        engine = CACHE_ENGINES.get(attrs.get("cacheEngine", ""))
        if node and engine:
            price = _first_paid_price("AmazonElastiCache", data, sku)
            if price is not None:
                prices[f"elasticache.node.{engine}.{node.group(1)}"] = price
    return prices


def _extract_cloudfront(data: dict[str, Any]) -> dict[str, Price]:
    """cloudfront.out_gb.<geo> and cloudfront.requests_https.<geo>, e.g. geo = in, us, eu."""
    keys = {"DataTransfer-Out-Bytes": "out_gb", "Requests-Tier2-HTTPS": "requests_https"}
    pattern = rf"^({EDGE_GEOGRAPHIES})-(DataTransfer-Out-Bytes|Requests-Tier2-HTTPS)$"
    prices: dict[str, Price] = {}
    for sku, product in data["products"].items():
        match = re.match(pattern, product.get("attributes", {}).get("usagetype", ""))
        if match and (price := _first_paid_price("AmazonCloudFront", data, sku)) is not None:
            prices[f"cloudfront.{keys[match.group(2)]}.{match.group(1).lower()}"] = price
    return prices


def extract_offer(offer: str, data: dict[str, Any]) -> tuple[dict[str, Price], dict[str, str]]:
    """All prices we model from one offer file, plus the keys that could not be resolved."""
    prices, missing = _extract_specs(offer, data)
    if offer == "AmazonRDS":
        prices.update(_extract_rds(data))
    if offer == "AmazonElastiCache":
        prices.update(_extract_elasticache(data))
    if offer == "AmazonCloudFront":
        prices.update(_extract_cloudfront(data))
    return prices, missing


def offer_url(offer: str, region: str) -> str:
    if offer in GLOBAL_OFFERS:
        return GLOBAL_URL.format(offer=offer)
    return PRICE_LIST_URL.format(offer=offer, region=region)


def snapshot_path(directory: Path, region: str) -> Path:
    return directory / f"{region}.json"


def update_prices(region: str, directory: Path, client: httpx.Client | None = None) -> Path:
    """Download every offer for the region, write the compact snapshot, return its path."""
    client = client or httpx.Client(timeout=TIMEOUT_SECONDS, follow_redirects=True)
    prices: dict[str, Price] = {}
    missing: dict[str, str] = {}
    offers: dict[str, dict[str, str]] = {}
    for offer in OFFERS:
        url = offer_url(offer, region)
        try:
            response = client.get(url)
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPError as error:
            raise PriceError(f"could not download {offer} for {region}: {error}") from error
        offer_prices, offer_missing = extract_offer(offer, data)
        prices.update(offer_prices)
        missing.update(offer_missing)
        offers[offer] = {
            "version": str(data.get("version", "")),
            "published": str(data.get("publicationDate", "")),
        }
        del data  # the RDS file alone is ~20 MB of JSON; do not hold several at once
    snapshot = {
        "schema_version": SNAPSHOT_VERSION,
        "region": region,
        "fetched_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "offers": offers,
        "prices": {
            key: {"ref": p.ref, "usd": p.usd, "unit": p.unit, "description": p.description}
            for key, p in sorted(prices.items())
        },
        "missing": dict(sorted(missing.items())),
    }
    directory.mkdir(parents=True, exist_ok=True)
    target = snapshot_path(directory, region)
    temporary = target.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    temporary.replace(target)
    return target


class PriceBook:
    """Read-only view of a snapshot."""

    def __init__(self, snapshot: dict[str, Any]) -> None:
        self.region: str = snapshot["region"]
        self.fetched_at: str = snapshot["fetched_at"]
        self.offers: dict[str, dict[str, str]] = snapshot["offers"]
        self.missing: dict[str, str] = snapshot.get("missing", {})
        self._prices: dict[str, Price] = {
            key: Price(v["ref"], float(v["usd"]), v["unit"], v["description"])
            for key, v in snapshot["prices"].items()
        }

    @classmethod
    def load(cls, path: Path) -> "PriceBook":
        try:
            snapshot = json.loads(path.read_text(encoding="utf-8"))
            if snapshot.get("schema_version") != SNAPSHOT_VERSION:
                raise PriceError(f"{path} has an unsupported schema_version")
            return cls(snapshot)
        except FileNotFoundError as error:
            raise PriceError(
                f"no price snapshot at {path}. Run `prodpath prices update --region <region>` once "
                "(the only networked command; it downloads the public AWS Price List)."
            ) from error
        except (json.JSONDecodeError, KeyError) as error:
            raise PriceError(f"{path} is not a valid price snapshot: {error!r}") from error

    def get(self, key: str) -> Price | None:
        return self._prices.get(key)

    @property
    def count(self) -> int:
        return len(self._prices)

    def refs(self) -> set[str]:
        return {p.ref for p in self._prices.values()}

    def describe(self) -> str:
        versions = ", ".join(f"{o} {v['version']}" for o, v in sorted(self.offers.items()))
        return f"AWS Price List, region {self.region}, fetched {self.fetched_at} ({versions})"
