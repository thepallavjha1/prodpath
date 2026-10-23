# prodpath

**prodpath reads your code and tells you how to put it on AWS, what it will cost, and what can go wrong.**

You point it at a project folder. It looks at the code (it never touches your AWS account) and writes three things:

| You get | What it is |
|---|---|
| `PLAN.md` | A step-by-step plan: which AWS services to use, why, and the exact order to set them up |
| `terraform/` | Ready-to-review Terraform files for that plan (nothing is applied for you) |
| `FORECAST.md` | A monthly cost estimate (low, expected, spike) and the traps most likely to hurt you |

Every claim points to the file and line in your code that caused it.

## Is it safe?

- It **never connects to your AWS account** and never asks for passwords or keys.
- It **never reads secret values**. It only notes that a setting like `DATABASE_URL` exists.
- Your **code never leaves your computer**. The only AI used is a small model running locally (Ollama).
- It only writes inside a `.prodpath` folder in the project you analyse.
- The only thing it ever downloads is the public AWS price list (when you run `prices update`).

## What you need

| Need | Required? | Why |
|---|---|---|
| Windows with PowerShell | yes | the commands below are for PowerShell |
| [uv](https://docs.astral.sh/uv/) | yes | installs and runs the project (it brings the right Python itself) |
| Git | to analyse a GitHub repo | prodpath reads local folders, so you clone first |
| [Ollama](https://ollama.com) with the `phi3` model | only for `--summarize` | writes a short summary of each service |
| [Terraform](https://developer.hashicorp.com/terraform) | optional | lets prodpath check the Terraform it writes (skipped, not faked, if missing) |

## Set it up (one time, about 5 minutes)

Open PowerShell in the `prodpath` folder, then:

```powershell
uv sync
uv run prodpath doctor
uv run prodpath prices update --region ap-south-1
```

1. `uv sync` installs everything.
2. `doctor` checks your computer. `ok` is good. A `warn` is explained on the line and is usually fine (for example "no provider mirror" only means the Terraform check is skipped).
3. `prices update` downloads the public AWS price list once (about 25 MB). Change the region if you deploy elsewhere.

If you want summaries: install Ollama, then run `ollama pull phi3`.

## See it work (the easy way)

```powershell
.\scripts\demo.ps1
```

This copies a built-in sample project to a temporary folder, analyses it, and shows you where the results are. It takes about 15 seconds and does not change your files. Add `-Summarize` to also use the local AI (about 2 minutes), or `-Open` to open the results when done.

## Run it on your own project

**Step 1.** Get the project onto your computer as a normal folder. For a GitHub repo, clone it:

```powershell
git clone https://github.com/<you>/<repo> C:\code\myrepo
```

**Step 2.** From the `prodpath` folder, run it:

```powershell
uv run prodpath run --path C:\code\myrepo
```

Add `--summarize` if you installed Ollama. That's it.

**Step 3.** Open the results in `C:\code\myrepo\.prodpath\out\`:

- `PLAN.md`: start here. Read "Unknowns" and "Not verified by this tool" too: they tell you what it could not know.
- `FORECAST.md`: look at "Biggest cost drivers" and "What can bite me" first.
- `terraform\`: the infrastructure files. Read `README.md` inside for how to use them.

> Tip: the first run finds out what your project is made of, so check the service list near the top of `PLAN.md`. If a service is missing or wrong, that is the most useful thing you can tell the developer.

## Tell it about your real traffic

Out of the box the cost estimate uses placeholder traffic numbers, and says so. To use yours, create a file called `usage.toml`:

```toml
avg_requests_per_second = 2     # average over a month, per web service (not the busiest moment)
response_kb = 50                # typical size of one response
```

Then run again with `--usage usage.toml`:

```powershell
uv run prodpath run --path C:\code\myrepo --usage usage.toml
```

In `FORECAST.md`, every assumption is labelled `default` (a placeholder), `user` (your number) or `inferred` (worked out from your code).

Other useful options: `--env nonprod` for a cheaper test setup (one copy of each thing instead of two), `--region <aws-region>`.

## All the commands

| Command | What it does |
|---|---|
| `doctor` | checks your setup |
| `prices update` | downloads the AWS price list (the only command that uses the internet) |
| `scan --path <folder>` | lists the services it found and why |
| `facts --path <folder>` | lists what it learned about each service, with file and line |
| `summarize --path <folder>` | short summaries from the local AI |
| `plan --path <folder>` | writes `PLAN.md` and `terraform/` |
| `forecast --path <folder>` | writes `FORECAST.md` |
| `run --path <folder>` | does all of the above in one go |

Run any command with `--help` to see its options. Always start with `uv run prodpath ...`.

## When something goes wrong

| You see | What it means | Fix |
|---|---|---|
| `program not found` | you are in the wrong folder | `cd` into the `prodpath` folder first, or use `uv run --project <prodpath folder> prodpath ...` |
| `--path must be a local folder, not a URL` | prodpath cannot download code | `git clone` the repo, then use the cloned folder |
| `no price snapshot` | you skipped the price download | `uv run prodpath prices update --region ap-south-1` |
| `usage file not found` | wrong file name or location | check the name (watch for a stray dot) and the folder |
| `cannot reach Ollama` | the local AI is not running | start Ollama, or leave out `--summarize` |
| `terraform validate: not run` | no Terraform check set up | optional; everything else still works |
| A service is missing from the plan | detection missed it | tell the developer; it becomes a test |

## Honest limits

- It has been tested on built-in sample projects and one small real repo. It is **not yet proven on a large real monorepo**.
- The Terraform is checked for correctness but **never applied** by prodpath. Read it before you use it.
- Cost numbers are estimates from the public price list and your traffic assumptions. They have **not been compared with a real AWS bill yet**, so treat them as a guide.
- It understands Python and JavaScript/TypeScript code. Other languages are noticed but not analysed.
- The AI summaries are short and sometimes shallow. The plan and the cost forecast do not depend on them.

## Learn more

| File | What is in it |
|---|---|
| `docs/DEMO.md` | a guided walkthrough, how to test it, and the known limits |
| `docs/ARCHITECTURE.md` | how it is built |
| `docs/ROADMAP.md` | what is done and what is next |
| `docs/SECURITY.md` | the safety rules in detail |
| `docs/TESTING.md` | how it is tested |
| `docs/DECISIONS.md` | why each design choice was made |
| `MEMORY.md` | current state and notes between work sessions |

## For developers

```powershell
uv run pytest -q                  # fast tests (about 30 seconds)
uv run pytest -m tf               # also run real Terraform checks (about 2 minutes)
uv run ruff check . ; uv run mypy src
```

Working with Claude Code: start a session with "Read CLAUDE.md, then MEMORY.md, then tell me the current phase and the next task", and end it with `/wrapup`.
