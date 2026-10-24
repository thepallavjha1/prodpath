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
    found = {a.name: a.source for a in book.assumptions()}
    for name in ("avg_requests_per_second@apps-web", "avg_requests_per_second", "response_kb"):
        assert found[name] == "user", name


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


# ---- peak versus average traffic (ADR-020) -------------------------------------------------


def values(book: UsageBook) -> dict[str, float]:
    return {a.name: a.value for a in book.assumptions()}


def sources(book: UsageBook) -> dict[str, str]:
    return {a.name: a.source for a in book.assumptions()}


def test_defaults_are_a_peak_of_20_with_an_average_of_4() -> None:
    book = UsageBook()
    assert book.get("avg_requests_per_second") == pytest.approx(4.0)
    assert book.factor("spike") == pytest.approx(5.0)  # a month at the peak
    assert values(book) == {
        "avg_requests_per_second": 4.0,
        "peak_requests_per_second": 20.0,
        "peak_to_average_ratio": 5.0,
        "scenario_spike": 5.0,
    }
    assert set(sources(book).values()) == {"default"}
    note = next(a.note for a in book.assumptions() if a.name == "avg_requests_per_second")
    assert "peak" in note and "ratio" in note


def test_a_user_peak_derives_the_average_and_is_labelled_user() -> None:
    book = UsageBook({"peak_requests_per_second": 50.0})
    assert book.get("avg_requests_per_second") == pytest.approx(10.0)
    assert book.factor("spike") == pytest.approx(5.0)
    assert sources(book)["peak_requests_per_second"] == "user"
    assert sources(book)["avg_requests_per_second"] == "user"  # derived from a user number
    assert sources(book)["peak_to_average_ratio"] == "default"


def test_a_user_average_implies_a_peak_through_the_ratio() -> None:
    book = UsageBook({"avg_requests_per_second": 2.0})
    assert book.get("avg_requests_per_second") == 2.0
    assert book.factor("spike") == pytest.approx(5.0)
    assert values(book)["peak_requests_per_second"] == pytest.approx(10.0)


def test_the_ratio_changes_both_the_average_and_the_spike() -> None:
    book = UsageBook({"peak_requests_per_second": 60.0, "peak_to_average_ratio": 3.0})
    assert book.get("avg_requests_per_second") == pytest.approx(20.0)
    assert book.factor("spike") == pytest.approx(3.0)


def test_giving_both_the_average_and_the_peak_sets_the_spike_to_their_quotient() -> None:
    book = UsageBook({"avg_requests_per_second": 4.0, "peak_requests_per_second": 40.0})
    assert book.get("avg_requests_per_second") == 4.0
    assert book.factor("spike") == pytest.approx(10.0)


def test_a_service_can_have_its_own_peak() -> None:
    book = UsageBook(service_overrides={"api": {"peak_requests_per_second": 100.0}})
    assert book.get("avg_requests_per_second", "api") == pytest.approx(20.0)
    assert book.get("avg_requests_per_second", "web") == pytest.approx(4.0)
    names = values(book)
    assert names["avg_requests_per_second@api"] == pytest.approx(20.0)
    assert names["avg_requests_per_second"] == pytest.approx(4.0)


def test_an_explicit_spike_factor_still_wins() -> None:
    book = UsageBook({"scenario_spike": 8.0})
    assert book.factor("spike") == 8.0
    assert sources(book)["scenario_spike"] == "user"


def test_the_ratio_must_be_at_least_one(tmp_path: Path) -> None:
    with pytest.raises(UsageError, match="peak_to_average_ratio must be at least 1"):
        load_usage_file(write(tmp_path, "peak_to_average_ratio = 0.5\n"))


def test_peak_keys_are_accepted_globally_and_per_service(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        'peak_requests_per_second = 40\n\n[service."api"]\npeak_requests_per_second = 100\n',
    )
    book = load_usage_file(path)
    assert book.get("avg_requests_per_second", "api") == pytest.approx(20.0)
    assert book.get("avg_requests_per_second", "web") == pytest.approx(8.0)


# ---- usage template ------------------------------------------------------------------------


def test_the_template_lists_every_assumption_with_its_unit_and_note() -> None:
    from prodpath.forecast import DEFAULTS, usage_template

    text = usage_template()
    for name in DEFAULTS:
        assert name in text, name
    assert "peak_requests_per_second = 20" in text
    assert "# avg_requests_per_second" in text  # derived by default, so left commented out
    assert "[service." in text  # shows the per-service form


def test_the_template_round_trips_and_changes_nothing(tmp_path: Path) -> None:
    from prodpath.forecast import usage_template

    book = load_usage_file(write(tmp_path, usage_template()))
    default = UsageBook()
    for name in ("avg_requests_per_second", "rps_per_task", "response_kb", "s3_stored_gb"):
        assert book.get(name) == pytest.approx(default.get(name)), name
    assert book.factor("spike") == pytest.approx(default.factor("spike"))
    assert book.factor("low") == pytest.approx(default.factor("low"))
