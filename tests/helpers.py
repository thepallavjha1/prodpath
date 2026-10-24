from pathlib import Path

from prodpath.cache import HashCache
from prodpath.detect import detect_services
from prodpath.extract import extract_system
from prodpath.models import Evidence, Fact, Service, ServiceCandidate, SystemModel
from prodpath.scan import ScanStats, scan_repo


def scan_and_detect(
    repo: Path, cache_path: Path
) -> tuple[list[ServiceCandidate], ScanStats, list[str]]:
    cache = HashCache(cache_path)
    try:
        inventory, stats = scan_repo(repo, cache)
    finally:
        cache.close()
    return detect_services(repo, inventory), stats, [e.path for e in inventory.files]


def write_files(root: Path, files: dict[str, str]) -> None:
    for rel_path, content in files.items():
        target = root / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


def make_fact(kind: str, value: str, path: str = "svc/app.py", line: int = 1) -> Fact:
    evidence = [Evidence(path=path, line=line, snippet="x")]
    return Fact(kind=kind, value=value, evidence=evidence, certainty="parsed")  # type: ignore[arg-type]


def make_service(sid: str, kind: str, facts: list[Fact]) -> Service:
    return Service(id=sid, root=sid, kind=kind, facts=facts)  # type: ignore[arg-type]


def build_system(repo: Path, tmp: Path) -> SystemModel:
    """Run stages 1 to 3 on a repo, caching under tmp."""
    cache = HashCache(tmp / "pipeline.sqlite")
    try:
        inventory, _ = scan_repo(repo, cache)
        system, _ = extract_system(repo, inventory, detect_services(repo, inventory), cache)
    finally:
        cache.close()
    return system


def kitchen_sink_system() -> SystemModel:
    """Every component type the templates know (two static sites included), plus two without."""
    env = ["DATABASE_URL", "API_TOKEN", "PORT", "LOG_LEVEL"]
    shop = [
        make_fact("port", "8000"),
        make_fact("health_endpoint", "/health"),
        make_fact("framework", "flask"),
        make_fact("datastore", "postgres"),
        make_fact("datastore", "mysql"),
        make_fact("cache", "redis"),
        make_fact("object_store", "s3"),
        make_fact("queue", "sqs"),
        make_fact("queue", "sns"),
        *[make_fact("env_var", name) for name in env],
    ]
    jobs = [
        make_fact("worker", "celery"),
        make_fact("datastore", "postgres"),
        make_fact("queue", "sqs"),
        make_fact("datastore", "mongodb"),  # no template yet: listed as a gap
        make_fact("env_var", "REDIS_URL"),
    ]
    admin = [
        make_fact("framework", "django"),  # no port: the port is assumed and flagged
        make_fact("cache", "memcached"),  # no template yet: listed as a gap
        make_fact("env_var", "SECRET_KEY"),
    ]
    return SystemModel(
        services=[
            make_service("shop", "web", shop),
            make_service("jobs", "worker", jobs),
            make_service("nightly", "cron", [make_fact("runtime", "python:3.12")]),
            make_service("admin", "web", admin),
            make_service(
                "landing",
                "static",
                [make_fact("framework", "vite"), make_fact("framework", "react")],
            ),
            make_service("docs", "static", [make_fact("framework", "docusaurus")]),
        ]
    )


# Old hand-computed tests assume one request per second on average; pinning it keeps their
# arithmetic checkable now that the default traffic is a peak of 20 req/s (average 4).
ONE_RPS = {"avg_requests_per_second": 1.0}
