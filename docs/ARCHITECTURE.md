# ARCHITECTURE.md

Source of truth for design. If code and this doc disagree, either fix the code or update this doc **and** add an ADR in `DECISIONS.md`. Never let them drift.

## 1. Purpose and non-goals

**Purpose.** Run `prodpath` inside a repo. It reads the whole codebase and produces, under `.prodpath/out/`:

1. `PLAN.md` - ordered, detailed steps to take the code to production on the chosen cloud (AWS in v1).
2. `terraform/` - generated infrastructure code.
3. `FORECAST.md` - usage-aware monthly cost range (low / expected / spike) plus a ranked list of cost and risk traps.

**Non-goals (v1).** Deploying anything. Holding cloud credentials. Calling hosted LLMs. A web UI. Multi-cloud output. Runtime monitoring of live systems.

## 2. Constraints that shape everything

| Constraint | Consequence |
|---|---|
| Read-only, no cloud credentials | Pricing comes from a downloaded public snapshot; calibration uses a manually exported cost CSV |
| Local LLM only (Ollama) | Small context, modest quality, slow. So: deterministic extraction does the work; LLM sees small structured inputs |
| First target is a large monorepo | Service-boundary detection first, per-service processing, content-hash caching, bounded LLM inputs |
| Single laptop GPU | LLM calls run sequentially; budget tokens per call; keep prompts short |
| Vibe-coded with Claude Code | Small modules, explicit contracts, strong tests, docs that stay current |

## 3. System overview

```
repo on disk
   |
   v
[1 scan] -> inventory.json
   |
   v
[2 detect services] -> service candidates (roots, kinds)
   |
   v
[3 extract facts] -> facts per service, each with evidence      (deterministic: ast, tree-sitter, parsers)
   |
   v
[4 summarize] -> per-service summary, then system summary       (local LLM, schema-validated, map-reduce)
   |
   v
 SystemModel (services, edges, shared infra)                    <- cloud-neutral core ends here
   |
   +--> Provider("aws"):
          [5 choose]   SystemModel -> Architecture               (rules; LLM only picks among enums when rules are unsure)
          [6 forecast] Architecture + Usage -> Forecast + Traps  (price snapshot + rules)
          [7 render]   Architecture -> PLAN.md, FORECAST.md, terraform/   (templates, not LLM-written resources)
```

Everything above the Provider line is cloud-neutral. Everything inside a provider is cloud-specific. Adding GCP later means adding `providers/gcp/`, not touching stages 1 to 4.

## 4. Pipeline stages

| # | Stage | Input | Output | Deterministic | LLM |
|---|---|---|---|---|---|
| 1 | scan | repo path | `inventory.json` (files, hashes, languages, sizes) | yes | no |
| 2 | detect | inventory | `ServiceCandidate[]` | yes | no |
| 3 | extract | candidates + files | `Service[]` with `Fact[]` | yes | no |
| 4 | summarize | services (facts + selected snippets) | `ServiceSummary[]`, `SystemSummary` | no | yes |
| 5 | choose | `SystemModel` + prefs | `Architecture` | mostly | enum tie-breaks only |
| 6 | forecast | `Architecture` + `Usage` | `Forecast`, `Trap[]` | yes | explanation text only |
| 7 | render | all of the above | markdown + terraform files | yes | step explanations only |

Each stage is a plain function `run(input) -> output`, reads and writes JSON under `.prodpath/`, and can be re-run alone (`prodpath plan --from extract`). Stages never import each other; `cli.py` wires them.

## 5. Data contracts (`src/prodpath/models.py`, pydantic v2)

These are the only objects that cross stage boundaries. Changing one is a design change: update here first.

