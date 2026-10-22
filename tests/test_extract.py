import logging
import shutil
from pathlib import Path

import pytest

from prodpath.cache import HashCache
from prodpath.cli import main
from prodpath.detect import detect_services
from prodpath.extract import extract_system
from prodpath.models import SystemModel
from prodpath.scan import scan_repo
from tests.helpers import write_files

GOLDEN = Path(__file__).parent / "golden"
FIXTURE_NAMES = ["mono_a", "mono_b", "mono_c", "mono_d"]
FAKE_SECRETS = ["hunter2"]


def run_extract(repo: Path, cache_path: Path):  # type: ignore[no-untyped-def]
    cache = HashCache(cache_path)
    try:
        inventory, _ = scan_repo(repo, cache)
        candidates = detect_services(repo, inventory)
        return extract_system(repo, inventory, candidates, cache)
    finally:
        cache.close()


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_system_matches_golden(
    name: str, fixtures_dir: Path, tmp_path: Path, update_golden: bool
) -> None:
    system, _ = run_extract(fixtures_dir / name, tmp_path / "c.sqlite")
    actual = system.model_dump_json(indent=2) + "\n"
    golden_file = GOLDEN / f"system_{name}.json"
    if update_golden:
        golden_file.write_text(actual, encoding="utf-8")
    assert actual == golden_file.read_text(encoding="utf-8")


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_every_fact_has_evidence_and_bounded_snippets(
    name: str, fixtures_dir: Path, tmp_path: Path
) -> None:
    system, _ = run_extract(fixtures_dir / name, tmp_path / "c.sqlite")
    facts = [f for s in system.services for f in s.facts] + system.shared_infra
    assert facts
    for fact in facts:
        assert fact.evidence
        assert all(len(e.snippet) <= 200 and e.path for e in fact.evidence)
    assert all(edge.evidence for edge in system.edges)


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_no_secret_value_in_output_or_logs(
    name: str, fixtures_dir: Path, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG):
        system, _ = run_extract(fixtures_dir / name, tmp_path / "c.sqlite")
    output = system.model_dump_json() + caplog.text
    for secret in FAKE_SECRETS:
        assert secret not in output


def test_secret_fixture_is_really_exercised(fixtures_dir: Path, tmp_path: Path) -> None:
    system, _ = run_extract(fixtures_dir / "mono_a", tmp_path / "c.sqlite")
    names = {f.value for f in system.services[0].facts if f.kind == "env_var"}
    assert {"DATABASE_URL", "FLASK_SECRET"} <= names  # names kept, values dropped
    source = (fixtures_dir / "mono_a/app/config.py").read_text()
    assert "hunter2" in source


def test_second_run_extracts_nothing_and_output_is_identical(
    fixtures_dir: Path, tmp_path: Path
) -> None:
    cache_path = tmp_path / "c.sqlite"
    first, first_stats = run_extract(fixtures_dir / "mono_c", cache_path)
    second, second_stats = run_extract(fixtures_dir / "mono_c", cache_path)
    assert first_stats.extracted > 0 and first_stats.cached == 0
    assert second_stats.extracted == 0 and second_stats.cached == first_stats.extracted
    assert first.model_dump_json() == second.model_dump_json()


def test_changed_file_is_the_only_one_reextracted(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    write_files(
        repo,
        {
            "Dockerfile": "FROM python:3.12\n",
            "a.py": "import flask\n",
            "b.py": "import redis\n",
        },
    )
    cache_path = tmp_path / "c.sqlite"
    run_extract(repo, cache_path)
    (repo / "a.py").write_text("import flask\nimport psycopg2\n", encoding="utf-8")
    system, stats = run_extract(repo, cache_path)
    assert (stats.extracted, stats.cached) == (1, 1)
    assert ("datastore", "postgres") in {(f.kind, f.value) for f in system.services[0].facts}


def test_shared_infra_and_http_edges(fixtures_dir: Path, tmp_path: Path) -> None:
    system_b, _ = run_extract(fixtures_dir / "mono_b", tmp_path / "b.sqlite")
    assert [(f.kind, f.value) for f in system_b.shared_infra] == [("cache", "redis")]
    assert {(e.src, e.dst, e.via) for e in system_b.edges} == {
        ("api", "infra:redis", "cache"),
        ("worker", "infra:redis", "cache"),
    }
    system_c, _ = run_extract(fixtures_dir / "mono_c", tmp_path / "c.sqlite")
    assert {(e.src, e.dst, e.via) for e in system_c.edges} == {
        ("apps-gateway", "apps-billing", "http"),
        ("apps-gateway", "apps-users", "http"),
    }


def test_unparsable_and_test_files_are_listed_not_hidden(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    write_files(
        repo,
        {
            "Dockerfile": "FROM python:3.12\n",
            "bad.py": "def (:\n",
            "tests/test_x.py": "import redis\n",
            "good.py": "import flask\n",
        },
    )
    system, _ = run_extract(repo, tmp_path / "c.sqlite")
    assert any(note.startswith("bad.py: python syntax error") for note in system.not_analyzed)
    assert "1 test files excluded from analysis" in system.not_analyzed
    facts = {(f.kind, f.value) for f in system.services[0].facts}
    assert ("framework", "flask") in facts and ("cache", "redis") not in facts


def test_nested_service_files_belong_to_the_deepest_root(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    write_files(
        repo,
        {
            "Dockerfile": "FROM python:3.12\n",
            "app.py": "import flask\n",
            "sub/Dockerfile": "FROM node:20\n",
            "sub/server.js": 'require("express");\n',
        },
    )
    system, _ = run_extract(repo, tmp_path / "c.sqlite")
    by_id = {s.id: {(f.kind, f.value) for f in s.facts} for s in system.services}
    assert ("framework", "express") in by_id["sub"]
    assert ("framework", "express") not in by_id["root"]
    assert ("framework", "flask") in by_id["root"]


def test_cli_facts_writes_only_under_prodpath(
    fixtures_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = tmp_path / "mono_a"
    shutil.copytree(fixtures_dir / "mono_a", repo)
    before = {p.relative_to(repo).as_posix() for p in repo.rglob("*") if p.is_file()}
    assert main(["facts", "--path", str(repo)]) == 0
    after = {p.relative_to(repo).as_posix() for p in repo.rglob("*") if p.is_file()}
    assert all(p.startswith(".prodpath/") for p in after - before)
    out = capsys.readouterr().out
    assert "framework       flask" in out
    for secret in FAKE_SECRETS:
        assert secret not in out
    system = SystemModel.model_validate_json((repo / ".prodpath/system.json").read_text())
    assert system.services[0].facts
