# MEMORY.md

Living memory for this project. Claude Code reads this first and updates it after every meaningful change.
Keep it short, factual and current. History goes in the changelog; design lives in `docs/ARCHITECTURE.md`.

## How to maintain this file (rules for Claude Code)

- **Current state**: rewrite it (do not append) so it always describes *now*.
- **Changelog**: append one entry per meaningful change, newest on top. Format: `YYYY-MM-DD | phase-N | what changed | why | files`.
- **Decisions**: one line each here; the full reasoning goes into `docs/DECISIONS.md`.
- **Open questions / Open items**: add when you hit uncertainty or leave a `TODO`; remove when resolved (move the answer to Decisions).
- **Gotchas**: things that cost time to discover (tool quirks, model behavior, parsing edge cases). Future sessions must not rediscover them.
- Never store secrets, API keys, or real customer code in this file.
- When the changelog passes ~40 entries, roll the oldest into a short per-month summary at the bottom.

## Current state

- Phase: **8 (autoscaling and alarms) implemented.** Next in the approved plan (ADR-017): Phase 9 medium-traffic defaults, 10 calibration tooling (blocked on bills), 11 hardening + `prodpath run`. The user still has not run the pipeline on the real monorepo.
- Works: per-service CPU target-tracking autoscaling (`var.service_scaling`, min = current count, max = 5x, services ignore `desired_count`), one alerts SNS topic + `alert_email` variable, 10 to 24 CloudWatch alarms per system defined once as data (`build_alarms` in `providers/aws/iac.py`, used by both `alarms.tf` and the cost model), forecast tasks follow traffic (`clamp(ceil(rps/rps_per_task), min, max)`, `rps_per_task` default 25, per-service override), alarms priced from `CW:AlarmMonitorUsage`, traps `autoscaling-max-cost` and `alarm-subscription-unconfirmed` (replacing `no-autoscaling`), a real alerts step. 339 fast tests + 9 `-m tf` tests (real terraform validate), ruff, mypy --strict green.
- Real-price forecast (ap-south-1, prod, defaults): mono_a $215, mono_b ~$196, mono_c $426, mono_d $277 per month. With 20 req/s *average* and 25 KB responses on every service, mono_d is $1,328 expected and $5,735 at 5x spike (egress dominates), so Phase 9 must settle whether the user's "tens of req/s" means average or peak.
- Demo: `.\scripts\demo.ps1` (fixture, no LLM, ~15 s; `-Summarize` ~2 min) or `uv run prodpath run --path <repo> [--summarize] [--usage usage.toml]`; guide in `docs/DEMO.md`. `prodpath run` was pulled forward from Phase 11 (it also leaves inventory.json and system.json).
- Code is at https://github.com/thepallavjha1/prodpath (public, main). Commit and push after each task.
- Next action: user says "go" for Phase 9 (first answering average vs peak traffic) and runs the pipeline on the real monorepo.

## Decisions (short form; details in docs/DECISIONS.md)

- Advisor only: reads code, writes plan + IaC + forecast. No cloud account access. (ADR-001)
- Delivered as a CLI that runs inside the target repo. (ADR-002)
- Written in Python, managed with uv. (ADR-003)
- LLM is local only, via Ollama, so code never leaves the machine. (ADR-004)
- v1 targets AWS only, behind a `Provider` interface so other clouds can be added later. (ADR-005)
- Deterministic analysis does the heavy lifting; the LLM summarizes and explains with schema-validated output. (ADR-006)
- IaC format: Terraform. The user had no preference ("whatever is good and easy to use"), so this was chosen as the default; revisit if it hurts. (ADR-007)
- First real test target: a large monorepo with many services, so service-boundary detection and incremental caching are core, not extras. (ADR-008)

## Open questions

- CPU model: i5-10300H (known). Cold-run time the user accepts on the real monorepo: still unanswered.
- Real monorepo size and exact stack: mixed with frontends, size unknown until the first real run.
- AWS region: still `ap-south-1` by default; the user has not explicitly confirmed it.
- Real AWS bills for Phase 7 calibration: none yet (user, 2026-10-21).

## Product answers (user, 2026-10-21)

- Compute stays ECS Fargate behind one shared ALB; deploys via GitHub Actions; prod only (single environment).
- Forecast should assume **medium** traffic (tens of req/s per service) until real numbers exist; the current 1 req/s default is a known mismatch to fix.
- Monorepo is mixed with frontends: static sites/SPAs need an S3 + CloudFront rule and templates.
- Next work ("everything"): frontend hosting, ECS autoscaling and alarms in Terraform, medium-traffic defaults, Phase 7 tooling (data pending), hardening on the real repo.
- Audience is just the user: no PyPI, license or contribution-guide work.

