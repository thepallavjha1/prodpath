import shutil
from pathlib import Path

import pytest

from prodpath import cli
from prodpath.cli import main
from prodpath.forecast import UsageBook
from prodpath.models import Architecture, Forecast, Prefs, Trap
from prodpath.providers.aws import AwsProvider
from prodpath.providers.aws.pricing import PriceBook, PriceError
from prodpath.render import render_forecast
from tests.helpers import build_system

PRICES = Path(__file__).parent / "fixtures" / "prices"
GOLDEN = Path(__file__).parent / "golden"
FIXTURE_NAMES = ["mono_a", "mono_b", "mono_c", "mono_d"]
STAMP = "2000-01-01T00:00:00Z"


def build(repo: Path, tmp: Path) -> tuple[Architecture, Forecast, list[Trap], str]:
    system = build_system(repo, tmp)
    provider = AwsProvider(PRICES)
    arch = provider.choose(system, Prefs())
    forecast = provider.forecast(arch, system, UsageBook())
    traps = provider.traps(arch, system, forecast)
    return arch, forecast, traps, render_forecast(arch, forecast, traps, STAMP)


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_forecast_markdown_matches_golden(
    name: str, fixtures_dir: Path, tmp_path: Path, update_golden: bool
) -> None:
    *_, document = build(fixtures_dir / name, tmp_path)
    golden_file = GOLDEN / f"FORECAST_{name}.md"
    if update_golden:
        golden_file.write_text(document, encoding="utf-8", newline="\n")
    assert document == golden_file.read_text(encoding="utf-8")


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_document_shows_every_assumption_with_its_source_and_every_price_ref(
    name: str, fixtures_dir: Path, tmp_path: Path
) -> None:
    arch, forecast, traps, document = build(fixtures_dir / name, tmp_path)
    for a in forecast.assumptions:
        row = next(line for line in document.splitlines() if line.startswith(f"| `{a.name}` |"))
        assert f"**{a.source}**" in row
    for ln in forecast.lines:
        assert f"`{ln.price_ref}`" in document
    for trap in traps:
        assert trap.id in document and trap.fix in document
    headings = [
        "## Assumptions",
        "## Cost breakdown",
        "## What can bite me",
        "## Not priced",
        "## Not included in any figure",
        "## What this forecast is based on",
    ]
    for heading in headings:
        assert heading in document
    assert document.startswith("<!-- prodpath ")
    assert "free" in document.lower() and "NAT gateway" in document


def test_forecast_is_deterministic(fixtures_dir: Path, tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    first = build(fixtures_dir / "mono_c", tmp_path / "a")[3]
    second = build(fixtures_dir / "mono_c", tmp_path / "b")[3]
    assert first == second


def test_cli_forecast_writes_only_under_prodpath(
    fixtures_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = tmp_path / "mono_b"
    shutil.copytree(fixtures_dir / "mono_b", repo)
    before = {p.relative_to(repo).as_posix() for p in repo.rglob("*") if p.is_file()}
    assert main(["forecast", "--path", str(repo), "--prices-dir", str(PRICES)]) == 0
    after = {p.relative_to(repo).as_posix() for p in repo.rglob("*") if p.is_file()}
    assert all(p.startswith(".prodpath/") for p in after - before)
    out = capsys.readouterr().out
    assert "expected $171.95/month (low $167.63, spike $194.98)" in out
    document = (repo / ".prodpath/out/FORECAST.md").read_text(encoding="utf-8")
    assert "**Expected: about $171.95 per month**" in document
    assert Forecast.model_validate_json((repo / ".prodpath/forecast.json").read_text())


def test_cli_forecast_without_a_snapshot_says_how_to_get_one(
    fixtures_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = tmp_path / "mono_a"
    shutil.copytree(fixtures_dir / "mono_a", repo)
    code = main(["forecast", "--path", str(repo), "--prices-dir", str(tmp_path / "empty")])
    assert code == 1
    assert "prodpath prices update" in capsys.readouterr().err
    assert not (repo / ".prodpath/out/FORECAST.md").exists()


def test_cli_forecast_uses_a_usage_file(
    fixtures_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = tmp_path / "mono_a"
    shutil.copytree(fixtures_dir / "mono_a", repo)
    usage = tmp_path / "usage.toml"
    usage.write_text("avg_requests_per_second = 4\nresponse_kb = 20\n", encoding="utf-8")
    args = ["forecast", "--path", str(repo), "--prices-dir", str(PRICES), "--usage", str(usage)]
    assert main(args) == 0
    document = (repo / ".prodpath/out/FORECAST.md").read_text(encoding="utf-8")
    assert "| `avg_requests_per_second` | 4 | req/s | **user** |" in document
    assert "| `response_kb` | 20 | KB | **user** |" in document


def test_cli_forecast_rejects_a_bad_usage_file(
    fixtures_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = tmp_path / "mono_a"
    shutil.copytree(fixtures_dir / "mono_a", repo)
    usage = tmp_path / "usage.toml"
    usage.write_text("rps = 3\n", encoding="utf-8")
    args = ["forecast", "--path", str(repo), "--prices-dir", str(PRICES), "--usage", str(usage)]
    assert main(args) == 1
    assert "unknown key 'rps'" in capsys.readouterr().err


def test_cli_prices_update_reports_counts_and_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    snapshot = PRICES / "ap-south-1.json"
    seen: list[tuple[str, Path]] = []

    def fake_update(region: str, directory: Path) -> Path:
        seen.append((region, directory))
        return snapshot

    monkeypatch.setattr(cli, "update_prices", fake_update)
    assert main(["prices", "update", "--region", "ap-south-1", "--dest", str(tmp_path)]) == 0
    assert seen == [("ap-south-1", tmp_path)]
    out = capsys.readouterr().out
    assert f"{PriceBook.load(snapshot).count} prices extracted" in out

    def failing_update(region: str, directory: Path) -> Path:
        raise PriceError("could not download AmazonECS for ap-south-1: boom")

    monkeypatch.setattr(cli, "update_prices", failing_update)
    assert main(["prices", "update", "--dest", str(tmp_path)]) == 1
    assert "could not download AmazonECS" in capsys.readouterr().err
