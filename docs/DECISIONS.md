# DECISIONS.md

Architecture decision records (ADRs). Append-only: never rewrite history. To change a decision, add a new ADR that supersedes the old one and mark the old one `Superseded by ADR-NNN`.
Add an ADR for any new dependency, new top-level module, changed data contract, or change to a hard constraint in `CLAUDE.md`. Use `/adr <title>` to scaffold one.

Format: **Status** | **Context** | **Decision** | **Consequences**.

---

## ADR-001: Advisor only, no cloud account access
- **Status:** Accepted (2026-10-21), chosen by the user
- **Context:** The user hesitates and double-checks when deploying. A tool with write access to a cloud account is a liability if it is wrong, and needs a much larger safety design.
- **Decision:** The tool reads code and writes a plan, Terraform and a forecast. It never holds credentials and never calls a cloud API except the public price list download.
- **Consequences:** Safe to adopt immediately. Calibration uses a manually exported cost CSV. Applying the Terraform is the user's job.

## ADR-002: CLI run inside the target repo
- **Status:** Accepted (2026-10-21), chosen by the user
- **Decision:** One CLI, `prodpath`, run in the repo. Output goes to `.prodpath/`.
- **Consequences:** No server, no auth, no UI. Wrappers (GitHub App, MCP server) are possible later.

## ADR-003: Python 3.12, managed with uv
- **Status:** Accepted (2026-10-21), language chosen by the user; `uv` and layout chosen by Claude
- **Decision:** `pyproject.toml` + `uv`, src layout, argparse for the CLI, stdlib first.
- **Consequences:** Minimal dependencies (pydantic, httpx, jinja2, tree-sitter). New dependencies need an ADR.

## ADR-004: Local LLM only, via Ollama
- **Status:** Accepted (2026-10-21), chosen by the user
- **Context:** The tool reads proprietary code. The user wants it to never leave the machine. Hardware is a laptop GPU (specs unconfirmed).
- **Decision:** All LLM calls go to Ollama on localhost with schema-constrained output. A `FakeLLM` is used in tests.
- **Consequences:** Weaker model, small context. Mitigated by ADR-006. Tests assert no non-localhost network access.

## ADR-005: AWS first, behind a Provider interface
- **Status:** Accepted (2026-10-21), chosen by the user
- **Decision:** v1 supports AWS only. Everything cloud-specific lives in `providers/aws/`; stages 1 to 4 are cloud-neutral.
- **Consequences:** Adding another cloud means implementing `Provider`. If it forces edits to stages 1 to 4, the abstraction leaked and must be fixed.

## ADR-006: Deterministic first, LLM explains
- **Status:** Accepted (2026-10-21), chosen by Claude as the design principle
- **Context:** Small local models hallucinate; prices and infrastructure must be correct.
- **Decision:** Parsing, rules, pricing and Terraform come from code and templates. The LLM writes summaries and explanations from structured inputs and must cite evidence.
- **Consequences:** More code than a prompt-only agent, but results are checkable and reproducible.

## ADR-007: Terraform as the IaC format
- **Status:** Accepted (2026-10-21). The user had no preference ("whatever is good and easy to use"); Claude chose the default.
- **Context:** Terraform is widely used, readable, and not tied to one language or cloud.
- **Decision:** Generate Terraform from Jinja2 templates; validate with `terraform validate` when available.
- **Consequences:** Revisit if template maintenance becomes painful or the user prefers CDK/Pulumi.

## ADR-008: Design for a large monorepo from day one
- **Status:** Accepted (2026-10-21), driven by the user's first test target
- **Decision:** Service detection comes before analysis; extraction is per service; results are cached by content hash; LLM inputs are bounded and map-reduced.
- **Consequences:** More upfront work in Phases 1 and 2, but avoids a rewrite when the first real repo is large.

## ADR-009: Every fact carries evidence
- **Status:** Accepted (2026-10-21), chosen by Claude
- **Decision:** `Fact` requires at least one `Evidence` (path, line, short snippet). Heuristic facts are labelled.
- **Consequences:** Plans are auditable, and the LLM can be constrained to cite evidence ids. Snippets must never contain secret values.

