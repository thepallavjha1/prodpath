import pytest
from pydantic import ValidationError

from prodpath.models import CostLine, Evidence, Fact


def test_fact_requires_evidence() -> None:
    with pytest.raises(ValidationError):
        Fact(kind="datastore", value="postgres", evidence=[], certainty="parsed")


def test_fact_with_evidence_is_valid() -> None:
    fact = Fact(
        kind="datastore",
        value="postgres",
        evidence=[Evidence(path="requirements.txt", line=2, snippet="psycopg2-binary")],
        certainty="parsed",
    )
    assert fact.evidence[0].path == "requirements.txt"


def test_evidence_snippet_is_bounded() -> None:
    with pytest.raises(ValidationError):
        Evidence(path="a.py", line=1, snippet="x" * 201)


def test_cost_line_requires_price_ref() -> None:
    values = dict(
        component="alb", dimension="hours", unit="h", qty_low=1, qty_expected=1, qty_spike=1,
        unit_price=0.1, usd_low=0.1, usd_expected=0.1, usd_spike=0.1,
    )  # fmt: skip
    with pytest.raises(ValidationError):
        CostLine(price_ref="", **values)
    assert CostLine(price_ref="offer-123", **values).price_ref == "offer-123"
