# ROADMAP.md

Phased plan. Work only on the current phase (see `MEMORY.md`). A phase is done only when its **exit criteria** are met and recorded in `MEMORY.md`.
Do not start the next phase "while you're here". If a task belongs to a later phase, write it under Open items instead.

## Phase 0 - Bootstrap and fixtures

**Goal:** a repo where tests, lint and the CLI run, with realistic test data.

- [x] `uv init`, `pyproject.toml` (Python 3.12, `pydantic`, `httpx`, `jinja2`, `tree-sitter` + language pack; dev: `pytest`, `ruff`, `mypy`)
- [x] `src/prodpath/` skeleton with `cli.py` (`--help`, `doctor` stub), `models.py` with the contracts from ARCHITECTURE section 5
- [x] `tests/fixtures/`: three synthetic mini-monorepos: (a) one Flask service + Postgres, (b) FastAPI + Celery worker + Redis + docker-compose, (c) 6+ services mixing Python and Node with a pnpm workspace
- [x] Socket guard fixture: tests fail if any code opens a non-localhost connection
- [x] `/wrapup` command works end to end

**Exit:** `uv run pytest -q`, `ruff check`, `mypy src` all green; `uv run prodpath --help` works.

## Phase 1 - Scan and service detection

**Goal:** turn a large repo into a reliable list of deployable services.

- [x] `scan.py` with ignore rules, hashing, language detection, SQLite cache
- [x] `detect.py` with the detection order from ARCHITECTURE section 6
- [x] `prodpath scan` prints a service table (id, root, kind, evidence)
- [x] Golden tests for all three fixtures

**Exit:** correct services on all fixtures; a second run on an unchanged repo does no re-hashing work (verified by a test); on the real monorepo, the user confirms the service list is right or lists misses (record in MEMORY.md).

## Phase 2 - Fact extraction

**Goal:** every service gets evidence-backed facts.

- [x] `facts/python.py` (ast), `facts/docker.py`, `facts/compose.py`, `facts/manifests.py`
- [x] `facts/javascript.py` via tree-sitter
- [x] Edges between services (http calls by env var URLs, queues, shared DBs)
- [x] Invariant test: no fact without evidence; no secret value in any snippet

**Exit:** facts on the fixtures match goldens; on the real monorepo, a spot check of 10 random facts finds none without correct evidence.

## Phase 3 - Local LLM summaries

**Goal:** readable, trustworthy summaries from a small local model.

- [x] `llm.py`: `OllamaLLM`, `FakeLLM`, schema-validated output, repair retry, response cache
- [x] `prodpath doctor` real checks (Ollama reachable, model present, VRAM)
- [x] `summarize.py` map-reduce with token budgets
- [x] Small benchmark script comparing 2 to 3 candidate models on the fixtures (valid-JSON rate, evidence-citation rate, seconds per service). Record results in MEMORY.md and DECISIONS.md

**Exit:** chosen default model yields schema-valid output on at least 95% of calls across fixtures; cold run on the real monorepo finishes in an acceptable time (user defines "acceptable" and it is recorded).

## Phase 4 - AWS architecture choice and PLAN.md

**Goal:** a concrete, ordered production plan.

- [x] `providers/base.py`, `providers/aws/rules.py`, `steps.py`
- [x] `render.py` produces `PLAN.md` (architecture table with reasons and evidence, ordered steps with commands, risks)
- [x] `prodpath plan` end to end on all fixtures

**Exit:** the plan for the real monorepo is reviewed by the user; every component has a visible reason and evidence; unknowns are listed, not hidden.

## Phase 5 - Terraform generation

**Goal:** valid, readable Terraform from templates.

- [x] Templates for VPC, ECR, ECS cluster/service, ALB, RDS, ElastiCache, SQS, S3, Secrets slots, IAM (least privilege), CloudWatch log groups with retention, GitHub OIDC role
- [x] `terraform fmt` and `terraform validate` run when available, results reported
- [x] Golden tests per template

