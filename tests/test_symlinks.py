"""A repo we analyse is untrusted: a symlink must never make us read a file outside it."""

import os
from pathlib import Path

import pytest

from prodpath.cache import HashCache
from prodpath.detect import detect_services
from prodpath.extract import extract_system
from prodpath.scan import scan_repo
from tests.helpers import write_files

SECRET = "TOP_SECRET_OUTSIDE_THE_REPO"


def analyse(repo: Path, tmp_path: Path):  # type: ignore[no-untyped-def]
    cache = HashCache(tmp_path / "c.sqlite")
    try:
        inventory, stats = scan_repo(repo, cache)
        candidates = detect_services(repo, inventory)
        system, _ = extract_system(repo, inventory, candidates, cache)
    finally:
        cache.close()
    return inventory, stats, candidates, system


def make_repo_with_symlinks(tmp_path: Path) -> Path:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.py").write_text(f'import os\nTOKEN = "{SECRET}"\nos.environ["LEAKED"]\n')
    (outside / "Dockerfile").write_text(f"FROM python:3.12\nENV {SECRET}=1\nEXPOSE 1234\n")
    repo = tmp_path / "repo"
    write_files(repo, {"app/main.py": "from flask import Flask\napp = Flask(__name__)\n"})
    try:
        os.symlink(outside / "secret.py", repo / "app" / "linked.py")
        os.symlink(outside / "Dockerfile", repo / "app" / "Dockerfile")
        os.symlink(outside, repo / "linked_dir", target_is_directory=True)
    except OSError:
        pytest.skip("this account cannot create symlinks")
    return repo


def test_symlinked_files_are_listed_as_skipped_and_never_read(tmp_path: Path) -> None:
    repo = make_repo_with_symlinks(tmp_path)
    inventory, stats, candidates, system = analyse(repo, tmp_path)
    skipped = {e.path: e.skipped for e in inventory.files if e.skipped}
    assert skipped == {"app/Dockerfile": "symlink", "app/linked.py": "symlink"}
    assert all(e.hash == "" for e in inventory.files if e.skipped)
    everything = system.model_dump_json() + " ".join(system.not_analyzed)
    assert SECRET not in everything and "LEAKED" not in everything and "1234" not in everything
    assert any("linked.py" in note and "symlink" in note for note in system.not_analyzed)
    assert stats.skipped_symlinks == 2


def test_a_symlinked_dockerfile_cannot_define_a_service(tmp_path: Path) -> None:
    repo = make_repo_with_symlinks(tmp_path)
    _, _, candidates, _ = analyse(repo, tmp_path)
    assert all(c.evidence[0].path != "app/Dockerfile" for c in candidates)


def test_symlinked_directories_are_not_followed(tmp_path: Path) -> None:
    repo = make_repo_with_symlinks(tmp_path)
    inventory, _, _, _ = analyse(repo, tmp_path)
    assert not any(e.path.startswith("linked_dir/") for e in inventory.files)


def test_the_check_does_not_depend_on_the_os_allowing_symlinks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Simulate a symlink so the guard is tested even where symlinks cannot be created."""
    repo = tmp_path / "repo"
    write_files(repo, {"Dockerfile": "FROM python:3.12\nEXPOSE 80\n", "ok.py": "import flask\n"})
    real = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda self: self.name == "Dockerfile" or real(self))
    inventory, _, candidates, system = analyse(repo, tmp_path)
    assert {e.path: e.skipped for e in inventory.files}["Dockerfile"] == "symlink"
    assert candidates == [] or all(c.evidence[0].path != "Dockerfile" for c in candidates)
    assert ("port", "80") not in {(f.kind, f.value) for s in system.services for f in s.facts}


def test_regular_files_are_unaffected(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    write_files(repo, {"Dockerfile": "FROM python:3.12\nEXPOSE 80\n"})
    inventory, stats, candidates, _ = analyse(repo, tmp_path)
    assert [e.skipped for e in inventory.files] == [None]
    assert stats.skipped_symlinks == 0 and [c.id for c in candidates] == ["root"]
