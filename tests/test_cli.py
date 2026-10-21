import pytest

from prodpath.cli import main


def test_help_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--help"])
    assert exit_info.value.code == 0
    assert "doctor" in capsys.readouterr().out


def test_doctor_stub_says_it_checked_nothing(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["doctor"]) == 0
    assert "Nothing was checked" in capsys.readouterr().out