## Open items (TODOs in code)

- none yet

## Gotchas

- Hardware: GTX 1650 with 4 GB VRAM. A 7B model will spill to CPU; plan for 3B to 4B models by default (ARCHITECTURE section 14).
- RAM is 8 GB (not 16): keep prompts and caches small; 3B to 4B model, `num_ctx` 4096 to start. Large repos: scan reads files in 1 MB chunks and detect reads at most 1 MB per file.
- `gitignore` support is simplified (no `!` negation, reported by `scan`). K8s manifests claim their directory (several workloads in one dir collapse). turbo/nx/Cargo/go.work workspaces are not detected yet.
- Heredocs with quotes/escapes broke in the Bash tool; write files with the Write tool.
- Environment tools present: uv 0.12.5, Python 3.12.3, Terraform 1.16.4, Ollama 0.40.6.
- `uv sync` run before `src/prodpath/` existed does not install the project; rerun `uv sync --reinstall-package prodpath` if `import prodpath` fails.
- Unknown packages produce no fact (only the KNOWN_PACKAGES table in facts/manifests.py); extend it when the real monorepo shows misses. Bump EXTRACTOR_VERSION in extract.py whenever an extractor changes.
- Shared infra is only detected through compose image-only services; two services both using psycopg2 are not assumed to share a database.
- Ollama models present: phi3:latest (2.2 GB), llama3.1:latest (4.9 GB). Models are pulled by the user, never by the tool. llama3.1 spills to CPU on 4 GB VRAM.
- Summary claims store `path:line` refs, not the prompt ids (F1...); the ids only exist inside one prompt.
- Steps are AWS CLI with placeholders because Terraform does not exist until Phase 5; revisit the Steps section of PLAN.md then.
- Secret slots: any env var name matching PASSWORD/SECRET/TOKEN/API_KEY/PRIVATE/CREDENTIAL/_URL/_URI/_DSN (URLs may embed credentials). Over-inclusive on purpose.
- Component evidence uses a service's anchor fact (port, framework, worker, runtime) rather than its first fact; alphabetical fact order made `redis` look like the reason for the ECS service.
- GitHub secret scanning flagged AWS's documented example access key ID (an ASIA-prefixed placeholder) in a test (alert #1, resolved as used_in_tests). Never write AWS-key-shaped literals, even documented examples: build them at runtime (`"AKIA" + "IOSFODNN7" + "EXAMPLE"`). The old literal remains in git history of the first pushes; it is a non-functional placeholder.
- Terraform provider mirror lives at ~/.cache/prodpath/terraform-mirror (hashicorp/aws 6.69.1, Windows amd64 only, created once with `terraform providers mirror`, user-approved, ADR-015). Validate runs `init -backend=false -plugin-dir=<mirror>` in a temp copy under `.prodpath/tfcheck/`. CHECKPOINT_DISABLE=1 stops terraform's own update check from using the network.
- Generated Terraform: ECS services use `ignore_changes = [task_definition]` so CI deploys are not reverted; ECR repos are IMMUTABLE (never reuse a tag); Redis has in-transit encryption on, so clients need rediss://.
- Price data: real Price List files were inspected once (usagetype has a region prefix like APS3-, tiers in priceDimensions, Global- SKUs hold free allowances). NAT gateway pricing is only in the 315 MB EC2 offer, so NAT is never priced; its trap says so. tests/fixtures/prices/ap-south-1.json holds made-up round numbers labelled TEST ONLY: never commit real AWS prices.
- Forecast defaults (1 req/s, 10 KB responses, 2 KB logs per request, 30 task starts) are placeholders; per-request log volume and S3/SQS ratios are not extracted from code yet (Phase 7 candidate). Always-free tiers are not applied, so figures lean high. Fargate and ALB lines do not scale with spike because nothing autoscales (the no-autoscaling trap says so).
- Traps are ranked by severity first, then estimated impact, so an unpriced high-severity trap (no outbound path) is listed first.
- CloudFront prices are in the GLOBAL `AmazonCloudFront` offer (no region segment), keyed by edge geography (IN-, US-, EU-...); the per-region file only has Origin Shield and Lambda@Edge. `prices update` must be re-run once to add CloudFront to an existing snapshot. A usagetype prefix check like `ap-south` also matches `ap-southeast-*`: use `ap-south-`.
- The CloudFront certificate must be in us-east-1 and is a required variable (`site_certificate_arn`); no second provider alias is generated. Price class defaults to PriceClass_All (cheaper classes exclude India/Asia).
- The alerts SNS topic is deliberately NOT KMS-encrypted: CloudWatch cannot publish to a topic using the AWS-managed key. The e-mail subscription must be confirmed by link or no alarm reaches anyone.
- Autoscaling is CPU-only (no request-count or queue-depth scaling); workers stay at their minimum in the forecast because their load is unknown. `rps_per_task` (25) is a placeholder: load-test one task to replace it.
- In shell heredocs, `
` inside Python strings and mixed quotes keep getting mangled; write patch scripts and templates with the Write tool and run them as files.
- phi3 summaries are shallow and sometimes wrong (for example "Next.js is not production-ready"); citations are valid but the content is low-trust. The plan labels model risks as model-written; the deterministic plan and forecast do not depend on them. A larger model or better prompts would be the fix if summaries matter.
- Build backend is hatchling (needed so `prodpath` is installable as a console script).

