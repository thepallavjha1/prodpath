# CODING_STANDARDS.md

Goal: code a tired person can read in one pass and change with confidence. Minimal, direct, hackable. Teeth over ceremony.

## 1. Principles

1. **Plain over clever.** Straight-line functions beat patterns. If a junior can't follow it in one read, simplify.
2. **One obvious main path.** `cli.py` wires stages; each stage is a function from input to output. No hidden control flow, no plugin magic.
3. **Few moving parts.** Every file, class and dependency must earn its place. Prefer deleting code to adding options.
4. **Strong defaults, tiny config.** A CLI flag beats a config file; a config file beats a config framework.
5. **Rule of three.** Do not abstract until the same shape appears three times. The one exception is the `Provider` protocol, which is mandated by ADR-005.
6. **Say what is fixed.** If a module should not be edited casually (for example `models.py` contracts), put a one-line comment at the top saying so and why.
7. **Comments explain why.** Tradeoffs, surprising constraints, links to evidence. Never narrate the code.

## 2. Python rules

- Python 3.12, `from __future__ import annotations` not needed. Use built-in generics (`list[str]`, `X | None`).
- Format and lint with `ruff` (line length 100). Type-check `src/` with `mypy --strict` where practical; no `Any` in public signatures.
- Type hints on every function signature. pydantic v2 models **only at stage boundaries** (`models.py`); inside a stage use plain dataclasses, tuples or dicts.
- `pathlib` for paths, `logging` for output (no `print` outside `cli.py`), `argparse` for the CLI.
- Functions aim for under 40 lines and one job. Modules under about 300 lines; split by responsibility, not by layer.
- Names: long and clear beats short and cryptic (`detect_service_roots`, not `dsr`). Booleans read as questions (`is_stateless`).
- No global mutable state. Pass dependencies in (for example the `LLM` object) so tests can fake them.
- No bare `except`, no `except Exception: pass`. Catch the narrowest exception, add context, re-raise or return a clear error.
- No silent fallbacks. If something is skipped or guessed, record it in the output ("Not analyzed", `heuristic` label, `default` assumption).
- Determinism: sort anything that is written to disk, fix temperature at 0, avoid timestamps inside hashed content.
- Prefer returning values over mutating arguments.

## 3. Data and I/O

- All cross-stage data are the models in `models.py`. Changing a model means updating `ARCHITECTURE.md` section 5 first.
- JSON on disk: `indent=2`, `sort_keys=True`, UTF-8, trailing newline. Include a `schema_version`.
- Never write outside the repo's `.prodpath/` directory or `~/.cache/prodpath/`.
- Reading files: bound size (skip or truncate very large files, record that you did), handle decode errors explicitly.

## 4. The LLM boundary

- Only `llm.py` talks to Ollama. Everything else uses the `LLM` protocol.
- Prompts live in `summarize.py` as module-level constants, short and plain. No giant prompt frameworks.
- Always request schema-constrained output and validate it. On failure: one repair retry, then raise with the prompt hash for debugging.
- Never put raw secrets or full files in prompts. Build prompts from facts and small evidence snippets.
- Any new LLM use must be justified in the PR/commit message: "why can't a rule or parser do this?"

## 5. Dependencies

- Allowed by default: `pydantic`, `httpx`, `jinja2`, `tree-sitter` (+ language pack). Dev: `pytest`, `ruff`, `mypy`.
- Anything else needs an ADR. Pin versions via `uv.lock`; commit the lock file.
- Do not add a dependency for something about 20 lines of stdlib can do.

## 6. Tests (summary; see `TESTING.md`)

- Behavior tests at the stage level using fixture repos; golden files for outputs.
- Fast tests use `FakeLLM` and never touch the network.
- A bug fix starts with a failing test that reproduces it.

## 7. Git and review hygiene

- Small commits, one concern each. Message: `phase-N: <imperative summary>`.
- Do not mix refactors with behavior changes.
- Before committing: `ruff check`, `ruff format`, `mypy src`, `pytest -q` all pass.
- Never commit `.prodpath/`, model files, secrets, or real customer code. Fixtures are synthetic.

## 8. Definition of done (every task)

- [ ] Behavior implemented in the current roadmap phase only
- [ ] Tests added or updated; all checks green
- [ ] No new dependency or module without an ADR
- [ ] `ARCHITECTURE.md` updated if the design changed
- [ ] `MEMORY.md` updated (changelog, current state, open items)
- [ ] No secret values in code, logs, fixtures, prompts or outputs
- [ ] Output files list their uncertainty (heuristic facts, default assumptions)

## 9. When in doubt

Choose the simpler design, write down the tradeoff in a comment or ADR, and ask the user if reversing the choice later would be expensive.
