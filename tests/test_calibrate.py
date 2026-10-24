"""Calibration on synthetic bills only; no real AWS data exists in this repository."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from prodpath.calibrate import (
    CalibrationError,
    append_dataset,
    compare,
    group_of_line,
    group_of_service,
    parse_cost_csv,
    render_calibration,
)
from prodpath.cli import main as cli_main
from prodpath.models import CostLine, Forecast

BILL = (
    "Service,2026-09-01,2026-10-01,Total costs($)\n"
    '"Amazon Elastic Container Service",40.00,60.00,100.00\n'
    '"Amazon Relational Database Service",20.00,20.00,40.00\n'
    '"Amazon Virtual Private Cloud",5.00,5.00,10.00\n'
    '"Tax",1.00,1.00,2.00\n'
    '"Total costs",66.00,86.00,152.00\n'
)


def line(component: str, dimension: str, low: float, expected: float, spike: float) -> CostLine:
    return CostLine(
        component=component, dimension=dimension, unit="u", qty_low=1, qty_expected=1,
        qty_spike=1, unit_price=1, price_ref="ref", usd_low=low, usd_expected=expected,
        usd_spike=spike,
    )  # fmt: skip


def make_forecast() -> Forecast:
    lines = [
        line("ecs-svc-api", "vCPU-hours", 20, 25, 40),
        line("rds-postgres", "gp3 storage", 8, 10, 12),
        line("alb", "load balancer hours", 15, 16, 17),
    ]
    return Forecast(
        provider="aws", region="ap-south-1", lines=lines, total_low=43, total_expected=51,
        total_spike=69, assumptions=[], not_priced=[], not_included=[], price_snapshot="test",
    )  # fmt: skip


def test_parse_uses_the_total_column_and_skips_tax_and_total_rows() -> None:
    assert parse_cost_csv(BILL) == {
        "Amazon Elastic Container Service": 100.0,
        "Amazon Relational Database Service": 40.0,
        "Amazon Virtual Private Cloud": 10.0,
    }


def test_parse_sums_months_when_there_is_no_total_column() -> None:
    text = "Service,2026-09-01,2026-10-01\nAmazonCloudWatch,1.5,2.5\n"
    assert parse_cost_csv(text) == {"AmazonCloudWatch": 4.0}


@pytest.mark.parametrize(
    "text, fragment",
    [
        ("", "no data rows"),
        ("Name,Cost\nx,1\n", "'Service'"),
        ("Service,Total\nTax,1\n", "no service"),
    ],
)
def test_parse_rejects_unusable_files_with_a_clear_message(text: str, fragment: str) -> None:
    with pytest.raises(CalibrationError, match=fragment):
        parse_cost_csv(text)


def test_services_and_components_land_in_the_same_groups() -> None:
    assert group_of_service("Amazon Elastic Container Service") == "compute"
    assert group_of_service("EC2 - Other") == "network"
    assert group_of_service("Something New") == "other"
    assert group_of_line("ecs-svc-api", "vCPU-hours") == "compute"
    assert group_of_line("logs-api", "log ingestion") == "monitoring"
    assert group_of_line("alb", "data transfer out") == "network"


def test_compare_reports_error_per_group_and_overall() -> None:
    """Months=2: actual compute 50, database 20, network 5 per month = 75.
    Expected 51 -> (51 - 75) / 75 = -32%. Compute 25 vs 50 = -50%."""
    result = compare(make_forecast(), parse_cost_csv(BILL), months=2)
    by_group = {g.group: g for g in result.groups}
    assert by_group["compute"].actual == pytest.approx(50.0)
    assert by_group["compute"].error_pct == pytest.approx(-0.5)
    assert by_group["compute"].within_range is False  # 50 is above the spike of 40
    assert by_group["database"].within_range is False  # 20 is above the spike of 12
    assert by_group["load-balancer"].actual == 0 and by_group["load-balancer"].error_pct is None
    assert result.total.actual == pytest.approx(75.0)
    assert result.total.error_pct == pytest.approx(-24 / 75)


def test_compare_rejects_zero_months() -> None:
    with pytest.raises(CalibrationError):
        compare(make_forecast(), {"x": 1.0}, months=0)


def test_render_names_the_verdict_and_unmapped_services() -> None:
    result = compare(make_forecast(), {"Amazon Mystery": 10.0, **parse_cost_csv(BILL)}, months=2)
    text = render_calibration(result, "STAMP")
    assert "| **total** |" in text and "Outside the 25% accuracy target" in text
    assert "Amazon Mystery" in text and "Not mapped" in text


def test_dataset_appends_one_line_per_run(tmp_path: Path) -> None:
    result = compare(make_forecast(), parse_cost_csv(BILL), months=2)
    target = tmp_path / "deep" / "runs.jsonl"
    append_dataset(target, result, "S1")
    append_dataset(target, result, "S2")
    rows = [json.loads(x) for x in target.read_text(encoding="utf-8").splitlines()]
    assert [r["at"] for r in rows] == ["S1", "S2"] and rows[0]["total"]["group"] == "total"


def test_cli_calibrate_writes_calibration_md(fixtures_dir: Path, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    shutil.copytree(fixtures_dir / "mono_a", repo)
    (repo / ".prodpath").mkdir()
    (repo / ".prodpath" / "forecast.json").write_text(
        make_forecast().model_dump_json(), encoding="utf-8"
    )
    csv_path = tmp_path / "costs.csv"
    csv_path.write_text(BILL, encoding="utf-8")
    code = cli_main(
        ["calibrate", str(csv_path), "--path", str(repo), "--months", "2",
         "--dataset", str(tmp_path / "ds.jsonl")]
    )  # fmt: skip
    assert code == 0
    assert "Forecast versus real bill" in (repo / ".prodpath/out/CALIBRATION.md").read_text(
        encoding="utf-8"
    )
    assert (tmp_path / "ds.jsonl").exists()


def test_cli_calibrate_without_a_forecast_says_what_to_run(
    fixtures_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = tmp_path / "repo"
    shutil.copytree(fixtures_dir / "mono_a", repo)
    csv_path = tmp_path / "costs.csv"
    csv_path.write_text(BILL, encoding="utf-8")
    assert cli_main(["calibrate", str(csv_path), "--path", str(repo)]) == 1
    assert "prodpath forecast" in capsys.readouterr().err