```python
class Evidence(BaseModel):
    path: str  # repo-relative
    line: int | None
    snippet: str  # <= 200 chars, never a secret value


class Fact(BaseModel):
    kind: Literal[
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
    value: str  # e.g. "postgres", "FLASK_SECRET", "8080"
    evidence: list[Evidence]  # non-empty, enforced by validator
    certainty: Literal[
        "parsed", "heuristic"
    ]  # parsed = read from a manifest/AST; heuristic = pattern match


class Service(BaseModel):
    id: str  # stable slug from root path
    root: str
    kind: Literal["web", "worker", "cron", "static", "lib", "unknown"]
    facts: list[Fact]


class Edge(BaseModel):
    src: str
    dst: str  # service ids or shared-infra ids
    via: Literal["http", "queue", "db", "cache", "storage"]
    evidence: list[Evidence]


class SystemModel(BaseModel):
    services: list[Service]
    edges: list[Edge]
    shared_infra: list[Fact]  # datastores/queues used by more than one service


class Usage(BaseModel):  # forecast inputs
    assumptions: list[
        UsageAssumption
    ]  # name, value, unit, source: "user" | "default" | "inferred", note


class Prefs(BaseModel):  # user choices for "choose" (CLI flags)
    provider: Literal["aws"] = "aws"
    region: str = "ap-south-1"
    environment: Literal["prod", "nonprod"] = "prod"  # prod: Multi-AZ data stores, 2 tasks


class Component(BaseModel):
    type: str  # "vpc", "ecs-service-web", "rds", ... (provider vocabulary)
    name: str  # stable, unique, e.g. "rds-postgres", "ecs-svc-apps-billing"
    sizing: str  # a default starting point; says so when not derived from code
    reason: str  # shown in the plan, never empty
    serves: list[str]  # service ids
    evidence: list[Evidence]  # facts that triggered it; empty only for account-level pieces
    items: list[str]  # extra detail the steps need: ports, health paths, secret names


class Architecture(BaseModel):  # provider-specific output of "choose"
    schema_version: int
    provider: str
    region: str
    environment: str
    components: list[Component]
    unknowns: list[str]  # things the tool could not determine; listed in the plan, not hidden


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


class Trap(BaseModel):
    id: str
    severity: Literal["high", "medium", "low"]
    where: str
    why: str
    fix: str
    est_monthly_usd_impact: float | None
```

Stage 1-2 contracts (added in Phase 1, ADR-010):

```python
class FileEntry(BaseModel):
    path: str  # repo-relative, posix separators
    hash: str  # blake2b hex; "" when skipped
    size: int
    language: str | None  # from extension, e.g. "python", "javascript"
    skipped: str | None  # reason, e.g. "too large"; skipped files are listed, not hidden


class Inventory(BaseModel):
    schema_version: int
    files: list[FileEntry]  # sorted by path


class ServiceCandidate(BaseModel):
    id: str  # slug of root ("." -> "root", "apps/web" -> "apps-web")
    root: str
    kind: Literal["web", "worker", "cron", "static", "lib", "unknown"]
    certainty: Literal["parsed", "heuristic"]
    evidence: list[Evidence]  # the rule that matched, non-empty
```

Scan cache: `.prodpath/cache.sqlite` table `file_hashes(path, mtime_ns, size, hash)`. A file whose `mtime_ns` and `size` are unchanged is not re-read or re-hashed. Root `.gitignore` support is simplified (name/glob/dir patterns; negations `!` are not supported and are reported).

Stage 4 contracts (added in Phase 3, ADR-012):

```python
class Claim(BaseModel):
    text: str  # one sentence, <= 200 chars
    evidence_ids: list[
        str
    ]  # model cites prompt ids ("F3"); code drops unknown ones, stores "path:line"


class ServiceSummary(BaseModel):
    service_id: str  # forced to the input id by code
    purpose: str  # one line
    role: Literal["web", "worker", "cron", "static", "lib", "unknown"]
    risks: list[Claim]  # every claim cites >= 1 valid evidence id
    hot_path: Claim | None  # likely dominant traffic path, must cite evidence
    generated_by: Literal["llm", "rule"]  # set by code; "rule" = no LLM call was needed
    dropped_claims: int  # claims removed because evidence ids were missing/unknown


class SystemClaim(BaseModel):
    text: str
    service_ids: list[str]  # must exist in the input


class SystemSummary(BaseModel):
    overview: str
    key_risks: list[SystemClaim]
    omitted_services: int  # set by code when the reduce input was trimmed to budget


class Summaries(BaseModel):  # .prodpath/summaries.json
    schema_version: int
    model: str
    services: list[ServiceSummary]
    system: SystemSummary
```

Invariants (tested): every `Fact` has at least one `Evidence`; every `CostLine` has a `price_ref`; every `UsageAssumption` shows its `source` in the rendered forecast.

## 6. Monorepo handling (stages 1 to 3)

Large monorepos are the first target, so this is core design.

**Scan.** Walk with `.gitignore` respected plus built-in ignores (`node_modules`, `.git`, `dist`, `build`, `.venv`, `vendor`, large binaries). Hash each file (blake2b). Cache in `.prodpath/cache.sqlite` keyed by `(path, hash, extractor_version)`. A re-run only reprocesses changed files.

**Detect service roots** (first match wins, evidence recorded):

