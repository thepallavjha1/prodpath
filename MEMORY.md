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

- Phase: **5 (Terraform generation) implemented and validated; Phases 1 to 5 wait on the user's real-monorepo review.** Exit criteria met on fixtures: `terraform validate` passes for generated code on mono_a/b/c (prod) and a kitchen-sink system (prod and nonprod), no secrets or account ids (self-scan plus tests), variables documented.
- Works: `prodpath plan` now also writes `.prodpath/out/terraform/` (versions, backend, main, variables, network, ecr, iam, secrets, ecs, alb, rds, elasticache, messaging, s3, scheduler, github_oidc, outputs, tfvars example, README), runs the self-scan, `terraform fmt`, and `terraform validate` (offline, against the local mirror), and adds a Terraform section to PLAN.md. Steps are now built around `terraform apply`. `prodpath doctor` checks for terraform and the mirror. 193 fast tests + 7 `-m tf` tests, ruff, mypy --strict green.
- Not generated yet (listed in PLAN.md and a manual step): App Runner, DocumentDB, DynamoDB, Amazon MQ, MSK, ElastiCache Memcached, alarms.
- Code is at https://github.com/thepallavjha1/prodpath (public, main). Commit and push after each task.
- Next action: user runs `scan`, `facts`, `summarize`, `plan` on the real monorepo, reviews PLAN.md and the Terraform, spot-checks 10 facts, states an acceptable cold-run time and confirms the AWS region. Then Phase 6 (forecast and traps) on the user's go-ahead.

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

- CPU model of the laptop (GPU: GTX 1650 4 GB; RAM: 8 GB, confirmed by the user).
- What cold-run time is acceptable on the real monorepo? (phi3 is about 12 s per service on this laptop.)
- Default AWS region for pricing. Currently `ap-south-1`; confirm.
- Which real monorepo is the first test target, and may a sanitized copy be used as a fixture?

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
- GitHub secret scanning flagged `ASIAIOSFODNN7EXAMPLE` (AWS's documented example key) in a test. Never write AWS-key-shaped literals, even documented examples: build them at runtime (`"AKIA" + "IOSFODNN7" + "EXAMPLE"`). The old literal remains in git history of the first pushes; it is a non-functional placeholder.
- Terraform provider mirror lives at ~/.cache/prodpath/terraform-mirror (hashicorp/aws 6.69.1, Windows amd64 only, created once with `terraform providers mirror`, user-approved, ADR-015). Validate runs `init -backend=false -plugin-dir=<mirror>` in a temp copy under `.prodpath/tfcheck/`. CHECKPOINT_DISABLE=1 stops terraform's own update check from using the network.
- Generated Terraform: ECS services use `ignore_changes = [task_definition]` so CI deploys are not reverted; ECR repos are IMMUTABLE (never reuse a tag); Redis has in-transit encryption on, so clients need rediss://.
- Build backend is hatchling (needed so `prodpath` is installable as a console script).

## Changelog

- 2026-10-21 | phase-5 | Added providers/aws/iac.py + 19 Jinja2 templates, iac_check.py (self-scan, fmt, validate), Component.params, reworked steps, Terraform section in PLAN.md, doctor mirror check, `tf` test marker; removed AWS-key-shaped literals from the repo after a GitHub secret-scanning alert (ADR-015) | Phase 5 roadmap | src/prodpath/{providers/aws,iac_check,render,cli,doctor,models}.py, tests/*, docs/*
- 2026-10-21 | phase-4 | Added Provider protocol, AWS rules and steps, render.py, `prodpath plan`, Prefs/Step models and richer Component/Architecture (ADR-014); goldens for plans | Phase 4 roadmap | src/prodpath/{providers,render,cli,models}.py, tests/*, docs/*
- 2026-10-21 | phase-3 | Added llm.py, summarize.py, doctor.py, `summarize` and real `doctor` commands, benchmark script, Summaries models, llm_cache table; chose phi3 default (ADR-012, ADR-013) | Phase 3 roadmap | src/prodpath/*, scripts/*, tests/*, docs/*
- 2026-10-21 | phase-2 | Added facts/* extractors, extract.py, edges.py, redact.py, `prodpath facts`, SystemModel.not_analyzed, goldens and invariants (ADR-011) | Phase 2 roadmap | src/prodpath/*, tests/*, docs/*
- 2026-10-21 | phase-1 | Added scan.py, detect.py, cache.py, `prodpath scan`, FileEntry/Inventory/ServiceCandidate models, golden + rule + cache tests; added pyyaml (ADR-010) | Phase 1 roadmap | src/prodpath/{scan,detect,cache,cli,models}.py, tests/*, docs/*
- 2026-10-21 | phase-0 | Bootstrapped uv project, models.py contracts, CLI stub, 3 fixtures, socket guard, tests; recorded real GPU specs | Phase 0 roadmap | pyproject.toml, src/prodpath/*, tests/*, docs/ARCHITECTURE.md, docs/ROADMAP.md
- 2026-10-21 | phase-0 | Created documentation set (CLAUDE.md, MEMORY.md, ARCHITECTURE, ROADMAP, DECISIONS, CODING_STANDARDS, TESTING, SECURITY) | Project kickoff after design discussion | all docs