## ADR-010: Inventory and candidate contracts, PyYAML dependency
- **Status:** Accepted (2026-10-21), chosen by Claude; PyYAML flagged to the user
- **Context:** Phase 1 needs stage 1-2 data contracts (ARCHITECTURE section 4 named them but section 5 did not define them) and must read docker-compose and Kubernetes manifests, which are YAML. The stdlib has no YAML parser; hand-parsing compose is fragile.
- **Decision:** Add `FileEntry`, `Inventory`, `ServiceCandidate` to `models.py`. Add the `pyyaml` dependency (`yaml.safe_load` only). Add `types-PyYAML` as a dev dependency for mypy.
- **Consequences:** One small, very widely used dependency. Also serves Phase 2 (`facts/compose.py`, manifests). Line numbers for evidence are found by text search because `safe_load` drops them.

## ADR-011: Phase 2 modules and SystemModel.not_analyzed
- **Status:** Accepted (2026-10-21), chosen by Claude
- **Context:** Phase 2 needs a stage-3 orchestrator, edge derivation and the secret redactor mandated by SECURITY.md section 3. ARCHITECTURE section 13 requires a visible "Not analyzed" list but no contract carried it.
- **Decision:** Add top-level modules `extract.py` (stage 3), `edges.py` (edges and shared infra) and `redact.py` (snippet redaction). Add `not_analyzed: list[str]` to `SystemModel`. Add CLI command `prodpath facts`. No new third-party dependency.
- **Consequences:** Stage 3 output is `SystemModel` as designed. Redaction is centralised so every snippet path shares it.

## ADR-012: Phase 3 contracts, doctor module, benchmark script
- **Status:** Accepted (2026-10-21), chosen by Claude
- **Context:** Phase 3 needs stage-4 data contracts, a real `prodpath doctor`, and a way to compare local models. The machine has an i5-10300H, 7.8 GB RAM and a 4 GB GTX 1650; installed models are `phi3` (3.8B) and `llama3.1` (8B).
- **Decision:** Add `Claim`, `ServiceSummary`, `SystemClaim`, `SystemSummary`, `Summaries` to `models.py`; new top-level module `doctor.py`; new `scripts/benchmark_models.py` (a dev tool, not part of the installed package); CLI command `prodpath summarize`. No new dependency (`httpx` is already allowed; `nvidia-smi` is called through `subprocess`). Rule-made summaries replace LLM calls for services with no facts.
- **Consequences:** LLM output is constrained by schema plus evidence-id validation. Small context (4096) keeps the 4 GB card usable; large services lose low-value facts first and say so.

## ADR-013: Default local model is phi3 (Phase 3 benchmark)
- **Status:** Accepted (2026-10-21), chosen by Claude from measured results; the user may override with `--model`
- **Context:** `scripts/benchmark_models.py` ran 9 services (3 fixtures) per model on an i5-10300H, 7.8 GB RAM, GTX 1650 4 GB, `num_ctx=4096`, no cache.
- **Results:** `phi3:latest` (3.8B, 2.2 GB, fits VRAM): 100% schema-valid on the first try, 100% evidence-citation rate, 12.3 s per call. `llama3.1:latest` (8B, 4.9 GB, spills to CPU): 100% valid, 96% citation rate, 33.1 s per call.
- **Decision:** Default to `phi3:latest`. It meets the 95% validity target, cites better, and is 2.7x faster. Sample is small (9 calls per model); rerun the benchmark when the real monorepo or a new model is available.
- **Consequences:** A 40-service cold run is about 40 x 12 s = 8 minutes plus the overview call; a warm run is served from the response cache. Quality of prose was not graded, only structure and evidence.

