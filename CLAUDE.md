# CLAUDE.md

`prodpath` (working name) is a **local, read-only CLI agent**. Run inside a repo, it reads the codebase and writes:
a step-by-step production plan (AWS first), Terraform, and a usage-aware cost/risk forecast
("What will this cost me, and what can bite me?").

## Read order (every session, before touching code)

1. `MEMORY.md` - current state, last changes, open questions. Start here.
2. `docs/ARCHITECTURE.md` - source of truth for design. Code follows the doc, not the other way round.
3. `docs/ROADMAP.md` - find the current phase. Work only on the current phase unless told otherwise.
4. First time in a session you write code: also read `docs/CODING_STANDARDS.md`, `docs/TESTING.md`, `docs/SECURITY.md`.

## Hard constraints (never break, never "temporarily" bypass)

- **Read-only.** The tool never asks for, reads, or uses cloud credentials. It never calls any cloud API except the public AWS Price List download (`prodpath prices update`, explicit command only).
- **Code never leaves the machine.** The only LLM is a local model via Ollama on `localhost`. No hosted LLM APIs, no telemetry, no network calls except the two above. Tests enforce this.
- **Deterministic first, LLM second.** Parsing, rules, prices and Terraform come from code and templates. The LLM summarizes and explains, always with schema-validated output and evidence. It never invents prices, services or facts.
- **Never read secret values.** Record env var *names* only. Never copy `.env` contents into any output, log or prompt.
- **Every fact carries evidence** (`path:line` + short snippet). No evidence, no fact.

## Workflow loop (follow for every task)

1. Restate the task in one or two lines and name the roadmap phase it belongs to.
2. If it changes design (new module, new data contract, new dependency): update `docs/ARCHITECTURE.md` **first** and add an entry to `docs/DECISIONS.md`. If unsure, ask the user before coding.
3. Write or update tests first for the behavior (see `docs/TESTING.md`), then the smallest code that passes.
4. Run the checks (below). Fix until green. Do not weaken or delete a test to get green.
5. Update `MEMORY.md` (changelog entry + "Current state" + open questions). This is part of the task, not optional.
6. Summarize for the user: what changed, what was verified, what is next.

Use `/wrapup` at the end of any session to run steps 4 to 6 in order.

## Commands (valid once Phase 0 is done; if missing, Phase 0 is the task)

```
uv sync                                   # install
uv run prodpath --help                    # CLI
uv run pytest -q                          # fast tests (no model, no network)
uv run pytest -m llm                      # slow tests that hit local Ollama
uv run pytest -m tf                       # slow: real terraform validate via the local provider mirror
uv run ruff check . && uv run ruff format --check .
uv run mypy src
```

## Code style (short version; full rules in `docs/CODING_STANDARDS.md`)

- Plain, readable, minimal Python 3.12. One obvious main path. No framework sprawl, no enterprise layering.
- Small modules, small functions (aim < 40 lines), explicit data contracts in `models.py` (pydantic v2).
- Comments explain *why* and tradeoffs, not what the line does.
- Strong defaults, tiny config. Prefer a CLI flag over a config system.
- stdlib first (`argparse`, `sqlite3`, `pathlib`, `logging`, `ast`). Ask before adding any dependency.
- Fail loudly with an actionable message. No bare `except`, no silent fallbacks.

## Do not

- Add a dependency, a new top-level module, or a new abstraction without noting it in `docs/DECISIONS.md`.
- Build things from a later roadmap phase "while you're here".
- Make the LLM do something a rule or a parser can do.
- Print or store anything that could contain secrets.
- Leave a `TODO` in code without a matching line in `MEMORY.md` under Open items.
- Edit golden files in `tests/golden/` without explaining in the commit message why output legitimately changed.

## Ask the user instead of guessing when

- A decision changes the architecture, a data contract, or the safety constraints above.
- The right behavior depends on the user's hardware (see MEMORY.md, "Open questions").
- Two reasonable designs exist and the cost of reversing later is high.

## Git hygiene

Small commits, one concern each. Message format: `phase-N: <imperative summary>` (for example `phase-1: detect docker-compose services`). Never commit `.prodpath/` output or model files.
