# prodpath

Local, read-only CLI agent that reads your codebase and tells you how to take it to production.
Run it inside a repo and get:

- `PLAN.md`: ordered, detailed steps for AWS (other clouds later)
- `terraform/`: generated infrastructure code
- `FORECAST.md`: a monthly cost range plus the traps most likely to bite you ("What will this cost me, and what can bite me?")

`prodpath` is a working name.

## Guarantees

- Never touches your cloud account and never asks for credentials.
- Your code never leaves your machine: the only LLM is a local model through Ollama.
- Every claim in the plan points to evidence in your code (`path:line`).

## Status

Phases 0 to 8 built (scan, facts, local-LLM summaries, AWS plan, Terraform, cost forecast and traps, frontend hosting, autoscaling and alarms). See `MEMORY.md` for the current state and `docs/ROADMAP.md` for the plan.

## Quickstart (once Phase 0 is done)

```bash
uv sync
ollama pull <model>          # see docs/ARCHITECTURE.md section 14 for suggested sizes
uv run prodpath doctor       # checks Ollama, model, GPU/VRAM
cd /path/to/your/repo
uv run --project /path/to/prodpath prodpath run
```

Output lands in `.prodpath/out/` inside your repo (git-ignore it).

## Docs

| File | Purpose |
|---|---|
| `CLAUDE.md` | Instructions Claude Code reads every session |
| `MEMORY.md` | Living project memory: state, decisions, changelog, open questions |
| `docs/ARCHITECTURE.md` | Source of truth for design |
| `docs/ROADMAP.md` | Phases with exit criteria |
| `docs/DECISIONS.md` | Architecture decision records |
| `docs/CODING_STANDARDS.md` | Minimal, readable code rules and definition of done |
| `docs/TESTING.md` | Test strategy, fixtures, invariants |
| `docs/SECURITY.md` | Threat model and secret-handling rules |
| `.claude/commands/` | `/wrapup` and `/adr` slash commands |

## Working with Claude Code

Start every session with: "Read CLAUDE.md, then MEMORY.md, then tell me the current phase and the next task."
End every session with `/wrapup`.
