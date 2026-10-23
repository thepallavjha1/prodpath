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

Phases 0 to 8 built (scan, facts, local-LLM summaries, AWS plan, Terraform, cost forecast and traps, frontend hosting, autoscaling and alarms), plus `prodpath run`. Proven on four synthetic monorepos; not yet run on a real one. See `MEMORY.md` for the current state and `docs/ROADMAP.md` for the plan.

## Quickstart

```powershell
uv sync
uv run prodpath doctor                                # Ollama, model, GPU fit, terraform, provider mirror
uv run prodpath prices update --region ap-south-1     # once: the only networked command (public AWS Price List)
.\scripts\demo.ps1                                    # one-command demo on a fixture (add -Summarize for the local LLM)

# on your own repo:
uv run prodpath run --path C:\path\to\your\repo --summarize --usage usage.toml
```

Output lands in `.prodpath/out/` inside the repo you analysed (git-ignore it): `PLAN.md`, `FORECAST.md` and `terraform/`. Stage outputs (`inventory.json`, `system.json`, `summaries.json`, `architecture.json`, `forecast.json`) sit in `.prodpath/`.

Individual stages: `scan`, `facts`, `summarize`, `plan`, `forecast`, `prices update`, `doctor`. See `docs/DEMO.md` for a guided walkthrough, how to test it, and the known limits.

## Docs

| File | Purpose |
|---|---|
| `CLAUDE.md` | Instructions Claude Code reads every session |
| `MEMORY.md` | Living project memory: state, decisions, changelog, open questions |
| `docs/ARCHITECTURE.md` | Source of truth for design |
| `docs/ROADMAP.md` | Phases with exit criteria |
| `docs/DEMO.md` | How to demo and test it |
| `docs/DECISIONS.md` | Architecture decision records |
| `docs/CODING_STANDARDS.md` | Minimal, readable code rules and definition of done |
| `docs/TESTING.md` | Test strategy, fixtures, invariants |
| `docs/SECURITY.md` | Threat model and secret-handling rules |
| `.claude/commands/` | `/wrapup` and `/adr` slash commands |

## Working with Claude Code

Start every session with: "Read CLAUDE.md, then MEMORY.md, then tell me the current phase and the next task."
End every session with `/wrapup`.
