"""Public GitHub intake for web mode (ADR-019, SECURITY.md section 3b).

Only https://github.com/<owner>/<repo>[/tree/<branch>] is accepted. The clone is shallow and
hardened, the code is only ever read, and size limits are enforced before analysis starts.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

CLONE_TIMEOUT_SECONDS = 120
MAX_REPO_BYTES = 300 * 1024 * 1024
MAX_REPO_FILES = 30_000

_OWNER = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})"
_REPO = r"[A-Za-z0-9._-]{1,100}"
_BRANCH = r"[A-Za-z0-9._/-]{1,100}"
_URL = re.compile(
    rf"^https://github\.com/(?P<owner>{_OWNER})/(?P<repo>{_REPO}?)(?:\.git)?"
    rf"(?:/tree/(?P<branch>{_BRANCH}))?/?$"
)


class RepoError(Exception):
    """A problem the visitor can act on; the message is safe to show."""


@dataclass(frozen=True)
class RepoRef:
    owner: str
    repo: str
    branch: str | None = None

    @property
    def clone_url(self) -> str:
        return f"https://github.com/{self.owner}/{self.repo}.git"

    @property
    def web_url(self) -> str:
        return f"https://github.com/{self.owner}/{self.repo}"


def parse_github_url(text: str) -> RepoRef:
    url = text.strip()
    match = _URL.match(url)
    if not match or len(url) > 300:
        raise RepoError(
            "Paste a public repository link like https://github.com/owner/repo "
            "(other sites and other link shapes are not accepted)."
        )
    owner, repo, branch = match["owner"], match["repo"], match["branch"]
    if repo in {".", ".."} or repo.endswith(".") or ".." in repo:
        raise RepoError("That repository name is not valid.")
    if branch and (".." in branch or branch.startswith(("/", "-")) or "//" in branch):
        raise RepoError("That branch name is not valid.")
    return RepoRef(owner, repo, branch)


Runner = Callable[..., "subprocess.CompletedProcess[str]"]


def _git(args: list[str], cwd: Path | None, run: Runner, env: dict[str, str]) -> str:
    try:
        result = run(
            ["git", *args], cwd=cwd, env=env, capture_output=True, text=True,
            timeout=CLONE_TIMEOUT_SECONDS, check=False,
        )  # fmt: skip
    except FileNotFoundError as error:
        raise RepoError("git is not installed on the server.") from error
    except subprocess.TimeoutExpired as error:
        raise RepoError(
            f"Cloning took longer than {CLONE_TIMEOUT_SECONDS} s; the repository is too big."
        ) from error
    if result.returncode != 0:
        raise RepoError(
            "Could not clone that repository. It must be public and the branch must exist."
        )
    return result.stdout.strip()


def clone(ref: RepoRef, dest: Path, run: Runner = subprocess.run) -> str:
    """Shallow, hook-free clone into `dest`; returns the commit sha and removes `.git`."""
    no_hooks = Path(tempfile.mkdtemp(prefix="prodpath-nohooks-"))
    env = {
        **os.environ,
        "GIT_TERMINAL_PROMPT": "0",  # private repos must fail, never prompt
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_LFS_SKIP_SMUDGE": "1",
    }
    args = [
        "-c", "core.symlinks=false", "-c", f"core.hooksPath={no_hooks.as_posix()}",
        "-c", "protocol.allow=never", "-c", "protocol.https.allow=always",
        "clone", "--depth", "1", "--single-branch", "--no-tags", "--no-recurse-submodules",
        "--quiet",
    ]  # fmt: skip
    if ref.branch:
        args += ["--branch", ref.branch]
    try:
        _git([*args, "--", ref.clone_url, str(dest)], None, run, env)
        sha = _git(["rev-parse", "HEAD"], dest, run, env)
    finally:
        shutil.rmtree(no_hooks, ignore_errors=True)
    shutil.rmtree(dest / ".git", ignore_errors=True)
    return sha


def check_limits(root: Path) -> None:
    """Refuse oversized repositories before any analysis (counts files, never opens them)."""
    files = total = 0
    for folder, _, names in os.walk(root):
        for name in names:
            files += 1
            if files > MAX_REPO_FILES:
                raise RepoError(f"The repository has more than {MAX_REPO_FILES:,} files.")
            try:
                total += os.lstat(os.path.join(folder, name)).st_size
            except OSError:
                continue
            if total > MAX_REPO_BYTES:
                raise RepoError(f"The repository is larger than {MAX_REPO_BYTES // 2**20} MB.")


def evidence_url(ref: RepoRef, sha: str, path: str, line: int | None) -> str:
    anchor = f"#L{line}" if line else ""
    return f"{ref.web_url}/blob/{sha}/{path}{anchor}"
