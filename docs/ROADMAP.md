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

- [ ] Templates for VPC, ECR, ECS cluster/service, ALB, RDS, ElastiCache, SQS, S3, Secrets slots, IAM (least privilege), CloudWatch log groups with retention, GitHub OIDC role
- [ ] `terraform fmt` and `terraform validate` run when available, results reported
- [ ] Golden tests per template

**Exit:** `terraform validate` passes for generated code on all fixtures; no secret values or account IDs hard-coded; variables documented.

## Phase 6 - Forecast and traps (the wedge)

**Goal:** answer "What will this cost me, and what can bite me?"

- [ ] `prices update` and local price snapshot reader
- [ ] Usage model with labelled assumptions; coefficients inferred from code
- [ ] `CostLine` computation for low / expected / spike
- [ ] Trap registry (seed list in ARCHITECTURE section 9), each with a test
- [ ] `FORECAST.md` rendering

**Exit:** hand-computed forecasts on 3 fixtures match the tool within rounding; every number traces to a price reference; the trap list for the real monorepo is reviewed by the user.

## Phase 7 - Calibration and hardening

**Goal:** prove the forecast is useful against real bills.

- [ ] `prodpath calibrate costs.csv` comparing predicted vs actual per dimension
- [ ] Target: expected forecast within about 30% of actual on at least 5 real projects (the user's own are fine)
- [ ] Fix the largest error sources first; log each in DECISIONS.md
- [ ] Performance pass on the monorepo; error messages pass; README quickstart verified from a clean clone

**Exit:** the accuracy target is met, or the main reasons it is not are documented with a plan.

## Phase 8 - Second provider (only after Phase 7)

Add `providers/gcp/` (or another) by implementing the `Provider` protocol. If this requires changes to stages 1 to 4, that signals a leak in the abstraction; fix the abstraction and record it in DECISIONS.md.

## Parking lot (not scheduled)

Monte Carlo ranges, Pulumi/CDK renderers, GitHub App wrapper, MCP server wrapper, optional sandbox-account dry run, live-account drift detection.
