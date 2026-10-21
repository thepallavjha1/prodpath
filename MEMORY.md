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

- Phase: **1 (scan and service detection) implemented; waiting on the real-monorepo check** (the only unmet exit criterion).
- Works: `prodpath scan [--path]` prints the service table and writes `.prodpath/inventory.json` and `cache.sqlite`; `scan.py` (ignores, blake2b, mtime+size cache), `detect.py` (rules in ARCHITECTURE section 6), `cache.py`; golden tests for mono_a/b/c; second run re-hashes nothing (tested). 32 tests, ruff, mypy --strict all green.
- Next action: user runs `prodpath scan --path <real monorepo>` and reports missed or wrong services; each miss becomes a fixture and a test. Then Phase 2 (fact extraction) on the user's go-ahead.

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
- Build backend is hatchling (needed so `prodpath` is installable as a console script).

## Changelog

- 2026-10-21 | phase-1 | Added scan.py, detect.py, cache.py, `prodpath scan`, FileEntry/Inventory/ServiceCandidate models, golden + rule + cache tests; added pyyaml (ADR-010) | Phase 1 roadmap | src/prodpath/{scan,detect,cache,cli,models}.py, tests/*, docs/*
- 2026-10-21 | phase-0 | Bootstrapped uv project, models.py contracts, CLI stub, 3 fixtures, socket guard, tests; recorded real GPU specs | Phase 0 roadmap | pyproject.toml, src/prodpath/*, tests/*, docs/ARCHITECTURE.md, docs/ROADMAP.md
- 2026-10-21 | phase-0 | Created documentation set (CLAUDE.md, MEMORY.md, ARCHITECTURE, ROADMAP, DECISIONS, CODING_STANDARDS, TESTING, SECURITY) | Project kickoff after design discussion | all docs
