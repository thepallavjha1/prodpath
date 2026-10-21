import json
import shutil
from pathlib import Path

import pytest

from prodpath.cache import HashCache
from prodpath.cli import main
from prodpath.scan import MAX_HASH_BYTES, scan_repo
from tests.helpers import scan_and_detect, write_files


def test_second_run_does_no_rehashing(fixtures_dir: Path, tmp_path: Path) -> None:
    cache_path = tmp_path / "cache.sqlite"
    _, first, paths = scan_and_detect(fixtures_dir / "mono_c", cache_path)
    _, second, _ = scan_and_detect(fixtures_dir / "mono_c", cache_path)
    assert first.hashed == len(paths) and first.cached == 0
    assert second.hashed == 0 and second.cached == len(paths)


def test_changed_file_is_rehashed_alone(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    write_files(repo, {"a.py": "x = 1\n", "b.py": "y = 2\n"})
    cache_path = tmp_path / "cache.sqlite"
    scan_and_detect(repo, cache_path)
    (repo / "a.py").write_text("x = 22222\n", encoding="utf-8")
    _, stats, _ = scan_and_detect(repo, cache_path)
    assert (stats.hashed, stats.cached) == (1, 1)


def test_inventory_is_byte_identical_across_runs(fixtures_dir: Path, tmp_path: Path) -> None:
    dumps = []
    for run in ("one", "two"):
        cache = HashCache(tmp_path / f"{run}.sqlite")
        inventory, _ = scan_repo(fixtures_dir / "mono_b", cache)
        cache.close()
        dumps.append(inventory.model_dump_json())
    assert dumps[0] == dumps[1]


def test_ignores_builtin_dirs_and_gitignore(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    write_files(
        repo,
        {
            "keep.py": "",
            "node_modules/dep/index.js": "",
            ".prodpath/inventory.json": "{}",
            "secret_dir/x.txt": "",
            "debug.log": "",
            "sub/debug.log": "",
            ".gitignore": "secret_dir/\n*.log\n!keep.log\n",
        },
    )
    cache = HashCache(tmp_path / "c.sqlite")
    inventory, stats = scan_repo(repo, cache)
    cache.close()
    assert [e.path for e in inventory.files] == [".gitignore", "keep.py"]
    assert stats.unsupported_gitignore == ["!keep.log"]


def test_large_files_are_listed_as_skipped(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "big.bin").write_bytes(b"\0" * (MAX_HASH_BYTES + 1))
    cache = HashCache(tmp_path / "c.sqlite")
    inventory, _ = scan_repo(repo, cache)
    cache.close()
    assert inventory.files[0].skipped == "too large"
    assert inventory.files[0].hash == ""


def test_cli_scan_writes_only_under_prodpath(
    fixtures_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = tmp_path / "mono_b"
    shutil.copytree(fixtures_dir / "mono_b", repo)
    before = {p.relative_to(repo).as_posix() for p in repo.rglob("*") if p.is_file()}
    assert main(["scan", "--path", str(repo)]) == 0
    after = {p.relative_to(repo).as_posix() for p in repo.rglob("*") if p.is_file()}
    assert {p for p in after - before if not p.startswith(".prodpath/")} == set()
    assert "api" in capsys.readouterr().out
    assert json.loads((repo / ".prodpath/inventory.json").read_text())["files"]
