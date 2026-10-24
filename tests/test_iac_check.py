"""iac_check: the self-scan and the validate path, including proof that validate is real."""

import shutil
from pathlib import Path

import pytest

from prodpath.iac_check import (
    DEFAULT_MIRROR,
    find_violations,
    format_files,
    run_checks,
    validate_files,
)
from prodpath.models import Prefs
from prodpath.providers.aws import AwsProvider
from tests.helpers import kitchen_sink_system

TERRAFORM = shutil.which("terraform")
HAVE_MIRROR = DEFAULT_MIRROR.is_dir()
# Built at runtime so no key-shaped literal sits in the repo (GitHub secret scanning).
FAKE_KEY = "AKIA" + "IOSFODNN7" + "EXAMPLE"
needs_validate = pytest.mark.skipif(
    TERRAFORM is None or not HAVE_MIRROR, reason="needs terraform and the local provider mirror"
)
slow_tf = pytest.mark.tf  # real terraform runs; opt in with `pytest -m tf`


def generated() -> dict[str, str]:
    provider = AwsProvider()
    return provider.render_iac(provider.choose(kitchen_sink_system(), Prefs()))


@pytest.mark.parametrize(
    "text, label",
    [
        (
            'resource "x" "y" {\n  arn = "arn:aws:iam::123456789012:role/r"\n}\n',
            "12-digit account id",
        ),
        (f'key = "{FAKE_KEY}"\n', "AWS access key"),
        ("-----BEGIN RSA PRIVATE KEY-----\n", "private key"),
        ('  password = "not-a-reference"\n', "literal password"),
        ('  master_password = "x1"\n', "literal password"),
        ('  secret_string = "abc"\n', "literal secret"),
    ],
)
def test_self_scan_catches_secrets_and_account_ids(text: str, label: str) -> None:
    assert find_violations({"main.tf": text}) == [f"main.tf: contains a {label}"]


def test_self_scan_allows_references_and_ordinary_numbers() -> None:
    text = "password = var.db_password\nmessage_retention_seconds = 1209600\nport = 5432\n"
    assert find_violations({"main.tf": text}) == []
    assert find_violations(generated()) == []


def test_run_checks_without_terraform_reports_skipped_not_ok() -> None:
    files, results = run_checks(generated(), which=lambda name: None)
    assert files == generated()
    assert [(r.name, r.status) for r in results] == [
        ("self-scan", "ok"),
        ("terraform fmt", "skipped"),
        ("terraform validate", "skipped"),
    ]


def test_a_failed_self_scan_stops_everything_else() -> None:
    files = {"main.tf": f'key = "{FAKE_KEY}"\n'}
    out, results = run_checks(files, which=lambda name: "/bin/terraform")
    assert out == files
    assert [(r.name, r.status) for r in results] == [("self-scan", "fail")]


def test_validate_without_a_mirror_says_how_to_create_one(tmp_path: Path) -> None:
    result = validate_files({"main.tf": ""}, "terraform", tmp_path / "missing", tmp_path)
    assert result.status == "skipped"
    assert "terraform providers mirror" in result.detail


@pytest.mark.skipif(TERRAFORM is None, reason="terraform is not on PATH")
def test_fmt_is_idempotent() -> None:
    assert TERRAFORM
    once = format_files(generated(), TERRAFORM)
    assert format_files(once, TERRAFORM) == once


@slow_tf
@needs_validate
def test_validate_really_fails_on_a_broken_configuration(tmp_path: Path) -> None:
    """Guards against a vacuous check: an undefined reference must be reported as a failure."""
    assert TERRAFORM
    files = format_files(generated(), TERRAFORM)
    files["ecs.tf"] += '\noutput "broken" {\n  value = aws_ecs_cluster.does_not_exist.arn\n}\n'
    result = validate_files(files, TERRAFORM, DEFAULT_MIRROR, tmp_path)
    assert result.status == "fail"
    assert "does_not_exist" in result.detail


@slow_tf
@needs_validate
def test_run_checks_end_to_end_on_real_terraform(tmp_path: Path) -> None:
    formatted, results = run_checks(generated(), DEFAULT_MIRROR, tmp_path)
    assert [(r.name, r.status) for r in results] == [
        ("self-scan", "ok"),
        ("terraform fmt", "ok"),
        ("terraform validate", "ok"),
    ]
    assert set(formatted) == set(generated())


@slow_tf
@needs_validate
def test_budget_mode_terraform_passes_fmt_and_validate(tmp_path: Path) -> None:
    provider = AwsProvider()
    files = provider.render_iac(provider.choose(kitchen_sink_system(), Prefs(budget=True)))
    _, results = run_checks(files, DEFAULT_MIRROR, tmp_path)
    assert [(r.name, r.status) for r in results] == [
        ("self-scan", "ok"),
        ("terraform fmt", "ok"),
        ("terraform validate", "ok"),
    ]