## ADR-014: Phase 4 contracts and provider scope
- **Status:** Accepted (2026-10-21), chosen by Claude
- **Context:** Phase 4 needs `Prefs`, `Step` and richer `Component`/`Architecture` contracts (evidence per component, unknowns list). Terraform does not exist until Phase 5, so steps cannot point at it.
- **Decision:** Add `Prefs` and `Step` to `models.py`; extend `Component` with `evidence` and `items`, and `Architecture` with `environment` and `unknowns`. `Provider` protocol declares only `choose` and `steps` for now. New modules: `render.py`, `providers/base.py`, `providers/__init__.py`, `providers/aws/rules.py`, `providers/aws/steps.py`. Steps use AWS CLI with placeholders. No new dependency, no LLM in stage 5.
- **Consequences:** `prodpath plan` is deterministic and works offline. The plan must be re-checked when Phase 5 replaces CLI steps with Terraform. Default region `ap-south-1` is unconfirmed by the user and is listed as an open question in every plan.

## ADR-015: Terraform generation, local provider mirror, Component.params
- **Status:** Accepted (2026-10-21); the one-time provider download was approved by the user
- **Context:** Phase 5 must emit valid, readable Terraform. `terraform validate` needs the AWS provider plugin, normally fetched by `terraform init` from registry.terraform.io, which would add a network destination (SECURITY.md section 2). Templates also need machine-readable sizing, which free-text `Component.sizing` cannot give.
- **Decision:** (1) Add `Component.params: dict[str, str]`. (2) Add `render_iac` and `iac_gaps` to the `Provider` protocol, a `providers/aws/iac.py` renderer with Jinja2 templates, and a top-level `iac_check.py` (self-scan, `terraform fmt`, `terraform validate`). (3) The user approved a one-time `terraform providers mirror ~/.cache/prodpath/terraform-mirror` (hashicorp/aws 6.69.1, 176 MB, windows_amd64); validation always uses that local mirror and never the network. (4) Plan steps are reworked around `terraform apply` (CLI remains for state bootstrap, secrets and image push). (5) AWS provider constraint `>= 5.81, < 7.0`.
- **Consequences:** Validation is reproducible offline. Components without templates are listed, not hidden. The mirror holds one platform (Windows amd64); other platforms need their own `terraform providers mirror -platform=...`. Rendering is deterministic; goldens store `terraform fmt`-formatted output and are skipped when terraform is absent.

## ADR-016: Phase 6 forecast, price snapshot and traps
- **Status:** Accepted (2026-10-21), chosen by Claude. The Price List host was already an allowed destination (SECURITY.md section 2, ADR-001).
- **Context:** The forecast must be usage-aware, traceable to a price, and honest about what it cannot price. The real Price List files for ap-south-1 were inspected: the 11 offers we need total about 25 MB (RDS 21 MB); the EC2 offer (NAT gateway) is 315 MB and parses to several GB, too heavy for an 8 GB laptop.
- **Decision:** (1) New contract `Forecast` (and `Provider.forecast`, `Provider.traps` join the protocol). (2) New modules: `forecast.py` (neutral usage and scenarios), `providers/aws/pricing.py`, `providers/aws/costs.py`, `providers/aws/traps.py`. (3) `prodpath prices update` downloads the 11 offers and writes a compact snapshot under `~/.cache/prodpath/prices/`; the forecast reads only that snapshot. (4) NAT gateway is not priced; its trap states the cost is unpriced. (5) Free tiers are not applied. (6) Tests use a tiny committed snapshot with made-up round numbers (`tests/fixtures/prices/`), never real AWS prices, so no AWS data is redistributed.
- **Consequences:** Forecasts are only as good as the labelled defaults until the user supplies `usage.toml`; the document says so. Price refs are stable ids, so a snapshot can be audited against the public file. Only first-tier on-demand prices are used (volume discounts and reserved pricing ignored).

