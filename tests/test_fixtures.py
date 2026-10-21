from pathlib import Path


def _dockerfile_roots(repo: Path) -> set[str]:
    return {p.parent.relative_to(repo).as_posix() for p in repo.rglob("Dockerfile")}


def test_mono_a_is_one_flask_service(fixtures_dir: Path) -> None:
    repo = fixtures_dir / "mono_a"
    assert _dockerfile_roots(repo) == {"."}
    assert "flask" in (repo / "requirements.txt").read_text()
    assert "psycopg2" in (repo / "requirements.txt").read_text()


def test_mono_b_has_api_worker_and_redis(fixtures_dir: Path) -> None:
    repo = fixtures_dir / "mono_b"
    assert _dockerfile_roots(repo) == {"api", "worker"}
    assert "redis:" in (repo / "docker-compose.yml").read_text()


def test_mono_c_has_six_plus_services_and_a_workspace(fixtures_dir: Path) -> None:
    repo = fixtures_dir / "mono_c"
    assert (repo / "pnpm-workspace.yaml").exists()
    assert len(_dockerfile_roots(repo)) >= 6
    assert (repo / "apps/reports/crontab").exists()


def test_fixtures_contain_no_real_secret_shapes(fixtures_dir: Path) -> None:
    for path in fixtures_dir.rglob("*"):
        if path.is_file():
            text = path.read_text(errors="replace")
            # One documented fake key is allowed (TESTING.md section 4, invariant 2).
            assert "AKIA" not in text.replace("AKIAIOSFODNN7EXAMPLE", ""), path
            assert "BEGIN PRIVATE KEY" not in text, path