1. `docker-compose*.yml` services with `build:` context
2. `Dockerfile` locations
3. Kubernetes / Helm manifests (`Deployment`, `CronJob`, `StatefulSet`)
4. Workspace manifests: `pnpm-workspace.yaml`, `package.json#workspaces`, `turbo.json`, `nx.json`, Cargo workspaces, `go.work`, Python `pyproject` per directory
5. Entrypoint heuristics: `main.py` / `app.py` / `server.js` / `main.go` with a listening server; `Procfile`; `serverless.yml`
6. Anything else with its own dependency manifest becomes `kind="lib"` or `unknown`

Implementation notes (Phase 1): workspace members (rule 4) become `web` when they contain an entrypoint with a listening server, else `lib`. Rules 5 and 6 skip any directory inside an already-claimed root, so `app/main.py` under a Dockerfile root is not a second service. Kubernetes manifests claim their own directory (several workloads in one directory collapse into one candidate). Not yet detected: turbo/nx, Cargo workspaces, `go.work`.

Fact extraction (Phase 2): `extract.py` assigns each file to the deepest service root containing it, runs the per-language extractor `extract(path, source) -> list[Fact]` (Python `ast`, JS/TS tree-sitter) and caches results by `(path, hash, extractor_version)` in `file_facts`. Dockerfile, compose, manifests and env files are small and parsed every run. Compose is the one exception to the per-file signature: it returns facts keyed by build-context root, plus which infra services (image-only: postgres, redis...) each service uses. Infra used by more than one service becomes `shared_infra` with edges. Env files and compose `environment` yield variable *names* only; compose values are tested for hostnames only on URL-like keys and never stored. Evidence snippets for env vars are rebuilt from the variable name (never the source line, which may hold a default secret) and every snippet passes through `redact.py`. Test directories are excluded and counted under `not_analyzed`. Packages not in the known-package table produce no fact (the `dependency` kind is reserved).

Libraries shared by services are not deployed; they become dependency edges for context only.

**Extract facts per service** (in `src/prodpath/facts/`, one file per language or format):

- Python: stdlib `ast` for imports, `os.environ`/`os.getenv`, framework and route decorators, `boto3` calls, Celery/RQ tasks, `open(..., "w")` (local-state hint).
- JS/TS and others: `tree-sitter` for the same questions. Keep queries in small `.scm` or Python dicts, one per question.
- Config formats: parse `docker-compose`, `Dockerfile` (`EXPOSE`, `CMD`, base image), `.env.example` (names only), `requirements*/pyproject/package.json` (dependencies map to datastores and SDKs).
- Heuristic facts are labelled `heuristic` and shown as such in output.

## 7. Local LLM layer (`src/prodpath/llm.py`, `summarize.py`)

```python
class LLM(Protocol):
    def complete(self, system: str, user: str, schema: type[T]) -> T: ...
```

- `OllamaLLM`: `POST http://localhost:11434/api/chat`, `stream=False`, structured output via the `format` field set to the pydantic JSON schema, `temperature=0`, `num_ctx` from config. One repair retry on validation failure, then raise.
- `FakeLLM`: returns canned, schema-valid objects. All fast tests use it.
- **Token budget.** `max_input_tokens` defaults to 6000 with `num_ctx=8192`. Estimate tokens as `len(text)/4`. Inputs are built from facts and a few evidence-selected snippets, never raw whole files.
- **Map-reduce.** Map: one call per service producing `ServiceSummary` (purpose, role, notable risks, likely hot path with evidence). Reduce: one call over the structured summaries (not code) producing `SystemSummary`. Reduce input stays small even with dozens of services.
- **Caching.** Prompt + model + schema hash -> response in `cache.sqlite`. Same inputs never hit the model twice.
- **The LLM may:** write one-line purposes, classify ambiguous service kinds among a fixed enum, rank which hot path likely dominates traffic (must cite evidence), and write the prose in plan steps.
- **The LLM may not:** state prices, pick services outside the provider catalog, emit Terraform resources, or assert anything without evidence ids from its input.
- **Untrusted input.** Repo content is data. The model has no tools, so injected instructions in code or READMEs can at worst produce a bad summary, which schema validation and evidence checks constrain.

