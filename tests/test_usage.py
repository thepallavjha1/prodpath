from pathlib import Path

import pytest

from prodpath.forecast import DEFAULTS, UsageBook, UsageError, load_usage_file


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "usage.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_defaults_are_labelled_default_and_recorded_once() -> None:
    book = UsageBook()
    assert book.get("avg_requests_per_second") == DEFAULTS["avg_requests_per_second"][0]
    book.get("avg_requests_per_second", "svc-a")
    book.get("avg_requests_per_second", "svc-b")
    used = [a for a in book.assumptions() if a.name == "avg_requests_per_second"]
    assert len(used) == 1 and used[0].source == "default"


def test_overrides_and_service_overrides_win_in_that_order(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        'avg_requests_per_second = 4\nresponse_kb = 50\n\n[service."apps-web"]\n'
        "avg_requests_per_second = 20\n",
    )
    book = load_usage_file(path)
    assert book.get("avg_requests_per_second", "apps-web") == 20
    assert book.get("avg_requests_per_second", "other") == 4
    assert book.get("response_kb") == 50
    sources = {a.name: a.source for a in book.assumptions()}
    assert sources == {
        "avg_requests_per_second@apps-web": "user",
        "avg_requests_per_second": "user",
        "response_kb": "user",
    }


def test_scenario_factors() -> None:
    book = UsageBook({"scenario_spike": 10.0})
    assert (book.factor("low"), book.factor("expected"), book.factor("spike")) == (0.25, 1.0, 10.0)


def test_inferred_assumptions_are_labelled_inferred() -> None:
    book = UsageBook()
    book.infer("internal_http_calls_per_request", 1.0, "calls", "from edges")
    assert book.assumptions()[0].source == "inferred"


def test_unknown_keys_are_rejected_with_the_allowed_list(tmp_path: Path) -> None:
    with pytest.raises(UsageError, match=r"unknown key 'rps'.*avg_requests_per_second"):
        load_usage_file(write(tmp_path, "rps = 3\n"))


def test_service_tables_only_accept_per_service_keys(tmp_path: Path) -> None:
    with pytest.raises(UsageError, match=r"\[service.api\] has unknown key 'scenario_spike'"):
        load_usage_file(write(tmp_path, '[service."api"]\nscenario_spike = 3\n'))


@pytest.mark.parametrize("value", ["-1", '"fast"', "true"])
def test_values_must_be_non_negative_numbers(tmp_path: Path, value: str) -> None:
    with pytest.raises(UsageError, match="non-negative number"):
        load_usage_file(write(tmp_path, f"avg_requests_per_second = {value}\n"))


def test_missing_and_invalid_files_are_clear_errors(tmp_path: Path) -> None:
    with pytest.raises(UsageError, match="not found"):
        load_usage_file(tmp_path / "nope.toml")
    with pytest.raises(UsageError, match="not valid TOML"):
        load_usage_file(write(tmp_path, "this is = = broken"))
