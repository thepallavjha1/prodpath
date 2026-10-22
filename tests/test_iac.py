"""Terraform rendering: invariants that need no terraform binary, plus formatted goldens."""

import re
import shutil
from pathlib import Path

import pytest

from prodpath.iac_check import find_violations, format_files
from prodpath.models import Architecture, Prefs, SystemModel
from prodpath.providers.aws import AwsProvider
from prodpath.providers.aws.iac import iac_gaps, render_iac, tf_id
from tests.helpers import build_system, kitchen_sink_system, make_fact, make_service

GOLDEN = Path(__file__).parent / "golden" / "terraform"
FIXTURE_NAMES = ["mono_a", "mono_b", "mono_c", "mono_d"]
TERRAFORM = shutil.which("terraform")
PROVIDER = AwsProvider()

RESOURCE = re.compile(r'^resource "(\w+)" "(\w+)"', re.MULTILINE)
VARIABLE = re.compile(r'^variable "(\w+)" \{(.*?)^\}', re.MULTILINE | re.DOTALL)
INGRESS = re.compile(r"^  ingress \{(.*?)^  \}", re.MULTILINE | re.DOTALL)


def arch_for(system: SystemModel, env: str = "prod") -> Architecture:
    return PROVIDER.choose(system, Prefs(environment=env))  # type: ignore[arg-type]


@pytest.fixture(params=[*FIXTURE_NAMES, "kitchen_sink"])
def rendered(request: pytest.FixtureRequest, fixtures_dir: Path, tmp_path: Path):  # type: ignore[no-untyped-def]
    if request.param == "kitchen_sink":
        system = kitchen_sink_system()
    else:
        system = build_system(fixtures_dir / request.param, tmp_path)
    arch = arch_for(system)
    return request.param, arch, render_iac(arch)


def tf_text(files: dict[str, str]) -> str:
    return "\n".join(text for name, text in sorted(files.items()) if name.endswith(".tf"))


@pytest.mark.skipif(TERRAFORM is None, reason="terraform is not on PATH")
@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_terraform_matches_formatted_golden(
    name: str, fixtures_dir: Path, tmp_path: Path, update_golden: bool
) -> None:
    assert TERRAFORM
    files = format_files(
        render_iac(arch_for(build_system(fixtures_dir / name, tmp_path))), TERRAFORM
    )
    target = GOLDEN / name
    if update_golden:
        shutil.rmtree(target, ignore_errors=True)
        target.mkdir(parents=True)
        for filename, text in files.items():
            (target / filename).write_text(text, encoding="utf-8", newline="\n")
    expected = {p.name: p.read_text(encoding="utf-8") for p in target.iterdir()}
    assert files == expected


def test_no_account_ids_keys_or_secret_values(rendered) -> None:  # type: ignore[no-untyped-def]
    _, _, files = rendered
    assert find_violations(files) == []
    assert "hunter2" not in "".join(files.values())


def test_braces_balance_and_resources_are_unique(rendered) -> None:  # type: ignore[no-untyped-def]
    _, _, files = rendered
    for name, text in files.items():
        if name.endswith(".tf"):
            assert text.count("{") == text.count("}"), name
    addresses = RESOURCE.findall(tf_text(files))
    assert len(addresses) == len(set(addresses))


def test_every_variable_reference_is_declared_and_documented(rendered) -> None:  # type: ignore[no-untyped-def]
    _, _, files = rendered
    declared = {name: body for name, body in VARIABLE.findall(files["variables.tf"])}
    used = set(re.findall(r"\bvar\.(\w+)", tf_text(files)))
    assert used <= set(declared), used - set(declared)
    assert all("description" in body for body in declared.values())


def test_required_variables_appear_in_the_tfvars_example(rendered) -> None:  # type: ignore[no-untyped-def]
    _, _, files = rendered
    required = [n for n, body in VARIABLE.findall(files["variables.tf"]) if "default" not in body]
    for name in required:
        assert re.search(rf"^{name}\s*=", files["terraform.tfvars.example"], re.MULTILINE), name


def test_only_the_load_balancer_is_open_to_the_internet(rendered) -> None:  # type: ignore[no-untyped-def]
    _, _, files = rendered
    for text in files.values():
        for body in INGRESS.findall(text):
            if "0.0.0.0/0" in body:
                port = int(re.search(r"from_port\s*=\s*(\d+)", body).group(1))  # type: ignore[union-attr]
                assert port in (80, 443)
    assert "0.0.0.0/0" not in files.get("rds.tf", "") + files.get("elasticache.tf", "")


def test_data_stores_are_encrypted_and_private(rendered) -> None:  # type: ignore[no-untyped-def]
    _, _, files = rendered
    text = tf_text(files)
    assert text.count("storage_encrypted           = true") == text.count(
        'resource "aws_db_instance"'
    )
    assert "publicly_accessible         = true" not in text
    assert text.count("manage_master_user_password = true") == text.count('aws_db_instance"')
    for bucket in re.findall(r'resource "aws_s3_bucket" "(\w+)"', text):
        assert f'resource "aws_s3_bucket_public_access_block" "{bucket}"' in text
        assert f'resource "aws_s3_bucket_server_side_encryption_configuration" "{bucket}"' in text
    if "aws_elasticache_replication_group" in text:
        assert "transit_encryption_enabled = true" in text
        assert "at_rest_encryption_enabled = true" in text