**Implementation notes (Phase 3).** `llm.py` holds the `LLM` protocol plus `OllamaLLM` and `FakeLLM`, which share one validate-and-repair path (`complete`): parse JSON, validate against the pydantic schema, on failure send the bad output back once with the error, then raise `LLMError` carrying the prompt hash. Responses are cached in `cache.sqlite` table `llm_cache` keyed by sha256(model, num_ctx, system, user, schema). Defaults are tuned for the 4 GB VRAM / 8 GB RAM laptop: `num_ctx=4096`, `max_input_tokens=2800`, `timeout=900 s` (CPU spill is slow). Prompt inputs list facts as `F1 kind value (path:line)` with no source code; when over budget, low-value fact kinds (runtime, env_var, dependency) are dropped first and the omission is stated in the prompt. Services with no facts get a rule-made summary and no LLM call. After each call, code removes claims whose evidence ids are not in the input and counts them in `dropped_claims`. Reduce input is one line per service (purpose + risk texts, trimmed) plus shared infra and edges; services that do not fit are counted in `omitted_services`. `doctor.py` implements `prodpath doctor` (Ollama reachable, model present, VRAM via `nvidia-smi`, terraform on PATH, warning when the model file is larger than ~85% of VRAM). `scripts/benchmark_models.py` runs candidate models over the fixtures and prints valid-JSON rate, citation rate and seconds per call.

## 8. Provider interface (`src/prodpath/providers/`)

```python
class Provider(Protocol):
    name: str

    def choose(self, system: SystemModel, prefs: Prefs) -> Architecture: ...
    def forecast(self, arch: Architecture, usage: Usage) -> Forecast: ...
    def traps(self, arch: Architecture, usage: Usage) -> list[Trap]: ...
    def steps(self, arch: Architecture) -> list[Step]: ...
    def render_iac(self, arch: Architecture) -> dict[str, str]: ...  # filename -> content
```

**Implementation notes (Phase 4).** `providers/base.py` defines `Provider` with only the methods implemented so far (`choose`, `steps`); `forecast`, `traps` and `render_iac` are added in Phases 5 and 6. `providers/aws/rules.py` is a list of small rule functions, each returning components with a `reason` and the triggering facts as `evidence`. Stage 5 uses no LLM in Phase 4 (rules are never unsure); `plan` reads `.prodpath/summaries.json` if `summarize` was run, to show each service's purpose, and says so when absent. Shared by design: one VPC, ECS cluster and ALB; one RDS or ElastiCache per engine serving every service that uses it (a risk the plan states). A single deployable web service with no datastore or cache gets App Runner instead of Fargate and an ALB. Secret slots are created for env var names that look like credentials or connection URLs; values are never known. `render.py` writes `.prodpath/out/PLAN.md` with a header (tool version, timestamp, input hash), sections for services, architecture, ordered steps, risks, unknowns, not analyzed, and "Not verified by this tool". Terraform is not generated yet, so steps use AWS CLI commands with placeholders and say so.

### AWS provider (`providers/aws/`)

| File | Responsibility |
|---|---|
| `rules.py` | Mapping from facts to components. Plain Python rules, each with a `reason` string shown in the plan |
| `pricing.py` | Reads the local price snapshot; no network except `prices update` |
| `traps.py` | Trap registry: detector function + cost impact + fix |
| `steps.py` | Ordered deployment steps (bootstrap account, state backend, network, data, services, CI/CD, observability, rollback) |
| `templates/` | Jinja2 Terraform templates, one per component type |

Default component rules (tunable; rules are code, so they stay reviewable):

- Stateless HTTP container -> ECS Fargate behind **one shared ALB** with host/path routing (avoids one load balancer per service in a monorepo). Small single-service apps may get App Runner instead.
- Background worker -> ECS Fargate service with no load balancer.
- Scheduled job -> EventBridge Scheduler triggering an ECS task or Lambda.
- Short event handler -> Lambda.
- Postgres/MySQL -> RDS (single-AZ for non-prod, Multi-AZ for prod). Redis -> ElastiCache. Queue -> SQS. Blobs -> S3.
- Secrets -> Secrets Manager or SSM Parameter Store. Env var *names* become secret slots; values are never known to the tool.
- Images -> ECR. CI/CD -> GitHub Actions assuming an IAM role through OIDC (no long-lived keys).
- Network -> VPC with public and private subnets; prefer VPC endpoints for S3/ECR to avoid NAT data charges.
- Logs -> CloudWatch with an explicit retention period on every log group.

## 9. Forecast engine (`forecast.py` + provider pricing)

1. **Usage model.** A scenario of average and peak requests per second, payload sizes, stored data, and retention. Defaults exist but are always labelled `default`. The user overrides with `--usage usage.toml`.
2. **Coefficients from code.** Static analysis extracts per-request multipliers as `inferred` assumptions with evidence: SDK calls per handler, log statements per request, retries configured, cross-service calls per request.
3. **Pricing.** Local snapshot of the AWS Price List per service and region in `~/.cache/prodpath/prices/`. Every `CostLine` stores its `price_ref`.
4. **Ranges.** v1: three deterministic scenarios (low, expected, spike) by scaling the traffic scenario. Monte Carlo is a later phase.
5. **Traps.** Seed registry: NAT gateway data processing, cross-AZ traffic, CloudWatch log ingestion without retention, public IPv4 addresses, one load balancer per service, S3 list/put volume in loops, Lambda retry loops, oversized ElastiCache, Multi-AZ RDS in non-prod. Each trap states its fix and estimated monthly impact when computable.
6. **Calibration** (Phase 7). `prodpath calibrate costs.csv` compares prediction with a manually exported actual-cost CSV and records the error per dimension. This dataset is the long-term moat.

