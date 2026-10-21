"""Checks on generated Terraform: secret/account-id self-scan, `terraform fmt`, `validate`.

Nothing here touches the network or any AWS account. `validate` reads a local provider mirror
(ADR-015); without it, validate is reported as not run instead of being guessed.
"""

import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_MIRROR = Path.home() / ".cache" / "prodpath" / "terraform-mirror"
MIRROR_COMMAND = "terraform providers mirror {mirror}   # needs a config requiring hashicorp/aws"
TIMEOUT_SECONDS = 300

# Things that must never appear in generated files (SECURITY.md sections 3 and 5).
FORBIDDEN = {
    "12-digit account id": re.compile(r"(?<![\w.-])\d{12}(?![\w.-])"),
    "AWS access key": re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    "private key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "literal password": re.compile(r"""(?i)\b(?:master_)?password\s*=\s*["'][^"'$\s]"""),
    "literal secret": re.compile(
        r"""(?i)\b(?:secret_string|secret_key|access_key)\s*=\s*["'][^"'$\s]"""
    ),
}


@dataclass
class CheckResult:
    name: str
    status: str  # "ok" | "fail" | "skipped"
    detail: str


@dataclass
class TerraformReport:
    files: list[str]
    gaps: list[str]  # components with no template, listed in PLAN.md
    checks: list[CheckResult] = field(default_factory=list)


def find_violations(files: dict[str, str]) -> list[str]:
    found = []
    for name, text in sorted(files.items()):
        for label, pattern in FORBIDDEN.items():
            if pattern.search(text):
                found.append(f"{name}: contains a {label}")
    return found


def _run(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    # CHECKPOINT_DISABLE stops terraform's own update check from phoning home.
    env = {**os.environ, "CHECKPOINT_DISABLE": "1", "TF_IN_AUTOMATION": "1", "NO_COLOR": "1"}
    return subprocess.run(  # noqa: S603 - fixed argv, no shell
        args, cwd=cwd, env=env, capture_output=True, text=True, timeout=TIMEOUT_SECONDS, check=False
    )


def format_text(text: str, terraform: str) -> str:
    """Return `terraform fmt` output for one file's text (stdin to stdout)."""
    result = subprocess.run(  # noqa: S603
        [terraform, "fmt", "-"], input=text, capture_output=True, text=True,
        env={**os.environ, "CHECKPOINT_DISABLE": "1"}, timeout=TIMEOUT_SECONDS, check=False,
    )  # fmt: skip
    if result.returncode != 0:
        raise ValueError(f"terraform fmt failed: {result.stderr.strip()[:300]}")
    return result.stdout


def format_files(files: dict[str, str], terraform: str) -> dict[str, str]:
    """Format every .tf file; other files (README, tfvars example) pass through unchanged."""
    return {
        name: format_text(text, terraform) if name.endswith(".tf") else text
        for name, text in files.items()
    }


def validate_files(
    files: dict[str, str], terraform: str, mirror: Path, workdir: Path
) -> CheckResult:
    """Run init -backend=false + validate on a throwaway copy inside `workdir`."""
    if not mirror.is_dir():
        return CheckResult(
            "terraform validate",
            "skipped",
            f"no provider mirror at {mirror}. One-time setup: "
            + MIRROR_COMMAND.format(mirror=mirror),
        )
    workdir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=workdir) as tmp:
        target = Path(tmp)
        for name, text in files.items():
            if name.endswith(".tf"):
                (target / name).write_text(text, encoding="utf-8", newline="\n")
        init = _run(
            [
                terraform,
                "init",
                "-backend=false",
                "-input=false",
                f"-plugin-dir={mirror.as_posix()}",
            ],
            cwd=target,
        )
        if init.returncode != 0:
            tail = (init.stderr or init.stdout).strip()[-400:]
            return CheckResult(
                "terraform validate", "skipped", f"init from the mirror failed: {tail}"
            )
        result = _run([terraform, "validate", "-no-color"], cwd=target)
    if result.returncode == 0:
        return CheckResult("terraform validate", "ok", "configuration is valid")
    return CheckResult(
        "terraform validate", "fail", (result.stderr or result.stdout).strip()[:1500]
    )


def run_checks(
    files: dict[str, str],
    mirror: Path = DEFAULT_MIRROR,
    workdir: Path | None = None,
    which: Callable[[str], str | None] = shutil.which,
) -> tuple[dict[str, str], list[CheckResult]]:
    """Self-scan, then fmt and validate when terraform is available. Returns (files, results)."""
    violations = find_violations(files)
    if violations:
        return files, [CheckResult("self-scan", "fail", "; ".join(violations))]
    results = [CheckResult("self-scan", "ok", "no account ids, keys or literal secrets found")]
    terraform = which("terraform")
    if terraform is None:
        skipped = "terraform is not on PATH"
        return files, [*results, CheckResult("terraform fmt", "skipped", skipped),
                       CheckResult("terraform validate", "skipped", skipped)]  # fmt: skip
    formatted = format_files(files, terraform)
    results.append(CheckResult("terraform fmt", "ok", "formatted with terraform fmt"))
    if workdir is None:
        results.append(CheckResult("terraform validate", "skipped", "no work directory given"))
    else:
        results.append(validate_files(formatted, terraform, mirror, workdir))
    return formatted, results