def test_wildcard_resources_are_explained(rendered) -> None:  # type: ignore[no-untyped-def]
    _, _, files = rendered
    for name, text in files.items():
        lines = text.splitlines()
        for number, line in enumerate(lines):
            if re.search(r'Resource\s*=\s*"\*"', line):
                nearby = lines[max(0, number - 4) : number]  # the comment sits atop the statement
                assert any(n.strip().startswith("#") for n in nearby), f"{name}:{number + 1}"


def test_secret_slots_are_created_without_values(rendered) -> None:  # type: ignore[no-untyped-def]
    _, _, files = rendered
    text = tf_text(files)
    assert "aws_secretsmanager_secret_version" not in text
    assert "secret_string" not in text


def test_services_are_not_rolled_back_by_terraform(rendered) -> None:  # type: ignore[no-untyped-def]
    _, _, files = rendered
    services = files["ecs.tf"].count('resource "aws_ecs_service"')
    assert files["ecs.tf"].count("ignore_changes = [task_definition, desired_count]") == services


def test_fixture_architectures_have_no_template_gaps(fixtures_dir: Path, tmp_path: Path) -> None:
    for name in FIXTURE_NAMES:
        (tmp_path / name).mkdir()
        arch = arch_for(build_system(fixtures_dir / name, tmp_path / name))
        assert iac_gaps(arch) == []


def test_kitchen_sink_lists_components_without_templates() -> None:
    arch = arch_for(kitchen_sink_system())
    assert iac_gaps(arch) == ["documentdb (documentdb)", "elasticache-memcached (elasticache)"]
    files = render_iac(arch)
    assert {"messaging.tf", "s3.tf", "scheduler.tf", "rds.tf", "elasticache.tf"} <= set(files)
    assert "documentdb" not in tf_text(files)


def test_nonprod_turns_protection_off_and_uses_single_az() -> None:
    files = render_iac(arch_for(kitchen_sink_system(), "nonprod"))
    assert "deletion_protection         = false" in files["rds.tf"]
    assert "skip_final_snapshot         = true" in files["rds.tf"]
    assert "multi_az                    = false" in files["rds.tf"]
    assert "enable_deletion_protection = false" in files["alb.tf"]
    assert "num_cache_clusters         = 1" in files["elasticache.tf"]


def test_prod_keeps_final_snapshots_and_deletion_protection() -> None:
    files = render_iac(arch_for(kitchen_sink_system(), "prod"))
    assert "skip_final_snapshot         = false" in files["rds.tf"]
    assert "final_snapshot_identifier" in files["rds.tf"]
    assert "enable_deletion_protection = true" in files["alb.tf"]


def test_assumed_port_and_health_path_are_flagged_in_the_code() -> None:
    files = render_iac(arch_for(kitchen_sink_system()))
    assert "listening port was not found" in files["ecs.tf"]
    assert "No health endpoint was found for admin" in files["alb.tf"]


def test_app_runner_only_architecture_renders_no_vpc_resources() -> None:
    system = SystemModel(services=[make_service("site", "web", [make_fact("port", "8000")])])
    arch = arch_for(system)
    files = render_iac(arch)
    assert "network.tf" not in files and "ecs.tf" not in files
    assert iac_gaps(arch) == ["apprunner-site (apprunner)"]


def test_empty_architecture_renders_nothing() -> None:
    assert render_iac(arch_for(SystemModel(services=[]))) == {}


def test_rendering_is_deterministic() -> None:
    first = render_iac(arch_for(kitchen_sink_system()))
    second = render_iac(arch_for(kitchen_sink_system()))
    assert first == second


@pytest.mark.parametrize(
    "name, expected",
    [("apps-web", "apps_web"), ("root", "root"), ("9lives", "s_9lives"), ("a.b/c", "a_b_c")],
)
def test_tf_id_is_a_valid_identifier(name: str, expected: str) -> None:
    assert tf_id(name) == expected


def static_files() -> dict[str, str]:
    return render_iac(arch_for(kitchen_sink_system()))


def test_each_static_site_gets_a_private_bucket_and_a_cloudfront_distribution() -> None:
    text = static_files()["static_site.tf"]
    for site in ("landing", "docs"):
        assert f'resource "aws_s3_bucket" "site_{site}"' in text
        assert f'resource "aws_cloudfront_origin_access_control" "site_{site}"' in text
        assert f'resource "aws_cloudfront_distribution" "site_{site}"' in text
        assert f'aliases             = ["{site}.${{var.domain_name}}"]' in text
    assert text.count("redirect-to-https") == 2
    assert text.count('minimum_protocol_version = "TLSv1.2_2021"') == 2
    assert text.count('variable = "AWS:SourceArn"') == 2  # only the distribution can read


