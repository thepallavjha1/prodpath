# TESTING.md

Tests are how a vibe-coded project stays trustworthy. Write the test first, then the smallest code that passes.

## 1. Layers

| Layer | What it covers | Speed | Uses model/network |
|---|---|---|---|
| Unit | Pure functions: detectors, parsers, rule tables, price math | ms | no |
| Stage | One stage on a fixture repo, compared with a golden file | < 1 s each | no (`FakeLLM`) |
| Pipeline | `prodpath run` on fixtures end to end | seconds | no (`FakeLLM`) |
| LLM integration | Real Ollama on small fixtures; checks schema validity and evidence citation | slow | local Ollama only; marked `llm` |

Default `pytest -q` runs everything except `-m llm` and `-m tf`. `-m tf` runs real `terraform validate` against the local provider mirror (about 2.5 minutes); run it before finishing any change to `providers/aws/templates/` or `iac.py`.

## 2. Fixtures (`tests/fixtures/`)

Small synthetic repos, committed. Never real customer code.

- `mono_a/`: one Flask service + Postgres
- `mono_b/`: FastAPI + Celery worker + Redis + docker-compose
- `mono_c/`: 6+ services, Python and Node, pnpm workspace, shared libs, one cron job, one service with local file writes
- `mono_d/`: mixed frontends: Vite+React SPA, Next.js with static export, SSR Next.js, an nginx-served docs site, and a Flask API with Postgres (Phase 7)
- Add a fixture for each bug found on the real monorepo (reduced to the minimal reproduction).

## 3. Golden files (`tests/golden/`)

- Stage outputs (`inventory.json`, `system.json`, `architecture.json`, `PLAN.md`, `FORECAST.md`, Terraform) are compared against goldens.
- Goldens are updated deliberately with `pytest --update-golden`. The commit message must explain why the output legitimately changed. Never update goldens just to get green.

## 4. Invariants (property-style tests that must always hold)

1. Every `Fact` has at least one `Evidence`.
2. No secret value appears in any output, log line, prompt or snippet (scan fixtures that deliberately contain fake secrets such as `password=hunter2`, plus AWS-key-shaped strings built at runtime in tests (never literals: GitHub secret scanning flags them)).
3. Every `CostLine` has a `price_ref` that exists in the price snapshot used by the test.
4. Every forecast assumption renders with its source (`user`, `default` or `inferred`).
5. Running a stage twice on unchanged input produces byte-identical output and, on the second run, does no re-extraction (cache hit counters).
6. Output files are only written under `.prodpath/`.

## 5. No-network guard

A session-scoped autouse fixture patches `socket.socket.connect` so that any connection to a non-localhost address fails the test. Tests that need Ollama are marked `llm` and may connect to `127.0.0.1:11434` only. The price snapshot used in tests is a small committed file; `prices update` is tested with a stubbed HTTP transport.

## 6. LLM testing rules

- `FakeLLM` returns canned, schema-valid objects keyed by a hash of the prompt. Use it for all fast tests.
- Test the failure path too: invalid JSON from the fake triggers one repair retry, then a clear error.
- `llm`-marked tests check: schema validity, evidence ids cited exist in the input, no invented service names. They report seconds per call so model choices can be compared (Phase 3 benchmark).
- Never assert exact model prose. Assert structure and evidence.

## 7. Forecast tests

- Pin a tiny price snapshot in `tests/fixtures/prices/`.
- Hand-compute at least one full forecast per fixture in a comment and assert the tool matches within rounding.
- One test per trap: a minimal architecture that triggers it, and one that must not.

## 8. Terraform tests

- If `terraform` is on PATH: run `fmt -check` and `validate` on generated output for each fixture. Skip with a clear reason otherwise.
- Always: grep generated files for hard-coded account IDs, access keys and secret values; fail if found.

## 9. Coverage and quality gates

- Gate on the invariants above, not on a coverage percentage. Aim for meaningful branches covered in `detect.py`, `facts/`, `providers/aws/rules.py`, `traps.py` and `forecast.py`.
- Before any commit: `ruff check`, `ruff format --check`, `mypy src`, `pytest -q`.

## 10. Real-monorepo checks (manual, recorded in MEMORY.md)

After each phase exit, run the tool on the real monorepo and record: services found vs expected, spot-checked facts, wall-clock cold and warm, and anything surprising. Turn each surprise into a fixture and a test.
