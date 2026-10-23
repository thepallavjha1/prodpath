from pathlib import Path

import pytest

from prodpath.cli import main


def test_help_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--help"])
    assert exit_info.value.code == 0
    assert "doctor" in capsys.readouterr().out


@pytest.mark.parametrize("command", ["scan", "facts", "summarize", "plan", "forecast", "run"])
@pytest.mark.parametrize(
    "url",
    ["https://github.com/someone/some-repo", "http://example.com/x", "git@github.com:a/b.git"],
)
def test_a_git_url_is_rejected_with_the_clone_hint(
    command: str, url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main([command, "--path", url])
    assert exit_info.value.code == 2
    err = capsys.readouterr().err
    assert "local folder" in err and "git clone" in err and url in err


def test_a_missing_folder_is_reported_clearly(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["scan", "--path", str(tmp_path / "nope")])
    assert exit_info.value.code == 2
    assert "does not exist" in capsys.readouterr().err


def test_a_file_instead_of_a_folder_is_reported_clearly(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    afile = tmp_path / "a.txt"
    afile.write_text("x", encoding="utf-8")
    with pytest.raises(SystemExit):
        main(["scan", "--path", str(afile)])
    assert "not a folder" in capsys.readouterr().err


def test_run_checks_the_usage_file_before_doing_any_work(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    prices = tmp_path / "prices"
    prices.mkdir()
    (prices / "ap-south-1.json").write_text("{}", encoding="utf-8")  # exists; never read
    code = main(
        [
            "run",
            "--path",
            str(repo),
            "--prices-dir",
            str(prices),
            "--usage",
            str(tmp_path / "usage.toml."),
        ]
    )
    assert code == 1
    err = capsys.readouterr().err
    assert "usage file not found" in err and "usage.toml." in err
    assert not (repo / ".prodpath").exists()  # nothing was written
