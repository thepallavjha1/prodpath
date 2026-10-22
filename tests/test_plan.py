import re
import shutil
from pathlib import Path

import pytest

from prodpath.cache import HashCache
from prodpath.cli import main
from prodpath.detect import detect_services
from prodpath.extract import extract_system
from prodpath.iac_check import TerraformReport, run_checks
from prodpath.models import Architecture, Prefs, Summaries
from prodpath.providers import get_provider
from prodpath.render import NOT_VERIFIED, render_plan
from prodpath.scan import scan_repo

GOLDEN = Path(__file__).parent / "golden"
FIXTURE_NAMES = ["mono_a", "mono_b", "mono_c", "mono_d"]
STAMP = "2000-01-01T00:00:00Z"
FAKE_SECRETS = ["hunter2"]


def build(repo: Path, tmp: Path, summaries: Summaries | None = None) -> tuple[Architecture, str]:
    cache = HashCache(tmp / "c.sqlite")
    inventory, _ = scan_repo(repo, cache)
    system, _ = extract_system(repo, inventory, detect_services(repo, inventory), cache)
    cache.close()
    prefs = Prefs()
    provider = get_provider("aws")
    arch = provider.choose(system, prefs)
    steps = provider.steps(arch)
    # which=None keeps goldens machine-independent: fmt/validate are reported as "not run".
    files, checks = run_checks(provider.render_iac(arch), which=lambda name: None)
    report = TerraformReport(sorted(files), provider.iac_gaps(arch), checks)
    return arch, render_plan(system, arch, steps, prefs, summaries, STAMP, report)


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_architecture_and_plan_match_golden(
    name: str, fixtures_dir: Path, tmp_path: Path, update_golden: bool
) -> None:
    arch, plan = build(fixtures_dir / name, tmp_path)
    pairs = {
        GOLDEN / f"architecture_{name}.json": arch.model_dump_json(indent=2) + "\n",
        GOLDEN / f"PLAN_{name}.md": plan,
    }
    for golden_file, actual in pairs.items():
        if update_golden:
            golden_file.write_text(actual, encoding="utf-8", newline="\n")
        assert actual == golden_file.read_text(encoding="utf-8")


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_plan_is_complete_honest_and_secret_free(
    name: str, fixtures_dir: Path, tmp_path: Path
) -> None:
    arch, plan = build(fixtures_dir / name, tmp_path)
    for heading in (
        "## Services", "## Architecture", "## Steps", "## Risks",
        "## Unknowns and open questions", "## Not analyzed", "## Not verified by this tool",
    ):  # fmt: skip
        assert heading in plan
    assert all(item in plan for item in NOT_VERIFIED)
    assert "Confirm the AWS region" in plan
    assert plan.startswith("<!-- prodpath ") and "input " in plan.splitlines()[0]
    for secret in FAKE_SECRETS:
        assert secret not in plan
    assert not re.search(r"\b\d{12}\b", plan)
    for component in arch.components:
        assert f"`{component.name}`" in plan  # every component is visible with its reason


def test_plan_is_byte_identical_for_the_same_input(fixtures_dir: Path, tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    first = build(fixtures_dir / "mono_c", tmp_path / "a")[1]
    second = build(fixtures_dir / "mono_c", tmp_path / "b")[1]
    assert first == second


def test_model_summaries_appear_and_are_labelled(fixtures_dir: Path, tmp_path: Path) -> None:
    summaries = Summaries.model_validate(
        {
            "model": "fake-model",
            "services": [
                {
                    "service_id": "api",
                    "purpose": "Accepts jobs | queues them",
                    "role": "web",
                    "risks": [{"text": "Depends on redis", "evidence_ids": ["api/main.py:7"]}],
                }
            ],
            "system": {"overview": "x"},
        }
    )
    _, plan = build(fixtures_dir / "mono_b", tmp_path, summaries)
    assert "Accepts jobs \\| queues them" in plan  # table-safe
    assert "model-written; evidence `api/main.py:7`" in plan
    assert "fake-model" in plan


def test_shared_datastore_is_called_out_as_a_risk(fixtures_dir: Path, tmp_path: Path) -> None:
    _, plan = build(fixtures_dir / "mono_b", tmp_path)
    assert "`elasticache-redis` is shared by api, worker" in plan


def test_cli_plan_writes_only_under_prodpath(
    fixtures_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = tmp_path / "mono_b"
    shutil.copytree(fixtures_dir / "mono_b", repo)
    before = {p.relative_to(repo).as_posix() for p in repo.rglob("*") if p.is_file()}
    assert main(["plan", "--path", str(repo), "--region", "eu-west-1", "--env", "nonprod"]) == 0
    after = {p.relative_to(repo).as_posix() for p in repo.rglob("*") if p.is_file()}
    assert all(p.startswith(".prodpath/") for p in after - before)
    plan = (repo / ".prodpath/out/PLAN.md").read_text(encoding="utf-8")
    assert "region `eu-west-1`" in plan and "environment `nonprod`" in plan
    assert (repo / ".prodpath/architecture.json").is_file()
    assert "no summaries.json" in capsys.readouterr().out


def test_unknown_provider_is_rejected_clearly() -> None:
    with pytest.raises(ValueError, match="unknown provider 'gcp'; available: aws"):
        get_provider("gcp")


def test_plan_has_a_terraform_section_with_checks_and_coverage(
    fixtures_dir: Path, tmp_path: Path
) -> None:
    _, plan = build(fixtures_dir / "mono_c", tmp_path)
    section = plan.split("## Terraform")[1].split("## Risks")[0]
    assert "self-scan: passed" in section
    assert "terraform validate: not run" in section  # honest when the check could not run
    assert "Every planned component has a template." in section
    assert "`ecs.tf`" in section


def test_cli_plan_writes_formatted_terraform_only_under_prodpath(
    fixtures_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = tmp_path / "mono_b"
    shutil.copytree(fixtures_dir / "mono_b", repo)
    before = {p.relative_to(repo).as_posix() for p in repo.rglob("*") if p.is_file()}
    code = main(["plan", "--path", str(repo), "--tf-mirror", str(tmp_path / "no-mirror")])
    after = {p.relative_to(repo).as_posix() for p in repo.rglob("*") if p.is_file()}
    assert code == 0
    assert all(p.startswith(".prodpath/") for p in after - before)
    tf_dir = repo / ".prodpath/out/terraform"
    assert {"versions.tf", "ecs.tf", "variables.tf", "terraform.tfvars.example"} <= {
        p.name for p in tf_dir.iterdir()
    }
    assert "self-scan: ok" in capsys.readouterr().out
    plan = (repo / ".prodpath/out/PLAN.md").read_text(encoding="utf-8")
    assert "## Terraform" in plan


def test_rerunning_plan_removes_stale_terraform_files(fixtures_dir: Path, tmp_path: Path) -> None:
    repo = tmp_path / "mono_b"
    shutil.copytree(fixtures_dir / "mono_b", repo)
    stale = repo / ".prodpath/out/terraform/old_leftover.tf"
    stale.parent.mkdir(parents=True)
    stale.write_text("# stale", encoding="utf-8")
    assert main(["plan", "--path", str(repo), "--tf-mirror", str(tmp_path / "no-mirror")]) == 0
    assert not stale.exists()
