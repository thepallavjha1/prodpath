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


class Prefs(BaseModel):  # user choices for "choose" (CLI flags)
    provider: Literal["aws"] = "aws"
    region: str = "ap-south-1"
    environment: Literal["prod", "nonprod"] = "prod"  # prod: Multi-AZ data stores, 2 tasks


class Component(BaseModel):
    type: str  # "vpc", "ecs-service-web", "rds", ... (provider vocabulary)
    name: str  # stable and unique, e.g. "rds-postgres"
    sizing: str  # a default starting point; says so when not derived from code
    reason: str  # shown in the plan, never empty
    serves: list[str]  # service ids
    evidence: list[Evidence] = []  # triggering facts; empty only for account-level pieces
    items: list[
        str
    ] = []  # for humans and steps: "port:8000", "health:/x", "env:NAME", secret names
    params: dict[str, str] = {}  # machine-readable sizing for templates (cpu, memory, engine...)

    @field_validator("reason")
    @classmethod
    def _reason_not_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("a Component needs a reason")
        return value


class Architecture(BaseModel):  # provider-specific output of "choose"
    schema_version: int = SCHEMA_VERSION
    provider: str
    region: str
    environment: str
    components: list[Component]
    unknowns: list[str] = []  # what the tool could not determine; listed in the plan


class Step(BaseModel):  # one ordered deployment step in PLAN.md
    id: str
    title: str
    why: str
    commands: list[str]  # AWS CLI / shell with <PLACEHOLDERS>; no credentials, no account ids
    verify: str
    components: list[str]  # component names this step creates


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


class Claim(BaseModel):
    text: str = Field(max_length=200)
    # The model cites ids like "F3" from its prompt; code drops unknown ids and replaces the
    # rest with "path:line" references, so stored summaries point at real evidence.
    evidence_ids: list[str]


class ServiceSummary(BaseModel):
    service_id: str  # forced to the input id by code
    purpose: str = Field(max_length=200)
    role: Literal["web", "worker", "cron", "static", "lib", "unknown"]
    risks: list[Claim] = []
    hot_path: Claim | None = None
    generated_by: Literal["llm", "rule"] = "llm"  # set by code
    dropped_claims: int = 0  # set by code: claims removed for missing/unknown evidence ids


class SystemClaim(BaseModel):
    text: str = Field(max_length=300)
    service_ids: list[str]  # must exist in the input


class SystemSummary(BaseModel):
    overview: str = Field(max_length=600)
    key_risks: list[SystemClaim] = []
    omitted_services: int = 0  # set by code when the reduce input was trimmed to budget


class Summaries(BaseModel):  # .prodpath/summaries.json
    schema_version: int = SCHEMA_VERSION
    model: str
    services: list[ServiceSummary]
    system: SystemSummary


class Forecast(BaseModel):  # stage 6 output
    schema_version: int = SCHEMA_VERSION
    provider: str
    region: str
    lines: list[CostLine]
    total_low: float
    total_expected: float
    total_spike: float
    assumptions: list[UsageAssumption]  # only those actually used, each with its source
    not_priced: list[str]  # planned components or dimensions with no price in the snapshot
    not_included: list[str]  # costs deliberately outside the model
    price_snapshot: str  # region, fetch date and offer versions
