"""Web mode: GitHub intake, job queue, bundle and the real HTTP server (ADR-019)."""

from __future__ import annotations

import io
import json
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from prodpath.web import github
from prodpath.web.github import RepoError, RepoRef, clone, evidence_url, parse_github_url
from prodpath.web.jobs import JobError, JobManager
from prodpath.web.server import SAMPLE_DIR, STATIC_DIR, make_server

PRICES = Path(__file__).parent / "fixtures" / "prices"
SHA = "0123456789abcdef0123456789abcdef01234567"


# -- URL intake -----------------------------------------------------------------------------
@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://github.com/octo/hello", RepoRef("octo", "hello")),
        ("  https://github.com/octo/hello/  ", RepoRef("octo", "hello")),
        ("https://github.com/octo/hello.git", RepoRef("octo", "hello")),
        ("https://github.com/octo/my.repo-x_1", RepoRef("octo", "my.repo-x_1")),
        ("https://github.com/octo/hello/tree/dev", RepoRef("octo", "hello", "dev")),
        ("https://github.com/octo/hello/tree/feature/x-1", RepoRef("octo", "hello", "feature/x-1")),
    ],
)
def test_accepts_only_plain_public_github_links(url: str, expected: RepoRef) -> None:
    assert parse_github_url(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "",
        "octo/hello",
        "http://github.com/octo/hello",
        "https://gitlab.com/octo/hello",
        "https://github.com.evil.example/octo/hello",
        "https://evil.example/https://github.com/octo/hello",
        "https://user@github.com/octo/hello",
        "https://github.com:8443/octo/hello",
        "file:///etc/passwd",
        "git@github.com:octo/hello.git",
        "https://github.com/octo",
        "https://github.com/octo/hello/issues",
        "https://github.com/octo/hello?x=1",
        "https://github.com/octo/..",
        "https://github.com/-octo/hello",
        "https://github.com/octo/hello/tree/../../x",
        "https://github.com/octo/hello/tree/-evil",
        "https://github.com/octo/hello " + "a" * 400,
        "--upload-pack=touch /tmp/x",
    ],
)
def test_rejects_everything_else(url: str) -> None:
    with pytest.raises(RepoError):
        parse_github_url(url)


def test_evidence_links_point_at_the_pinned_commit_and_line() -> None:
    ref = RepoRef("octo", "hello")
    assert evidence_url(ref, SHA, "src/app.py", 12) == (
        f"https://github.com/octo/hello/blob/{SHA}/src/app.py#L12"
    )
    assert evidence_url(ref, SHA, "Dockerfile", None).endswith("/Dockerfile")