**Exit:** `terraform validate` passes for generated code on all fixtures; no secret values or account IDs hard-coded; variables documented.

## Phase 6 - Forecast and traps (the wedge)

**Goal:** answer "What will this cost me, and what can bite me?"

- [x] `prices update` and local price snapshot reader
- [x] Usage model with labelled assumptions; coefficients inferred from code
- [x] `CostLine` computation for low / expected / spike
- [x] Trap registry (seed list in ARCHITECTURE section 9), each with a test
- [x] `FORECAST.md` rendering

**Exit:** hand-computed forecasts on 3 fixtures match the tool within rounding; every number traces to a price reference; the trap list for the real monorepo is reviewed by the user.

## Phase 7 - Frontend hosting (S3 + CloudFront)

**Goal:** a static site or SPA is detected as `static`, planned as S3 + CloudFront, and gets Terraform, steps, cost lines and traps (ADR-017).

- [x] Detect `static` sites and SPAs; Next.js SSR becomes `web`
- [x] `rule_static`, `s3-site` and `cloudfront` components, params, unknowns
- [x] `static_site.tf.j2`, variables, outputs, GitHub OIDC permissions; validated with `pytest -m tf`
- [x] Frontend deploy steps; CloudFront cost lines from the global price offer; traps
- [x] New fixture `mono_d` and goldens

**Exit:** fixture frontends are planned and validated; hand-computed forecast for `mono_d` matches; on the real monorepo the user confirms the frontends were found.

## Phase 8 - ECS autoscaling and alarms

**Goal:** generated Terraform scales services and notifies someone when things break.

- [x] Application Auto Scaling target tracking per service; services ignore `desired_count` (ADR-018)
- [x] Alarms (ALB, ECS, RDS, Redis, queues) to one SNS topic
- [x] Autoscale-aware forecast with a labelled `rps_per_task` assumption; alarm costs
- [x] `autoscaling-max-cost` and `alarm-subscription-unconfirmed` traps replace `no-autoscaling`

**Exit:** `terraform validate` passes with autoscaling and alarms; forecast hand-checks match.

## Phase 9 - Medium-traffic defaults

**Goal:** the forecast starts from the traffic the user expects.

- [ ] Default traffic assumptions raised to a "medium" profile, still labelled `default` (decide first whether the user's "tens of req/s" is an average or a peak: 20 req/s *average* is already ~$1,300/month for five services)
- [ ] `prodpath forecast --write-usage-template usage.toml`
- [ ] Hand-computed tests and goldens recomputed

**Exit:** every default is documented and the template round-trips through `--usage`.

## Phase 10 - Calibration (was Phase 7)

**Goal:** prove the forecast is useful against real bills.

- [ ] `prodpath calibrate costs.csv` comparing predicted vs actual per component group
- [ ] Target: expected forecast within about 30% of actual on at least 5 real projects (the user's own are fine); **blocked until the user has bills**, tooling is tested on synthetic data
- [ ] Fix the largest error sources first; log each in DECISIONS.md

**Exit:** the accuracy target is met, or the main reasons it is not are documented with a plan.

## Phase 11 - Hardening on the real repo

**Goal:** make it correct on the user's actual monorepo.

- [ ] `prodpath run` (scan, facts, optional summaries, plan, forecast in one command)
- [ ] Fix every miss from the first real run, each with a minimal fixture and a test
- [ ] Performance pass on the monorepo; error messages pass; README quickstart verified from a clean clone

**Exit:** the user confirms services, facts, plan, Terraform and forecast on the real repo.

## Parking lot (not scheduled)

Second cloud provider (was Phase 8; implement the `Provider` protocol in `providers/gcp/` and fix any leak into stages 1 to 4), Monte Carlo ranges, Pulumi/CDK renderers, GitHub App wrapper, MCP server wrapper, optional sandbox-account dry run, live-account drift detection.
