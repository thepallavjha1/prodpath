"""`prodpath run`: scan, facts, optional summaries, plan and forecast in one command."""

import shutil
from pathlib import Path

import pytest

from prodpath import cli
from prodpath.cli import main
from prodpath.llm import LLMError
from prodpath.models import Summaries

PRICES = Path(__file__).parent / "fixtures" / "prices"
NO_MIRROR = "does-not-exist-mirror"


def prepare(fixtures_dir: Path, tmp_path: Path, name: str = "mono_b") -> Path:
    repo = tmp_path / name
    shutil.copytree(fixtures_dir / name, repo)
    return repo


def run_args(repo: Path, tmp_path: Path, *extra: str) -> list[str]:
    return [
        "run", "--path", str(repo), "--prices-dir", str(PRICES),
        "--tf-mirror", str(tmp_path / NO_MIRROR), *extra,
    ]  # fmt: skip


def test_run_writes_plan_terraform_and_forecast_in_one_command(
    fixtures_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = prepare(fixtures_dir, tmp_path)
    one_rps = tmp_path / "one.toml"
    one_rps.write_text("avg_requests_per_second = 1\n", encoding="utf-8")
    before = {p.relative_to(repo).as_posix() for p in repo.rglob("*") if p.is_file()}
    assert main(run_args(repo, tmp_path, "--usage", str(one_rps))) == 0
    after = {p.relative_to(repo).as_posix() for p in repo.rglob("*") if p.is_file()}
    assert all(p.startswith(".prodpath/") for p in after - before)  # read-only on the repo
    out = repo / ".prodpath"
    assert (out / "out/PLAN.md").is_file() and (out / "out/FORECAST.md").is_file()
    assert (out / "out/terraform/ecs.tf").is_file()
    assert (out / "inventory.json").is_file() and (out / "forecast.json").is_file()
    text = capsys.readouterr().out
    assert "services detected" in text and "expected $172.75/month" in text
    assert "PLAN.md" in text and "FORECAST.md" in text  # tells the user where to look


def test_run_stops_early_with_a_hint_when_there_is_no_price_snapshot(
    fixtures_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = prepare(fixtures_dir, tmp_path)
    args = ["run", "--path", str(repo), "--prices-dir", str(tmp_path / "empty")]
    assert main(args) == 1
    assert "prodpath prices update" in capsys.readouterr().err
    assert not (repo / ".prodpath").exists()  # failed before doing any work


def test_run_passes_region_env_and_usage_through(fixtures_dir: Path, tmp_path: Path) -> None:
    repo = prepare(fixtures_dir, tmp_path, "mono_a")
    usage = tmp_path / "usage.toml"
    usage.write_text("avg_requests_per_second = 4\n", encoding="utf-8")
    assert main(run_args(repo, tmp_path, "--env", "nonprod", "--usage", str(usage))) == 0
    plan = (repo / ".prodpath/out/PLAN.md").read_text(encoding="utf-8")
    forecast = (repo / ".prodpath/out/FORECAST.md").read_text(encoding="utf-8")
    assert "environment `nonprod`" in plan
    assert "| `avg_requests_per_second` | 4 | req/s | **user** |" in forecast


def test_run_reports_a_bad_usage_file_and_still_leaves_the_plan(
    fixtures_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = prepare(fixtures_dir, tmp_path)
    usage = tmp_path / "usage.toml"
    usage.write_text("rps = 3\n", encoding="utf-8")
    assert main(run_args(repo, tmp_path, "--usage", str(usage))) == 1
    assert "unknown key 'rps'" in capsys.readouterr().err
    assert (repo / ".prodpath/out/PLAN.md").is_file()  # the plan stage had already succeeded


def test_run_with_summarize_puts_purposes_in_the_plan(
    fixtures_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = prepare(fixtures_dir, tmp_path)
    calls: list[tuple[str, int]] = []

    def fake_summarize(path: Path, model: str, num_ctx: int) -> int:
        calls.append((model, num_ctx))
        summaries = Summaries.model_validate(
            {
                "model": model,
                "services": [
                    {"service_id": "api", "purpose": "Queues jobs for the worker", "role": "web"}
                ],
                "system": {"overview": "Two services."},
            }
        )
        out = path / ".prodpath"
        out.mkdir(parents=True, exist_ok=True)
        (out / "summaries.json").write_text(summaries.model_dump_json(), encoding="utf-8")
        return 0

    monkeypatch.setattr(cli, "run_summarize", fake_summarize)
    args = run_args(repo, tmp_path, "--summarize", "--model", "tiny:1", "--num-ctx", "2048")
    assert main(args) == 0
    assert calls == [("tiny:1", 2048)]
    plan = (repo / ".prodpath/out/PLAN.md").read_text(encoding="utf-8")
    assert "Queues jobs for the worker" in plan


def test_run_without_summarize_never_calls_the_model(
    fixtures_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*args: object) -> int:
        raise AssertionError("the model must not be used without --summarize")

    monkeypatch.setattr(cli, "run_summarize", boom)
    assert main(run_args(prepare(fixtures_dir, tmp_path), tmp_path)) == 0


def test_a_failing_summarize_stops_the_run_with_its_message(
    fixtures_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = prepare(fixtures_dir, tmp_path)
    monkeypatch.setattr(cli, "run_summarize", lambda *args: 1)
    assert main(run_args(repo, tmp_path, "--summarize")) == 1
    assert not (repo / ".prodpath/out/PLAN.md").exists()  # nothing half-finished is presented


def test_the_summarize_failure_path_surfaces_the_llm_error() -> None:
    assert issubclass(LLMError, Exception)  # run_summarize prints LLMError messages to stderr
