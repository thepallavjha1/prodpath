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

- Phase: **2 (fact extraction) implemented; Phase 1 and 2 both wait on the real-monorepo check** (the only unmet exit criteria).
- Works: `prodpath scan` and `prodpath facts [--path] [--service]` (writes `.prodpath/system.json`); extractors in `src/prodpath/facts/` (python ast, javascript tree-sitter, docker, compose, manifests/env), `extract.py` (stage 3 with per-file facts cache), `edges.py` (http and shared-infra edges), `redact.py`. Goldens for detect and system output on mono_a/b/c; secret-leak invariants with fake secrets (`hunter2`, `AKIAIOSFODNN7EXAMPLE`). 70 tests, ruff, mypy --strict green.
- Code is published at https://github.com/thepallavjha1/prodpath (public, branch main). Commit and push after each task.
- Next action: user runs `prodpath scan` and `prodpath facts` on the real monorepo, reports wrong services and spot-checks 10 facts; each miss becomes a fixture and a test. Then Phase 3 (local LLM) on the user's go-ahead.

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
- Which local model gives acceptable structured-JSON quality on this hardware? Decide in Phase 3 with a small benchmark.
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
- Build backend is hatchling (needed so `prodpath` is installable as a console script).

## Changelog

- 2026-10-21 | phase-2 | Added facts/* extractors, extract.py, edges.py, redact.py, `prodpath facts`, SystemModel.not_analyzed, goldens and invariants (ADR-011) | Phase 2 roadmap | src/prodpath/*, tests/*, docs/*
- 2026-10-21 | phase-1 | Added scan.py, detect.py, cache.py, `prodpath scan`, FileEntry/Inventory/ServiceCandidate models, golden + rule + cache tests; added pyyaml (ADR-010) | Phase 1 roadmap | src/prodpath/{scan,detect,cache,cli,models}.py, tests/*, docs/*
- 2026-10-21 | phase-0 | Bootstrapped uv project, models.py contracts, CLI stub, 3 fixtures, socket guard, tests; recorded real GPU specs | Phase 0 roadmap | pyproject.toml, src/prodpath/*, tests/*, docs/ARCHITECTURE.md, docs/ROADMAP.md
- 2026-10-21 | phase-0 | Created documentation set (CLAUDE.md, MEMORY.md, ARCHITECTURE, ROADMAP, DECISIONS, CODING_STANDARDS, TESTING, SECURITY) | Project kickoff after design discussion | all docs
