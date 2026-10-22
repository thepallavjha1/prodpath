import re

from prodpath.models import Architecture, Prefs, Service, Step, SystemModel
from prodpath.providers.aws import AwsProvider
from tests.helpers import kitchen_sink_system
from tests.helpers import make_fact as f
from tests.helpers import make_service as svc


def plan_steps(
    services: list[Service], region: str = "ap-south-1"
) -> tuple[Architecture, list[Step]]:
    provider = AwsProvider()
    arch = provider.choose(SystemModel(services=services), Prefs(region=region))
    return arch, provider.steps(arch)


API_FACTS = [
    f("port", "8000"),
    f("health_endpoint", "/health"),
    f("datastore", "postgres"),
    f("env_var", "DATABASE_URL"),
    f("object_store", "s3"),
]
FULL = [svc("api", "web", API_FACTS), svc("job", "cron", [f("runtime", "python")])]
APP_RUNNER = [svc("site", "web", [f("port", "8000")])]


def step(steps: list[Step], step_id: str) -> Step:
    return next(s for s in steps if s.id == step_id)


def test_terraform_flow_is_ordered_and_complete() -> None:
    _, steps = plan_steps(FULL)
    ids = [s.id for s in steps]
    assert ids == [
        "account", "state", "terraform", "secret-values", "images",
        "cicd", "observability", "rollback", "verify",
    ]  # fmt: skip


def test_images_come_after_terraform_and_secrets_are_filled_before_services_run() -> None:
    _, steps = plan_steps(FULL)
    ids = [s.id for s in steps]
    assert ids.index("terraform") < ids.index("secret-values") < ids.index("images")


def test_every_step_explains_and_verifies() -> None:
    _, steps = plan_steps(FULL)
    assert all(s.title and s.why and s.verify for s in steps)


def test_terraform_step_matches_the_generated_backend_and_directory() -> None:
    _, steps = plan_steps(FULL, "ap-south-1")
    commands = "\n".join(step(steps, "terraform").commands)
    assert "cd .prodpath/out/terraform" in commands
    assert 'backend-config="region=ap-south-1"' in commands
    assert "terraform plan -out=tfplan" in commands and "terraform apply tfplan" in commands


def test_state_bucket_location_constraint_rules() -> None:
    _, mumbai = plan_steps(FULL, "ap-south-1")
    _, virginia = plan_steps(FULL, "us-east-1")
    assert "LocationConstraint=ap-south-1" in step(mumbai, "state").commands[0]
    assert "LocationConstraint" not in step(virginia, "state").commands[0]


def test_secret_values_are_read_from_files_never_inline() -> None:
    _, steps = plan_steps(FULL)
    commands = step(steps, "secret-values").commands
    assert any("--secret-id prod/api/DATABASE_URL" in c for c in commands)
    assert all("file://<" in c for c in commands)
    assert not any("--secret-string " in c and "file://" not in c for c in commands)
    assert "data_store_endpoints" in step(steps, "secret-values").why


def test_no_account_ids_or_keys_in_any_command() -> None:
    _, steps = plan_steps(FULL)
    text = "\n".join(c for s in steps for c in s.commands)
    assert not re.search(r"\b\d{12}\b", text) and "AKIA" not in text
    assert "<ACCOUNT_ID>" in text


def test_components_without_templates_get_a_manual_step() -> None:
    provider = AwsProvider()
    arch = provider.choose(kitchen_sink_system(), Prefs())
    steps = provider.steps(arch)
    manual = step(steps, "manual")
    assert [s.id for s in steps].index("manual") > [s.id for s in steps].index("images")
    assert "documentdb" in " ".join(manual.commands)
    assert "elasticache-memcached" in " ".join(manual.commands)


def test_architecture_without_a_cluster_keeps_the_by_hand_steps() -> None:
    _, steps = plan_steps(APP_RUNNER)
    ids = [s.id for s in steps]
    assert "terraform" not in ids and "services" in ids
    assert any("apprunner create-service" in c for c in step(steps, "services").commands)


def test_empty_architecture_has_no_steps() -> None:
    _, steps = plan_steps([svc("lib", "lib", [f("framework", "flask")])])
    assert steps == []


SITE = [f("framework", "vite"), f("framework", "react")]


def test_a_static_site_alone_uses_the_terraform_flow_with_a_frontend_step() -> None:
    _, steps = plan_steps([svc("web", "static", SITE)])
    ids = [s.id for s in steps]
    assert ids == ["account", "state", "terraform", "frontend", "cicd", "rollback", "verify"]


def test_frontend_step_builds_syncs_invalidates_and_explains_dns() -> None:
    _, steps = plan_steps([svc("api", "web", API_FACTS), svc("web", "static", SITE)])
    ids = [s.id for s in steps]
    assert ids.index("terraform") < ids.index("images") < ids.index("frontend")
    text = "\n".join(step(steps, "frontend").commands)
    assert "npm ci && npm run build" in text
    assert "aws s3 sync dist/ s3://" in text and "--delete" in text
    assert "create-invalidation --distribution-id" in text and '--paths "/*"' in text
    assert "web.<YOUR_DOMAIN>" in text


def test_verify_step_checks_each_site() -> None:
    _, steps = plan_steps([svc("web", "static", SITE)])
    assert any("https://web.<YOUR_DOMAIN>/" in c for c in step(steps, "verify").commands)


def test_frontend_commands_use_the_detected_build_directory() -> None:
    _, steps = plan_steps([svc("blog", "static", [f("framework", "gatsby")])])
    assert "aws s3 sync public/ s3://" in "\n".join(step(steps, "frontend").commands)


def test_alerts_step_confirms_the_email_and_tests_an_alarm_and_checks_scaling() -> None:
    _, steps = plan_steps(FULL)
    alerts = step(steps, "observability")
    assert "alert" in alerts.title.lower()
    text = "\n".join(alerts.commands)
    assert "Confirm subscription" in text
    assert "aws sns list-subscriptions-by-topic" in text
    assert "aws cloudwatch set-alarm-state" in text
    assert "aws application-autoscaling describe-scaling-policies --service-namespace ecs" in text
    assert "terraform.tfvars" in alerts.why or "alert_email" in alerts.why


def test_static_only_systems_have_no_alerts_step() -> None:
    _, steps = plan_steps([svc("web", "static", SITE)])
    assert "observability" not in [s.id for s in steps]
