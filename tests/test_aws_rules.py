from prodpath.models import Architecture, Component, Prefs, Service, SystemModel
from prodpath.providers.aws.rules import choose_architecture
from tests.helpers import make_fact as f
from tests.helpers import make_service as svc


def choose(services: list[Service], env: str = "prod") -> Architecture:
    prefs = Prefs(environment=env)  # type: ignore[arg-type]
    return choose_architecture(SystemModel(services=services), prefs)


def types(arch: Architecture) -> set[str]:
    return {c.type for c in arch.components}


def by_name(arch: Architecture, name: str) -> Component:
    return next(c for c in arch.components if c.name == name)


WEB = [f("port", "8000"), f("framework", "flask")]


def test_lone_web_service_without_data_gets_app_runner() -> None:
    arch = choose([svc("site", "web", WEB)])
    assert "apprunner" in types(arch)
    assert not types(arch) & {"vpc", "alb", "ecs-cluster", "ecs-service-web"}


def test_web_with_database_gets_fargate_alb_and_rds() -> None:
    arch = choose([svc("api", "web", [*WEB, f("datastore", "postgres")])])
    assert {"vpc", "alb", "ecs-cluster", "ecs-service-web", "rds"} <= types(arch)
    assert "Multi-AZ" in by_name(arch, "rds-postgres").sizing


def test_nonprod_is_single_az_and_one_task() -> None:
    arch = choose([svc("api", "web", [*WEB, f("datastore", "postgres")])], env="nonprod")
    assert "single-AZ" in by_name(arch, "rds-postgres").sizing
    assert "1 task" in by_name(arch, "ecs-svc-api").sizing


def test_two_services_share_one_database_instance() -> None:
    arch = choose(
        [
            svc("a", "web", [*WEB, f("datastore", "postgres")]),
            svc("b", "worker", [f("worker", "celery"), f("datastore", "postgres")]),
        ]
    )
    rds = [c for c in arch.components if c.type == "rds"]
    assert len(rds) == 1 and rds[0].serves == ["a", "b"]


def test_bullmq_needs_redis_even_without_a_redis_fact() -> None:
    arch = choose([svc("w", "worker", [f("queue", "bullmq")])])
    assert "elasticache-redis" in {c.name for c in arch.components}


def test_celery_without_a_broker_is_an_unknown() -> None:
    arch = choose([svc("w", "worker", [f("worker", "celery")])])
    assert any("Celery" in u and "broker" in u for u in arch.unknowns)


def test_cron_becomes_scheduled_task_and_schedule_is_unknown() -> None:
    arch = choose([svc("job", "cron", [f("runtime", "python:3.12")])])
    assert "scheduled-task" in types(arch)
    assert any("job" in u and "schedule" in u for u in arch.unknowns)


def test_secret_slots_hold_names_only_and_skip_plain_config() -> None:
    names = ("DATABASE_URL", "STRIPE_API_KEY", "PORT", "LOG_LEVEL")
    arch = choose([svc("api", "web", [*WEB, *[f("env_var", n) for n in names]])])
    assert by_name(arch, "secrets-api").items == ["DATABASE_URL", "STRIPE_API_KEY"]


def test_local_file_writes_are_flagged() -> None:
    arch = choose([svc("api", "web", [*WEB, f("local_state", "/tmp/x")])])
    assert any("ephemeral" in u for u in arch.unknowns)


def test_web_without_a_port_is_an_unknown() -> None:
    arch = choose([svc("api", "web", [f("framework", "flask")])])
    assert any("no listening port" in u for u in arch.unknowns)


def test_libs_factless_and_unknown_kinds_are_not_deployed() -> None:
    arch = choose(
        [
            svc("lib", "lib", [f("framework", "flask")]),
            svc("empty", "web", []),
            svc("odd", "unknown", [f("framework", "flask")]),
        ]
    )
    assert arch.components == []
    assert any("odd" in u and "could not be classified" in u for u in arch.unknowns)
    assert any("nothing to plan" in u for u in arch.unknowns)


def test_storage_and_queues() -> None:
    facts = [*WEB, f("object_store", "s3"), f("queue", "sqs"), f("queue", "kafka")]
    arch = choose([svc("api", "web", facts)])
    assert {"s3", "sqs", "msk"} <= types(arch)


def test_every_component_has_reason_known_services_and_evidence() -> None:
    services = [
        svc("a", "web", [*WEB, f("datastore", "postgres"), f("cache", "redis")]),
        svc("b", "cron", [f("runtime", "python")]),
    ]
    arch = choose(services)
    for c in arch.components:
        assert c.reason.strip()
        assert set(c.serves) <= {"a", "b"}
        if c.type not in {"tf-state", "iam-github-oidc"}:
            assert c.evidence, c.name
    assert len({c.name for c in arch.components}) == len(arch.components)


def test_output_is_deterministic_and_foundation_comes_first() -> None:
    services = [
        svc("b", "web", [*WEB, f("datastore", "postgres")]),
        svc("a", "worker", [f("worker", "rq")]),
    ]
    first, second = choose(services), choose(list(reversed(services)))
    assert first.model_dump_json() == second.model_dump_json()
    assert [c.type for c in first.components][:2] == ["tf-state", "iam-github-oidc"]