# -- clone hardening ------------------------------------------------------------------------
class FakeGit:
    def __init__(self, fail: bool = False, timeout: bool = False) -> None:
        self.calls: list[tuple[list[str], dict[str, Any]]] = []
        self.fail, self.timeout = fail, timeout

    def __call__(self, cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append((cmd, kwargs))
        if self.timeout:
            raise subprocess.TimeoutExpired(cmd, 1)
        if "clone" in cmd:
            if self.fail:
                return subprocess.CompletedProcess(cmd, 128, "", "fatal: could not read Username")
            dest = Path(cmd[-1])
            (dest / ".git").mkdir(parents=True)
            (dest / "app.py").write_text("x = 1\n", encoding="utf-8")
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return subprocess.CompletedProcess(cmd, 0, SHA + "\n", "")


def test_clone_is_shallow_hook_free_symlink_free_and_never_prompts(tmp_path: Path) -> None:
    git = FakeGit()
    sha = clone(RepoRef("octo", "hello", "dev"), tmp_path / "repo", run=git)
    cmd, kwargs = git.calls[0]
    joined = " ".join(cmd)
    for flag in ("--depth 1", "--single-branch", "--no-tags", "--no-recurse-submodules"):
        assert flag in joined
    assert "core.symlinks=false" in joined and "core.hooksPath=" in joined
    assert "protocol.allow=never" in joined and "--branch dev" in joined
    assert cmd[-3:-1] == ["--", "https://github.com/octo/hello.git"]  # url cannot be a flag
    assert kwargs["env"]["GIT_TERMINAL_PROMPT"] == "0" and kwargs["timeout"] == 120
    assert sha == SHA
    assert not (tmp_path / "repo" / ".git").exists()  # history is never needed or kept
    assert (tmp_path / "repo" / "app.py").exists()


def test_clone_failures_become_friendly_errors(tmp_path: Path) -> None:
    with pytest.raises(RepoError, match="public"):
        clone(RepoRef("octo", "private"), tmp_path / "a", run=FakeGit(fail=True))
    with pytest.raises(RepoError, match="longer than"):
        clone(RepoRef("octo", "huge"), tmp_path / "b", run=FakeGit(timeout=True))


def test_size_and_file_count_limits(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
    (tmp_path / "b.txt").write_text("hello", encoding="utf-8")
    github.check_limits(tmp_path)
    monkeypatch.setattr(github, "MAX_REPO_FILES", 1)
    with pytest.raises(RepoError, match="files"):
        github.check_limits(tmp_path)
    monkeypatch.setattr(github, "MAX_REPO_FILES", 10)
    monkeypatch.setattr(github, "MAX_REPO_BYTES", 6)
    with pytest.raises(RepoError, match="larger"):
        github.check_limits(tmp_path)


# -- job manager ----------------------------------------------------------------------------
def copy_fixture(name: str, fixtures_dir: Path, seen: list[Path] | None = None):  # type: ignore[no-untyped-def]
    def fake_clone(ref: RepoRef, dest: Path) -> str:
        if seen is not None:
            seen.append(dest)
        shutil.copytree(fixtures_dir / name, dest)
        return SHA

    return fake_clone


def wait_done(manager: JobManager, job_id: str, timeout: float = 120.0) -> Any:
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = manager.job(job_id)
        assert job is not None
        if job.status in ("done", "error"):
            return job
        time.sleep(0.05)
    raise AssertionError("job did not finish")


@pytest.fixture
def manager(fixtures_dir: Path) -> Iterator[JobManager]:
    manager = JobManager(
        PRICES, Path("unused"), sample_dir=SAMPLE_DIR, clone_fn=copy_fixture("mono_a", fixtures_dir)
    )
    yield manager
    manager.shutdown()


def test_a_github_link_becomes_a_result_with_evidence_links(manager: JobManager) -> None:
    job = manager.submit("1.2.3.4", "https://github.com/octo/hello", {})
    assert wait_done(manager, job.id).status == "done"
    assert [m.split("]")[0] for m in manager.job(job.id).log][:1] == ["[clone"]  # type: ignore[union-attr]
    run = manager.run(job.id)
    assert run is not None and run.source["sha"] == SHA and run.source["owner"] == "octo"
    from prodpath.web.bundle import build_bundle

    bundle = build_bundle(run, job.id)
    assert bundle["summary"]["services"] == len(run.system.services) > 0
    first = bundle["services"][0]["facts"][0]["evidence"][0]
    assert first["url"].startswith(f"https://github.com/octo/hello/blob/{SHA}/")
    assert bundle["forecast"]["groups"] and bundle["terraform"]["files"]


def test_the_clone_workspace_is_deleted_after_the_analysis(
    fixtures_dir: Path,
) -> None:
    seen: list[Path] = []
    manager = JobManager(
        PRICES, Path("unused"), clone_fn=copy_fixture("mono_a", fixtures_dir, seen)
    )
    try:
        job = manager.submit("c", "https://github.com/octo/hello", {})
        assert wait_done(manager, job.id).status == "done"
        assert seen and not seen[0].exists() and not seen[0].parent.exists()
    finally:
        manager.shutdown()


def test_clone_errors_reach_the_visitor_without_internals(fixtures_dir: Path) -> None:
    def failing(ref: RepoRef, dest: Path) -> str:
        raise RepoError("Could not clone that repository. It must be public.")

    manager = JobManager(PRICES, Path("unused"), clone_fn=failing)
    try:
        job = manager.submit("c", "https://github.com/octo/private", {})
        done = wait_done(manager, job.id)
        assert done.status == "error" and "public" in done.error
    finally:
        manager.shutdown()


def test_unexpected_bugs_are_reported_generically(fixtures_dir: Path) -> None:
    def broken(ref: RepoRef, dest: Path) -> str:
        raise RuntimeError("/home/secret/path exploded")

    manager = JobManager(PRICES, Path("unused"), clone_fn=broken)
    try:
        job = manager.submit("c", "https://github.com/octo/x", {})
        done = wait_done(manager, job.id)
        assert done.status == "error" and "/home" not in done.error
    finally:
        manager.shutdown()


def test_bad_links_and_options_are_refused_before_any_work(manager: JobManager) -> None:
    with pytest.raises(RepoError):
        manager.submit("c", "https://evil.example/x/y", {})
    with pytest.raises(JobError, match="environment"):
        manager.submit("c", "https://github.com/octo/hello", {"environment": "staging"})
    with pytest.raises(JobError, match="region"):
        manager.submit("c", "https://github.com/octo/hello", {"region": "mars-north-1"})
    with pytest.raises(JobError, match="unknown usage"):
        manager.submit("c", "https://github.com/octo/hello", {"usage": {"nope": 1}})
    with pytest.raises(JobError, match="at least 1"):
        manager.submit(
            "c", "https://github.com/octo/hello", {"usage": {"peak_to_average_ratio": 0.5}}
        )


def test_rate_limit_is_per_client_and_expires(fixtures_dir: Path) -> None:
    now = [1000.0]
    manager = JobManager(
        PRICES, Path("unused"), clone_fn=copy_fixture("mono_a", fixtures_dir),
        rate_limit=2, rate_window=60, clock=lambda: now[0],
    )  # fmt: skip
    try:
        manager.submit("a", "https://github.com/o/r", {})
        manager.submit("a", "https://github.com/o/r", {})
        with pytest.raises(JobError, match="Too many"):
            manager.submit("a", "https://github.com/o/r", {})
        manager.submit("b", "https://github.com/o/r", {})  # another visitor is unaffected
        now[0] += 61
        manager.submit("a", "https://github.com/o/r", {})  # the window passed
    finally:
        manager.shutdown()


def test_results_expire_after_the_retention_window(fixtures_dir: Path) -> None:
    now = [0.0]
    manager = JobManager(
        PRICES, Path("unused"), clone_fn=copy_fixture("mono_a", fixtures_dir),
        retention=100, clock=lambda: now[0],
    )  # fmt: skip
    try:
        job = manager.submit("a", "https://github.com/o/r", {})
        wait_done(manager, job.id)
        assert manager.run(job.id) is not None
        now[0] = 101
        assert manager.run(job.id) is None and manager.job(job.id) is None
    finally:
        manager.shutdown()


def test_whatif_changes_traffic_and_network_without_cloning(manager: JobManager) -> None:
    job = manager.submit("a", "https://github.com/o/r", {"usage": {"peak_requests_per_second": 1}})
    wait_done(manager, job.id)
    quiet = manager.run(job.id)
    assert quiet is not None
    busy = manager.whatif(job.id, {"usage": {"peak_requests_per_second": 200}})
    assert busy.forecast.total_spike > quiet.forecast.total_spike
    budget = manager.whatif(job.id, {"budget": True, "usage": {"peak_requests_per_second": 1}})
    assert budget.prefs.budget and "vpc-endpoints" not in {
        ln.component for ln in budget.forecast.lines
    }
    assert budget.forecast.total_expected < quiet.forecast.total_expected
    with pytest.raises(JobError, match="expired"):
        manager.whatif("missing", {})


def test_the_built_in_sample_needs_no_clone(fixtures_dir: Path) -> None:
    def forbidden(ref: RepoRef, dest: Path) -> str:
        raise AssertionError("the sample must not clone")

    manager = JobManager(PRICES, Path("unused"), sample_dir=SAMPLE_DIR, clone_fn=forbidden)
    try:
        job = manager.submit("a", "sample", {})
        assert wait_done(manager, job.id).status == "done"
        run = manager.run(job.id)
        assert run is not None and run.source["sample"] is True and len(run.system.services) >= 4
    finally:
        manager.shutdown()


# -- HTTP server ----------------------------------------------------------------------------
@pytest.fixture
def base_url(manager: JobManager) -> Iterator[str]:
    server = make_server(manager, "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def call(
    url: str, body: Any = None, headers: dict[str, str] | None = None, raw: bytes | None = None
) -> tuple[int, dict[str, str], bytes]:
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    request = urllib.request.Request(url, data=data, headers=headers or {})
    if data is not None and not request.has_header("Content-type"):
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request) as response:  # noqa: S310 - localhost test server
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as error:
        return error.code, dict(error.headers), error.read()


def test_pages_carry_a_strict_content_security_policy(base_url: str) -> None:
    status, headers, body = call(base_url + "/")
    assert status == 200 and b"<html" in body.lower()
    csp = headers["Content-Security-Policy"]
    assert (
        "script-src 'self'" in csp and "'unsafe-inline'" not in csp and "default-src 'none'" in csp
    )
    assert (
        headers["X-Content-Type-Options"] == "nosniff"
        and headers["Referrer-Policy"] == "no-referrer"
    )
    for path in ("/app.js", "/app.css"):
        assert call(base_url + path)[0] == 200


def test_static_files_have_no_inline_script_style_or_event_handlers() -> None:
    import re

    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    assert not re.search(r"<script(?![^>]*\bsrc=)", html)
    assert not re.search(r"\sstyle\s*=", html) and not re.search(r"\son[a-z]+\s*=", html)
    js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert "innerHTML" not in js and "outerHTML" not in js and "insertAdjacentHTML" not in js
    assert "document.write" not in js and "eval(" not in js


def test_a_foreign_host_header_is_refused(base_url: str) -> None:
    status, _, _ = call(base_url + "/", headers={"Host": "evil.example"})
    assert status == 403


def test_analyze_validates_input(base_url: str) -> None:
    status, _, body = call(base_url + "/api/analyze", {"url": "https://evil.example/a/b"})
    assert status == 400 and "github.com" in json.loads(body)["error"]
    assert call(base_url + "/api/analyze", raw=b"not json")[0] == 400
    assert call(base_url + "/api/analyze", raw=b"[1]")[0] == 400
    assert call(base_url + "/api/analyze", raw=b"x" * 70_000)[0] == 400
    assert call(base_url + "/api/analyze", {"url": 5})[0] == 400
    status, _, _ = call(
        base_url + "/api/analyze", raw=b"{}", headers={"Content-Type": "text/plain"}
    )
    assert status == 415
    assert call(base_url + "/api/nothing")[0] == 404
    assert call(base_url + "/api/jobs/doesnotexist")[0] == 404


def test_the_full_flow_over_http(base_url: str) -> None:
    status, _, body = call(base_url + "/api/analyze", {"url": "https://github.com/octo/hello"})
    assert status == 202
    job_id = json.loads(body)["job_id"]
    deadline = time.time() + 120
    while time.time() < deadline:
        state = json.loads(call(f"{base_url}/api/jobs/{job_id}")[2])
        if state["status"] in ("done", "error"):
            break
        time.sleep(0.1)
    assert state["status"] == "done" and state["log"]
    bundle = json.loads(call(f"{base_url}/api/runs/{job_id}")[2])
    assert bundle["summary"]["expected"] > 0 and bundle["plan_md"].startswith("<!--")
    again = json.loads(call(f"{base_url}/api/runs/{job_id}/forecast", {"budget": True})[2])
    assert again["prefs"]["budget"] is True
    status, headers, data = call(f"{base_url}/api/runs/{job_id}/download.zip")
    assert status == 200 and headers["Content-Type"] == "application/zip"
    names = zipfile.ZipFile(io.BytesIO(data)).namelist()
    assert (
        "PLAN.md" in names
        and "FORECAST.md" in names
        and any(n.startswith("terraform/") for n in names)
    )
    status, _, body = call(f"{base_url}/api/runs/{job_id}/forecast", {"usage": {"nope": 1}})
    assert status == 400 and "unknown usage" in json.loads(body)["error"]


def test_a_public_bind_needs_an_explicit_flag(manager: JobManager) -> None:
    with pytest.raises(ValueError, match="allow-public"):
        make_server(manager, "0.0.0.0", 0)
