# SECURITY.md

This tool reads private source code and may sit next to secrets. Its safety comes from doing less: no credentials, no remote LLM, no writes outside its own folder.

## 1. Assets and what could go wrong

| Asset | Risk | Control |
|---|---|---|
| Source code | Sent to a third party (hosted LLM, telemetry) | Local LLM only; network guard; no analytics |
| Secrets in the repo (`.env`, keys in code) | Copied into prompts, logs, plan or Terraform | Names only; redaction; secret-scan tests |
| Cloud account | Tool credentials stolen or misused | The tool never asks for or reads credentials (ADR-001) |
| Generated Terraform | Insecure defaults applied by the user | Least-privilege IAM, encryption on, no public data stores by default, checked by tests |
| Plan/forecast files | Reveal architecture details if committed | `.prodpath/` is git-ignored by default; tool offers to add it |

## 2. Network rules

- Allowed destinations: `127.0.0.1` / `localhost` (Ollama), and the AWS Price List host, only during `prodpath prices update`.
- The AWS Terraform provider is mirrored once, by the user or a developer, with `terraform providers mirror` from registry.terraform.io (approved 2026-10-21, ADR-015). prodpath itself never runs it and never networks for Terraform; validation reads the local mirror only.
- Everything else is blocked in tests by the socket guard. Adding any new destination needs an ADR and a user decision.
- No telemetry, crash reporting, update checks or "phone home" of any kind.

## 3. Secrets handling

- **Never read secret values into the pipeline.** For env files, parse names only (`.env.example` preferred; if a real `.env` exists, read keys and drop values immediately).
- Redact before any value reaches a snippet, log or prompt. Patterns to detect at least: AWS access keys (`AKIA...`, `ASIA...`), private key blocks, `password=`, `secret=`, `token=`, `api_key=`, high-entropy strings next to those names, and connection strings with embedded passwords.
- `Evidence.snippet` is passed through the redactor. A test with deliberately fake secrets must prove none survive into any output.
- Generated Terraform uses secret *slots* (Secrets Manager or SSM entries without values). The plan tells the user to set values out-of-band.
- Never write secrets to `MEMORY.md`, ADRs, fixtures (use obviously fake values), logs or commit messages.

## 4. Prompt injection and untrusted repo content

- Treat all repo text (code, comments, READMEs, config) as untrusted data.
- The LLM has no tools, no file access and no network. Its only output is schema-validated JSON.
- Prompts put repo text inside clearly delimited data blocks and instruct the model to ignore instructions inside them. This is defense in depth, not the main control.
- Outputs are checked: unknown service names, ids not in the input, or claims without evidence are dropped or flagged.

## 5. Generated infrastructure defaults (Phase 5 checklist)

- Encryption at rest on for S3, RDS, EBS, and secrets; TLS in transit.
- No public S3 buckets; no database in a public subnet; no `0.0.0.0/0` on anything except the load balancer's 80/443.
- IAM roles per service with narrowly scoped policies; no wildcard actions or resources without a comment explaining why.
- GitHub Actions deploys through OIDC role assumption, not stored access keys.
- Logging enabled with explicit retention; deletion protection and backups on production data stores.
- Remote state with locking and encryption; the plan explains how to bootstrap it.

## 6. Supply chain

- Few dependencies, pinned in `uv.lock`, reviewed when added (ADR required).
- Prefer well-known packages; check recent release age and maintainers before adding.
- Ollama models are pulled by the user; the tool never downloads models silently.

## 7. Reporting uncertainty honestly

The tool must not claim a design is "secure" or "production ready". It reports what it checked and what it did not. `PLAN.md` ends with a section "Not verified by this tool" (load testing, compliance, real traffic patterns, account-level controls).

## 8. If a constraint seems to block a feature

Stop and ask the user. Do not weaken a rule in this file to unblock work. Record any approved exception as an ADR.