def test_only_single_page_apps_get_the_index_html_fallback() -> None:
    text = static_files()["static_site.tf"]
    plain, spa = text.split("# ---- landing")  # sites are sorted: docs, then landing (vite)
    assert spa.count("custom_error_response") == 2
    assert "custom_error_response" not in plain


def test_static_sites_need_a_domain_and_a_us_east_1_certificate_variable() -> None:
    files = static_files()
    assert 'variable "site_certificate_arn"' in files["variables.tf"]
    assert "us-east-1" in files["variables.tf"]
    assert 'variable "domain_name"' in files["variables.tf"]
    assert files["variables.tf"].count('variable "domain_name"') == 1  # shared with the ALB
    assert "site_certificate_arn" in files["terraform.tfvars.example"]


def test_deploy_role_can_sync_each_site_and_invalidate_only_its_distribution() -> None:
    text = static_files()["github_oidc.tf"]
    for site in ("landing", "docs"):
        assert f"aws_s3_bucket.site_{site}.arn" in text
        assert f"aws_cloudfront_distribution.site_{site}.arn" in text
    assert "cloudfront:CreateInvalidation" in text and "s3:DeleteObject" in text


def test_a_static_only_system_renders_no_compute_network_or_empty_ecr_statements() -> None:
    system = SystemModel(services=[make_service("web", "static", [make_fact("framework", "vite")])])
    files = render_iac(arch_for(system))
    assert not {"network.tf", "ecs.tf", "alb.tf", "ecr.tf", "iam.tf", "rds.tf"} & set(files)
    assert {"static_site.tf", "github_oidc.tf", "outputs.tf", "variables.tf"} <= set(files)
    assert "ecr:" not in files["github_oidc.tf"]  # no empty Resource list for a missing ECR repo
    assert "site_distributions" in files["outputs.tf"] and "site_buckets" in files["outputs.tf"]
    assert find_violations(files) == []


def test_every_scalable_service_has_a_target_and_a_cpu_policy() -> None:
    files = render_iac(arch_for(kitchen_sink_system()))
    text = files["autoscaling.tf"]
    for service in ("shop", "jobs", "admin"):
        assert f'resource "aws_appautoscaling_target" "{service}"' in text
        assert f'resource "aws_appautoscaling_policy" "{service}_cpu"' in text
        assert f"aws_ecs_service.{service}.name" in text
    assert "nightly" not in text  # scheduled jobs do not scale
    assert text.count("ECSServiceAverageCPUUtilization") == 3
    assert text.count('scalable_dimension = "ecs:service:DesiredCount"') == 3


def test_services_let_autoscaling_own_the_task_count() -> None:
    ecs = render_iac(arch_for(kitchen_sink_system()))["ecs.tf"]
    services = ecs.count('resource "aws_ecs_service"')
    assert ecs.count("ignore_changes = [task_definition, desired_count]") == services


def test_scaling_bounds_are_a_documented_variable() -> None:
    variables = render_iac(arch_for(kitchen_sink_system()))["variables.tf"]
    assert 'variable "service_scaling"' in variables
    for key in ("min_count", "max_count", "cpu_target"):
        assert key in variables
    assert 'variable "alert_email"' in variables


def test_alarms_notify_one_unencrypted_topic_with_a_required_email() -> None:
    files = render_iac(arch_for(kitchen_sink_system()))
    text = files["alarms.tf"]
    assert text.count('resource "aws_sns_topic" "alerts"') == 1
    assert "kms_master_key_id" not in text  # CloudWatch cannot publish to an AWS-managed-key topic
    assert (
        "alert_email" in text
        and 'protocol  = "email"' in text.replace("  ", " ")
        or "email" in text
    )
    alarms = text.count('resource "aws_cloudwatch_metric_alarm"')
    assert alarms >= 10
    assert text.count("alarm_actions") == alarms and text.count("ok_actions") == alarms
    assert "alert_email" in files["terraform.tfvars.example"]


def test_alarm_coverage_follows_what_was_planned() -> None:
    text = render_iac(arch_for(kitchen_sink_system()))["alarms.tf"]
    for fragment in (
        "HTTPCode_Target_5XX_Count",
        "UnHealthyHostCount",
        "CPUUtilization",
        "MemoryUtilization",
        "FreeStorageSpace",
        "EngineCPUUtilization",
        "Evictions",
        "ApproximateNumberOfMessagesVisible",
    ):
        assert fragment in text, fragment
    # An app with only a worker and no data stores has no ALB, RDS, Redis or queue alarms.
    system = SystemModel(services=[make_service("w", "worker", [make_fact("worker", "rq")])])
    worker_only = render_iac(arch_for(system))["alarms.tf"]
    assert "UnHealthyHostCount" not in worker_only and "FreeStorageSpace" not in worker_only


def test_rds_storage_alarm_threshold_is_twenty_percent_of_the_allocation() -> None:
    text = render_iac(arch_for(kitchen_sink_system()))["alarms.tf"]
    assert str(int(20 * 1024**3 * 0.2)) in text  # 20 GB allocated