## ADR-017: Roadmap re-plan and frontend hosting (Phase 7)
- **Status:** Accepted (2026-10-22), chosen by Claude from the user's answers (mixed monorepo with frontends, ECS Fargate + shared ALB, GitHub Actions, prod only, medium traffic, no AWS bills yet, audience is the user, next focus "everything").
- **Context:** The `static` kind existed in the contracts but was never emitted, so a SPA became a library and was silently not deployed. Autoscaling and alarms were missing, forecast defaults assumed 1 request/second, and calibration cannot be validated without bills.
- **Decision:** (1) Re-plan: Phase 7 frontend hosting, 8 autoscaling and alarms, 9 medium-traffic defaults, 10 calibration tooling (old Phase 7), 11 hardening on the real repo plus `prodpath run`; a second cloud stays parked. (2) Frontends: detect `static` (build tool in package.json with a build script and no server entrypoint, Next.js `output: "export"`, or a Dockerfile that copies a build into nginx/httpd html); Next.js without static export is `web`. (3) Each static site gets one private S3 bucket (origin access control only) and one CloudFront distribution served at `<service-id>.<domain_name>`, HTTPS only, TLS 1.2+, with a SPA fallback (403/404 to `/index.html`) for client-routed frameworks. (4) The CloudFront ACM certificate is a required variable (`site_certificate_arn`); it must be created in us-east-1 outside Terraform, so no second provider alias is generated. (5) CloudFront prices live in the **global** `AmazonCloudFront` offer keyed by edge geography (IN, US, EU, AP, JP, AU, CA, ME, SA, ZA); the forecast assumes viewers are in the same geography as the AWS region and says so. (6) No new dependency.
- **Consequences:** Static sites cost no compute. Price class defaults to `PriceClass_All` because cheaper classes exclude India and other Asian edges. Custom domains are the user's job (DNS records are listed as a plan step). A shared distribution with path routing is not supported.

## ADR-018: ECS autoscaling and alarms (Phase 8)
- **Status:** Accepted (2026-10-22), chosen by Claude from the approved plan (ADR-017) and the user's "medium traffic" answer.
- **Context:** Task counts were fixed and nothing notified anyone when something broke; the `no-autoscaling` trap only described the gap. At tens of requests per second a fixed count is either overloaded or wasteful.
- **Decision:** (1) New component types `autoscaling` (one per web and worker service), `sns-alerts` and `alarms`. (2) Terraform: Application Auto Scaling with CPU target tracking per service (`variable "service_scaling"`: `min_count`, `max_count`, `cpu_target`), ECS services ignore `desired_count` (autoscaling owns it) as well as `task_definition`. (3) Alarms are defined once as data in `providers/aws/iac.py` (`build_alarms`) and used by both the template and the cost model, so they cannot drift: ALB target 5xx and unhealthy hosts per web service, ECS CPU and memory per service, RDS CPU and free storage, Redis engine CPU and evictions, dead-letter queue depth. All notify one SNS topic with a required `alert_email` variable. (4) The alerts topic is deliberately **not** KMS-encrypted: CloudWatch cannot publish to a topic encrypted with the AWS-managed key. It carries alarm names only, never application data. (5) Forecast: web tasks per scenario = clamp(ceil(requests per second / `rps_per_task`), min, max), where `rps_per_task` is a labelled default (25) and may be overridden per service; workers stay at their minimum because their load is not known; alarms are priced from `CW:AlarmMonitorUsage`. (6) Traps: `no-autoscaling` is replaced by `autoscaling-max-cost` (extra monthly cost if every service ran at its maximum, computed) and `alarm-subscription-unconfirmed`. (7) Defaults: min = current count (2 in prod, 1 otherwise), max = 5x min, CPU target 60%.
- **Consequences:** Compute cost now moves with traffic in the spike scenario. Thresholds are defaults. Request-count and queue-depth based scaling, CloudFront alarms and composite alarms are not generated. The topic subscription must be confirmed by e-mail before any alarm reaches anyone.

