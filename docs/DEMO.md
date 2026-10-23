# DEMO.md

How to see prodpath work in about five minutes, and how to test it. Commands are PowerShell (Windows); on bash replace `$env:TEMP` with `/tmp`.

## What it is, in one paragraph

Run it against a repo. It reads the code (never your cloud account, never secret values), finds the deployable services, and writes a production plan for AWS, ready-to-review Terraform, and a monthly cost range with the traps most likely to bite you. Everything is deterministic and evidence-backed (`path:line`) except the optional local-LLM summaries.

## Two rules that avoid the most common errors

1. **Run commands from the `prodpath` folder**, or point at it from anywhere:
   `uv run --project C:\Users\Asus\OneDrive\Desktop\Agentic_Cloud\prodpath prodpath <command>`.
   From any other folder, `uv run prodpath` fails with `program not found`.
2. **`--path` must be a local folder, not a URL.** prodpath never downloads code. Clone first:
   `git clone https://github.com/<you>/<repo>` then `--path C:\path\to\<repo>`.

## One-time setup

```powershell
cd C:\Users\Asus\OneDrive\Desktop\Agentic_Cloud\prodpath
uv sync
uv run prodpath doctor                                  # Ollama, model, GPU fit, terraform, provider mirror
uv run prodpath prices update --region ap-south-1       # the ONLY networked command (public AWS Price List)
```

`doctor` should say `ok` for everything. Warnings are explained in its output (for example "no provider mirror": Terraform `validate` is then skipped, not faked).

## The fast demo (one command)

```powershell
.\scripts\demo.ps1                 # mixed monorepo fixture, no LLM, about 15 seconds
.\scripts\demo.ps1 -Summarize      # add local-LLM summaries (about 2 minutes on this laptop)
.\scripts\demo.ps1 -Repo C:\path\to\your\repo     # your own repo instead of the fixture
.\scripts\demo.ps1 -Open           # open PLAN.md and FORECAST.md when done
```

The script copies the fixture to a temp folder first, so your working tree stays clean. Outputs land in `<repo>\.prodpath\out\`.

## The guided demo (step by step)

Use a copy so nothing is written into the repo:

```powershell
$demo = "$env:TEMP\prodpath-demo"
Remove-Item $demo -Recurse -Force -ErrorAction SilentlyContinue
Copy-Item tests\fixtures\mono_d $demo -Recurse
```

`mono_d` is a mixed monorepo: a Flask API with Postgres, a Vite+React SPA, a statically exported Next.js site, an SSR Next.js dashboard and an nginx-served docs site.

| Step | Command | What to look at |
|---|---|---|
| 1. Find services | `uv run prodpath scan --path $demo` | 5 services with kind and the file/line that proved it. 3 are `static`, 2 are `web`. |
| 2. Facts | `uv run prodpath facts --path $demo --service apps-api` | Postgres, Flask, port, health path, `DATABASE_URL` as a *name*, each with `path:line`. No values anywhere. |
| 3. Summaries (optional) | `uv run prodpath summarize --path $demo` | Purpose and cited risks written by the local model. **Treat as low-trust**: the 3.8B model is shallow and sometimes wrong. The plan labels them "model-written". |
| 4. Plan + Terraform | `uv run prodpath plan --path $demo` | Prints self-scan / fmt / validate results. Open `.prodpath\out\PLAN.md`: architecture table (reason + evidence per component), 10 ordered steps, unknowns, "Not verified by this tool". |
| 5. Forecast | `uv run prodpath forecast --path $demo` | Open `.prodpath\out\FORECAST.md`: low/expected/spike, biggest cost drivers, every assumption with its source, every cost line with a `price_ref`, ranked traps. |
| 6. Change the numbers | create `usage.toml` with `avg_requests_per_second = 5` and `response_kb = 20`, then `forecast --usage usage.toml` | The totals move; those assumptions now show **user** instead of **default**. |
| 7. Everything at once | `uv run prodpath run --path $demo --summarize` | Steps 3 to 5 in one command. |

Also look at `.prodpath\out\terraform\`: `ecs.tf`, `alb.tf`, `static_site.tf`, `autoscaling.tf`, `alarms.tf`, a `terraform.tfvars.example` with every `<PLACEHOLDER>` you must fill, and a `README.md`.

## Prove the guarantees

- **Read-only on your repo**: in a git repo, `git status` after a run shows only `.prodpath/` as new.
- **No secrets leak**: `mono_a` contains fake secrets. `uv run prodpath run --path <copy of mono_a>` then `Select-String -Path <copy>\.prodpath -Pattern hunter2 -Recurse` finds nothing, while the env var *names* are present.
- **Local only**: the only network command is `prices update`. Tests enforce a localhost-only socket guard.
- **Evidence everywhere**: pick any fact or plan row and open the cited file and line.
- **Honest about gaps**: the plan lists "Unknowns" and "Not analyzed", the forecast lists "Not priced" and "Not included in any figure" (no NAT gateway, free tiers not applied).

## How to test it

| Level | Command | Time | Needs |
|---|---|---|---|
| Fast suite | `uv run pytest -q` | ~30 s | nothing (no network, no model) |
| Lint and types | `uv run ruff check . ; uv run ruff format --check . ; uv run mypy src` | ~10 s | nothing |
| Real Terraform | `uv run pytest -m tf` | ~2 min | `terraform` + the provider mirror |
| Real model | `uv run pytest -m llm -s` | ~1 min | Ollama with `phi3` |
| Model benchmark | `uv run python scripts/benchmark_models.py phi3:latest` | minutes | Ollama |

## The real test: your own monorepo

```powershell
uv run prodpath run --path C:\path\to\your\repo --summarize --usage usage.toml
```

Then check, in this order:

1. **Services**: does `prodpath scan --path <repo>` list every service and frontend you expect, with the right kind? Missing or wrong ones are the most valuable bug reports.
2. **Facts**: spot-check 10 random facts (`prodpath facts`) against the cited lines.
3. **Plan**: read the unknowns and the architecture reasons. Do they make sense for your system?
4. **Terraform**: `cd <repo>\.prodpath\out\terraform; terraform init -backend=false; terraform validate`.
5. **Forecast**: put your real traffic in `usage.toml` (see keys below). Read the traps list first.

Send me what is wrong; each problem becomes a minimal fixture and a test.

### usage.toml keys

```toml
avg_requests_per_second = 20      # average over the month, per web service (not the peak)
response_kb = 25
[service."apps-api"]              # per-service overrides
avg_requests_per_second = 60
rps_per_task = 40                 # requests/second one task handles at 60% CPU
```

Unknown keys are rejected with the list of allowed ones. All names live in `DEFAULTS` in `src/prodpath/forecast.py`.

## Known limits (say these out loud in a demo)

- Proven on four synthetic fixtures; **not yet run on a real monorepo**.
- Terraform is generated and validated but **never applied** (the tool never touches AWS).
- Forecast accuracy is **unmeasured** until real AWS bills are compared (Phase 10).
- Traffic defaults are placeholders (Phase 9 will set "medium" defaults).
- Fact extraction covers Python and JS/TS; Go and Java services are detected but not analyzed.
- NAT gateway cost is not priced; the generated network has no NAT by default and a trap says what that breaks.
- Local-LLM summaries are low-trust prose; the plan and forecast do not depend on them.
