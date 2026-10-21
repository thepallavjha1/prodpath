---
description: Finish the session - run checks, sync docs, update MEMORY.md
---

Wrap up the current work. Do these in order and stop at the first failure to fix it.

1. Run `uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run pytest -q`. If anything fails, fix the cause. Never weaken or delete a test to get green.
2. Review `git diff`. Confirm: no secrets, no `.prodpath/` output, no model files, no unrelated changes, no dependency added without an ADR.
3. If the design changed, update `docs/ARCHITECTURE.md` and add an ADR in `docs/DECISIONS.md`.
4. Update `MEMORY.md`:
   - Rewrite **Current state** to describe now (phase, what works, what is next).
   - Add one **Changelog** entry (newest first): `YYYY-MM-DD | phase-N | what | why | files`.
   - Add or resolve **Open questions** and **Open items** (every `TODO` in code must be listed).
   - Add any **Gotchas** discovered this session.
5. Tick completed boxes in `docs/ROADMAP.md`. If the phase's exit criteria are met, say so explicitly and ask the user before starting the next phase.
6. Report to the user in under 10 lines: what changed, what was verified (with the commands run), what is next, and anything that needs their decision.

Extra context from the user (optional): $ARGUMENTS