## ADR-019: Web service, GitHub intake and the new network destination
- **Status:** Accepted (2026-10-24). The user asked for a web UI where anyone pastes a public GitHub repo link and gets the analysis, built on a separate branch (`feature/web-ui`) and tested before it reaches `main`.
- **Context:** Until now prodpath only read local folders and its only network call was the AWS Price List. A link-driven product needs to fetch untrusted code and serve a UI.
- **Decision:** (1) New command `prodpath serve` (default `127.0.0.1:8765`) using only the standard library (`http.server`), no new dependency. It serves a static single-page UI and a small JSON API. (2) Intake accepts only `https://github.com/<owner>/<repo>` (optionally `/tree/<branch>`); every other scheme or host is rejected, which also closes SSRF. (3) New allowed destination, **web mode only**: `github.com` over HTTPS for a shallow clone. The CLI commands stay offline except `prices update`. (4) The clone is hardened: `--depth 1 --single-branch --no-tags`, no submodules, `core.symlinks=false`, git hooks disabled, `GIT_TERMINAL_PROMPT=0` (private repos fail fast), a 120 s timeout, and post-clone limits (300 MB, 30,000 files). The cloned code is read, never executed. The workspace is deleted after the analysis. (5) Abuse controls: at most 2 concurrent jobs, a per-client rate limit, results kept 1 hour. (6) The UI is vanilla HTML, CSS and JavaScript with a strict Content-Security-Policy (`script-src 'self'`, no inline script or style attributes), and every repo-derived string reaches the DOM through `textContent` only, because file names, snippets and env var names are attacker-controlled. (7) Public hosting (non-localhost bind) needs a reverse proxy with TLS and authentication in front; that is out of scope here and documented.
- **Consequences:** The tool gains an attack surface, so symlinks are never read (security fix 88c3fb6), URLs are allow-listed, and all output is escaped. Summaries still use only the local Ollama model.

## ADR-020: Traffic model: peak versus average
- **Status:** Accepted (2026-10-24), from the user's answer that "tens of requests per second" is a **peak**.
- **Context:** Monthly volume (data out, logs, requests) follows the **average**, while capacity follows the **peak**. The old single `avg_requests_per_second = 1` default conflated them.
- **Decision:** New inputs `peak_requests_per_second` (default 20) and `peak_to_average_ratio` (default 5). Average = peak / ratio (4 req/s). The spike scenario is a month run at the peak (factor = ratio). `avg_requests_per_second` remains an explicit alternative: if given, peak = average x ratio. Both can be overridden per service. Autoscaling uses `rps_per_task` against the scenario's request rate as before. `prodpath forecast --write-usage-template usage.toml` writes every assumption with its default and a comment.
- **Consequences:** The default expected figure moves from a 1 req/s average to 4 req/s, labelled `default`. Hand-computed tests pin an explicit average so their arithmetic stays checkable; new hand-computed tests cover the peak semantics.

## ADR-021: Budget mode
- **Status:** Accepted (2026-10-24), the "small app" option the user agreed to ("build all the things").
- **Context:** For small apps the fixed network cost dominates (interface VPC endpoints about $57 of $140 a month for one service).
- **Decision:** `--budget` (and a UI toggle) selects a leaner network: no interface VPC endpoints and no NAT; web and worker tasks run in the public subnets with a public IPv4 address, protected by security groups that only allow the load balancer in. Databases and caches stay in private subnets. Autoscaling, alarms and the shared ALB are kept. The forecast replaces the endpoint lines with public IPv4 per task (scaled by task count) and the traps say what changed.
- **Consequences:** Cheaper, and outbound internet works without NAT (fixing the `no-outbound-path` trap for budget systems), at the price of public task IPs and weaker network isolation, which a new trap states plainly.

## ADR-022: Calibration command
- **Status:** Accepted (2026-10-24).
- **Context:** Phase 10 compares predicted and actual cost. The user has no real AWS bills yet.
- **Decision:** New module `calibrate.py` and `prodpath calibrate costs.csv [--path <repo>]`. Input is a Cost Explorer CSV grouped by service. A mapping table assigns AWS service names to the forecast's component groups; the command writes `CALIBRATION.md` with predicted versus actual per group and overall, and appends a row to a local dataset under `~/.cache/prodpath/calibration/` (never committed). Tested on synthetic CSVs only.
- **Consequences:** The accuracy target stays unmet until real bills exist; the tooling is ready when they do.

<!-- Add new ADRs below. Next number: ADR-023 -->