## 10. Rendering (`render.py`)

- Terraform is rendered from templates, never written by the LLM. If `terraform` is installed, run `terraform fmt` and `terraform validate` (works offline with no credentials) and report the result.
- `PLAN.md` structure: summary, architecture table (component, why, evidence), ordered steps with commands, risks, open questions.
- `FORECAST.md` structure: assumptions table (with source column), cost table (low / expected / spike), traps ranked by impact.
- Every generated file starts with a header: tool version, timestamp, input hash.

## 11. CLI (`cli.py`, argparse, single entry point)

```
prodpath doctor               # checks Ollama, model, GPU/VRAM, terraform presence
prodpath scan                 # stages 1-2
prodpath facts                # stages 1-3; writes .prodpath/system.json, prints facts per service
prodpath summarize            # stages 1-4 (needs Ollama); writes .prodpath/summaries.json
prodpath plan                 # stages 1-5 and 7 (PLAN.md now; terraform from Phase 5); needs no LLM
prodpath forecast             # stage 6 (needs a plan)
prodpath run                  # everything
prodpath prices update        # the only networked command (AWS Price List)
common flags: --path . --service <id> --model <tag> --region ap-south-1 --provider aws --from <stage> --usage usage.toml
```

## 12. Repository layout

```
prodpath/
  CLAUDE.md  MEMORY.md  README.md  pyproject.toml
  docs/        ARCHITECTURE.md ROADMAP.md DECISIONS.md CODING_STANDARDS.md TESTING.md SECURITY.md
  .claude/commands/   wrapup.md adr.md
  src/prodpath/
    cli.py  config.py  models.py  cache.py  redact.py  doctor.py
    scan.py  detect.py  extract.py  edges.py  llm.py  summarize.py  forecast.py  render.py
    facts/        python.py  javascript.py  docker.py  compose.py  manifests.py
    providers/
      base.py
      aws/        rules.py  pricing.py  traps.py  steps.py  templates/
  scripts/      benchmark_models.py
  tests/
    fixtures/     mini monorepos (small, synthetic, committed)
    golden/       expected JSON/markdown outputs
    test_*.py
```

Output in the target repo: `.prodpath/` containing `cache.sqlite`, `inventory.json`, `system.json`, `summaries.json`, `architecture.json`, `out/PLAN.md`, `out/FORECAST.md`, `out/terraform/`.

## 13. Errors, logging, observability

- stdlib `logging`; `-v` for debug. Each stage logs counts and elapsed time ("detected 14 services, 3 uncertain").
- Failures name the stage, the file or service, and the next action. No silent fallbacks; if something is skipped, it appears in the output under "Not analyzed".
- Output always lists uncertainty: heuristic facts, default assumptions, and services the tool could not classify.

## 14. Hardware envelope

Developer machine: ASUS TUF F15 with an NVIDIA GeForce GTX 1650, **4 GB VRAM** (confirmed with `nvidia-smi`, 2026-10-21). CPU and RAM are still unconfirmed; assume 16 GB RAM.

- With 4 GB VRAM, default to a 3B to 4B instruct model at 4-bit quantization (about 2 to 2.5 GB) with `num_ctx=4096` to 8192; a 7B to 8B model will spill to CPU and be slow. Benchmark both in Phase 3. Model tags are examples; confirm availability with `ollama list` and benchmark in Phase 3.
- `prodpath doctor` reports detected VRAM and warns when the configured model will spill to CPU.
- Calls run sequentially. A 40-service monorepo should finish a cold run in minutes, and a warm run (cache hits) in seconds.

## 15. Extension points

- New cloud: implement `Provider` in `providers/<name>/`, register it in `providers/__init__.py`.
- New language: add `facts/<lang>.py` exposing `extract(path, source) -> list[Fact]`.
- New trap: add one function and one registry entry in `providers/aws/traps.py` with a test.
- New IaC format: a new renderer behind `render_iac`; templates stay separate from rules.

## 16. Open design questions

Tracked in `MEMORY.md` under "Open questions". Resolve them there, then record the answer in `DECISIONS.md`.
