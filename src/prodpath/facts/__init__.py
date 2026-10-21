"""Fact extractors, one module per language or format. Shared helpers live here."""

from prodpath.models import Evidence, Fact, FactKind
from prodpath.redact import redact

MAX_SNIPPET = 200


class ExtractionError(Exception):
    """A file could not be analyzed. The caller records it under 'Not analyzed'."""


def make_fact(
    kind: FactKind,
    value: str,
    path: str,
    line: int | None,
    snippet: str,
    certainty: str = "parsed",
) -> Fact:
    """Build a Fact whose single evidence snippet is redacted and length-bounded."""
    evidence = Evidence(path=path, line=line, snippet=redact(snippet.strip())[:MAX_SNIPPET])
    return Fact(
        kind=kind,
        value=value,
        evidence=[evidence],
        certainty="heuristic" if certainty == "heuristic" else "parsed",
    )


def find_line(lines: list[str], needle: str) -> int | None:
    """1-based line number of the first line containing needle."""
    for number, line in enumerate(lines, start=1):
        if needle in line:
            return number
    return None
