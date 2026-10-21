import re

from prodpath.models import Architecture, Prefs, Service, Step, SystemModel
from prodpath.providers.aws import AwsProvider
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


def step(steps: list[Step], step_id: str) -> Step:
    return next(s for s in steps if s.id == step_id)


def test_steps_are_ordered_and_complete() -> None:
    _, steps = plan_steps(FULL)
    ids = [s.id for s in steps]
    assert ids == [
        "account", "state", "network", "data", "secrets", "images",
        "services", "schedules", "cicd", "observability", "rollback", "verify",
    ]  # fmt: skip
    assert ids.index("data") < ids.index("services")
    assert ids.index("images") < ids.index("services")


def test_every_step_explains_and_verifies() -> None:
    _, steps = plan_steps(FULL)
    assert all(s.title and s.why and s.verify for s in steps)


def test_state_bucket_location_constraint_rules() -> None:
    _, mumbai = plan_steps(FULL, "ap-south-1")
    _, virginia = plan_steps(FULL, "us-east-1")
    assert "LocationConstraint=ap-south-1" in step(mumbai, "state").commands[0]
    assert "LocationConstraint" not in step(virginia, "state").commands[0]


def test_secret_commands_create_slots_without_values() -> None:
    _, steps = plan_steps(FULL)
    commands = step(steps, "secrets").commands
    assert any("create-secret --name prod/api/DATABASE_URL" in c for c in commands)
    assert not any("--secret-string" in c for c in commands)


def test_service_step_uses_detected_port_and_health_path() -> None:
    _, steps = plan_steps(FULL)
    assert any(
        "container port 8000" in c and "/health" in c for c in step(steps, "services").commands
    )


def test_no_account_ids_or_keys_in_any_command() -> None:
    _, steps = plan_steps(FULL)
    text = "\n".join(c for s in steps for c in s.commands)
    assert not re.search(r"\b\d{12}\b", text) and "AKIA" not in text
    assert "<ACCOUNT_ID>" in text


def test_empty_architecture_has_no_steps() -> None:
    _, steps = plan_steps([svc("lib", "lib", [f("framework", "flask")])])
    assert steps == []