## Changelog

- 2026-10-23 | phase-11 (partial) | Added `prodpath run`, docs/DEMO.md, scripts/demo.ps1, README quickstart fix | User asked how to demo and test; README referenced a command that did not exist | src/prodpath/cli.py, tests/test_run.py, docs/DEMO.md, scripts/demo.ps1, README.md
- 2026-10-22 | phase-8 | Autoscaling + alarms in Terraform, build_alarms shared with the cost model, traffic-driven task counts and rps_per_task, alarm pricing, two traps, real alerts step (ADR-018) | Phase 8 roadmap | src/prodpath/providers/aws/*, src/prodpath/forecast.py, tests/*, docs/*
- 2026-10-22 | phase-7 | Static site detection, rule_static, static_site.tf, frontend step, CloudFront pricing (global offer), two traps, fixture mono_d, ROADMAP re-plan (ADR-017) | Phase 7 roadmap | src/prodpath/{detect,facts/manifests,forecast,render}.py, src/prodpath/providers/aws/*, tests/*, docs/*
- 2026-10-21 | phase-6 | Added forecast.py, providers/aws/{pricing,costs,traps}.py, render_forecast, `prices update` and `forecast` commands, Forecast model, usage.toml, 10 traps, committed TEST-ONLY price snapshot, hand-computed forecast tests (ADR-016) | Phase 6 roadmap | src/prodpath/*, tests/*, docs/*
- 2026-10-21 | phase-5 | Added providers/aws/iac.py + 19 Jinja2 templates, iac_check.py (self-scan, fmt, validate), Component.params, reworked steps, Terraform section in PLAN.md, doctor mirror check, `tf` test marker; removed AWS-key-shaped literals from the repo after a GitHub secret-scanning alert (ADR-015) | Phase 5 roadmap | src/prodpath/{providers/aws,iac_check,render,cli,doctor,models}.py, tests/*, docs/*
- 2026-10-21 | phase-4 | Added Provider protocol, AWS rules and steps, render.py, `prodpath plan`, Prefs/Step models and richer Component/Architecture (ADR-014); goldens for plans | Phase 4 roadmap | src/prodpath/{providers,render,cli,models}.py, tests/*, docs/*
- 2026-10-21 | phase-3 | Added llm.py, summarize.py, doctor.py, `summarize` and real `doctor` commands, benchmark script, Summaries models, llm_cache table; chose phi3 default (ADR-012, ADR-013) | Phase 3 roadmap | src/prodpath/*, scripts/*, tests/*, docs/*
- 2026-10-21 | phase-2 | Added facts/* extractors, extract.py, edges.py, redact.py, `prodpath facts`, SystemModel.not_analyzed, goldens and invariants (ADR-011) | Phase 2 roadmap | src/prodpath/*, tests/*, docs/*
- 2026-10-21 | phase-1 | Added scan.py, detect.py, cache.py, `prodpath scan`, FileEntry/Inventory/ServiceCandidate models, golden + rule + cache tests; added pyyaml (ADR-010) | Phase 1 roadmap | src/prodpath/{scan,detect,cache,cli,models}.py, tests/*, docs/*
- 2026-10-21 | phase-0 | Bootstrapped uv project, models.py contracts, CLI stub, 3 fixtures, socket guard, tests; recorded real GPU specs | Phase 0 roadmap | pyproject.toml, src/prodpath/*, tests/*, docs/ARCHITECTURE.md, docs/ROADMAP.md
- 2026-10-21 | phase-0 | Created documentation set (CLAUDE.md, MEMORY.md, ARCHITECTURE, ROADMAP, DECISIONS, CODING_STANDARDS, TESTING, SECURITY) | Project kickoff after design discussion | all docs
