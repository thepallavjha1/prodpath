"""terraform validate on every fixture's generated code, offline against the local mirror.

Skipped (with a reason) when terraform or the provider mirror is missing. Create the mirror once
with `terraform providers mirror ~/.cache/prodpath/terraform-mirror` (see `prodpath doctor`).
"""

import shutil
from pathlib import Path

import pytest

from prodpath.iac_check import DEFAULT_MIRROR, format_files, validate_files
from prodpath.models import Prefs
from prodpath.providers.aws import AwsProvider
from tests.helpers import build_system, kitchen_sink_system

TERRAFORM = shutil.which("terraform")
pytestmark = [
    pytest.mark.tf,  # slow: opt in with `pytest -m tf`
    pytest.mark.skipif(
        TERRAFORM is None or not DEFAULT_MIRROR.is_dir(),
        reason="needs terraform and the local provider mirror",
    ),
]


@pytest.mark.parametrize("name", ["mono_a", "mono_b", "mono_c", "mono_d"])
def test_fixture_terraform_validates(name: str, fixtures_dir: Path, tmp_path: Path) -> None:
    assert TERRAFORM
    provider = AwsProvider()
    arch = provider.choose(
        build_system(fixtures_dir / name, tmp_path),
        Prefs(),
    )
    files = format_files(provider.render_iac(arch), TERRAFORM)
    result = validate_files(files, TERRAFORM, DEFAULT_MIRROR, tmp_path / "work")
    assert (result.status, result.detail) == ("ok", "configuration is valid")


@pytest.mark.parametrize("env", ["prod", "nonprod"])
def test_kitchen_sink_terraform_validates(env: str, tmp_path: Path) -> None:
    assert TERRAFORM
    provider = AwsProvider()
    arch = provider.choose(kitchen_sink_system(), Prefs(environment=env))  # type: ignore[arg-type]
    files = format_files(provider.render_iac(arch), TERRAFORM)
    result = validate_files(files, TERRAFORM, DEFAULT_MIRROR, tmp_path)
    assert (result.status, result.detail) == ("ok", "configuration is valid")


def test_a_static_only_system_validates(tmp_path: Path) -> None:
    from prodpath.models import SystemModel
    from tests.helpers import make_fact, make_service

    assert TERRAFORM
    provider = AwsProvider()
    system = SystemModel(services=[make_service("web", "static", [make_fact("framework", "vite")])])
    files = format_files(provider.render_iac(provider.choose(system, Prefs())), TERRAFORM)
    result = validate_files(files, TERRAFORM, DEFAULT_MIRROR, tmp_path)
    assert (result.status, result.detail) == ("ok", "configuration is valid")


def test_a_streamlit_service_with_stickiness_validates(tmp_path: Path) -> None:
    from prodpath.models import SystemModel
    from tests.helpers import make_fact, make_service

    assert TERRAFORM
    provider = AwsProvider()
    facts = [
        make_fact("framework", "streamlit"),
        make_fact("dependency", "torch"),
        make_fact("external_call", "http-client"),
    ]
    system = SystemModel(services=[make_service("ui", "web", facts)])
    arch = provider.choose(system, Prefs())
    files = format_files(provider.render_iac(arch), TERRAFORM)
    assert "stickiness" in files["alb.tf"]
    result = validate_files(files, TERRAFORM, DEFAULT_MIRROR, tmp_path)
    assert (result.status, result.detail) == ("ok", "configuration is valid")
