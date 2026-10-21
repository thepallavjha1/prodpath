# FIXED CONTRACTS: these cross stage boundaries. Change them only after updating
# docs/ARCHITECTURE.md section 5 and adding an ADR.
from typing import Literal

from pydantic import BaseModel, Field, field_validator

SCHEMA_VERSION = 1


class Evidence(BaseModel):
    path: str  # repo-relative
    line: int | None = None
    snippet: str = Field(max_length=200)  # never a secret value


FactKind = Literal[
    "runtime",
    "framework",
    "port",
    "env_var",
    "datastore",
    "queue",
    "cache",
    "object_store",
    "external_call",
    "worker",
    "schedule",
    "health_endpoint",
    "local_state",
    "dependency",
]


class Fact(BaseModel):
    kind: FactKind
    value: str  # e.g. "postgres", "FLASK_SECRET", "8080"
    evidence: list[Evidence]
    # parsed = read from a manifest/AST; heuristic = pattern match
    certainty: Literal["parsed", "heuristic"]

    @field_validator("evidence")
    @classmethod
    def _evidence_not_empty(cls, value: list[Evidence]) -> list[Evidence]:
        # ADR-009: no evidence, no fact.
        if not value:
            raise ValueError("a Fact needs at least one Evidence")
        return value


class Service(BaseModel):
    id: str  # stable slug from root path
    root: str
    kind: Literal["web", "worker", "cron", "static", "lib", "unknown"]
    facts: list[Fact] = []


class Edge(BaseModel):
    src: str
    dst: str  # service ids or shared-infra ids
    via: Literal["http", "queue", "db", "cache", "storage"]
    evidence: list[Evidence]


class SystemModel(BaseModel):
    schema_version: int = SCHEMA_VERSION
    services: list[Service]
    edges: list[Edge] = []
    shared_infra: list[Fact] = []  # datastores/queues used by more than one service
    not_analyzed: list[str] = []  # skipped/unparsable files and exclusions


class UsageAssumption(BaseModel):
    name: str
    value: float
    unit: str
    source: Literal["user", "default", "inferred"]
    note: str = ""


class Usage(BaseModel):  # forecast inputs
    assumptions: list[UsageAssumption]


class Component(BaseModel):
    type: str
    name: str
    sizing: str
    reason: str  # shown in the plan
    serves: list[str]  # service ids


class Architecture(BaseModel):  # provider-specific output of "choose"
    schema_version: int = SCHEMA_VERSION
    provider: str
    region: str
    components: list[Component]


class CostLine(BaseModel):
    component: str
    dimension: str
    unit: str
    qty_low: float
    qty_expected: float
    qty_spike: float
    unit_price: float
    price_ref: str  # SKU/offer id in the snapshot
    usd_low: float
    usd_expected: float
    usd_spike: float

    @field_validator("price_ref")
    @classmethod
    def _price_ref_not_empty(cls, value: str) -> str:
        if not value:
            raise ValueError("a CostLine needs a price_ref")
        return value


class Trap(BaseModel):
    id: str
    severity: Literal["high", "medium", "low"]
    where: str
    why: str
    fix: str
    est_monthly_usd_impact: float | None = None


class FileEntry(BaseModel):
    path: str  # repo-relative, posix separators
    hash: str  # blake2b hex; "" when skipped
    size: int
    language: str | None = None
    skipped: str | None = None  # reason; skipped files are listed, not hidden


class Inventory(BaseModel):
    schema_version: int = SCHEMA_VERSION
    files: list[FileEntry]  # sorted by path


class ServiceCandidate(BaseModel):
    id: str  # slug of root ("." -> "root", "apps/web" -> "apps-web")
    root: str
    kind: Literal["web", "worker", "cron", "static", "lib", "unknown"]
    certainty: Literal["parsed", "heuristic"]
    evidence: list[Evidence]  # the rule that matched

    @field_validator("evidence")
    @classmethod
    def _evidence_not_empty(cls, value: list[Evidence]) -> list[Evidence]:
        if not value:
            raise ValueError("a ServiceCandidate needs at least one Evidence")
        return value
