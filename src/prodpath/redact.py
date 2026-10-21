"""Redact secret-looking text before it reaches a snippet, log or prompt (SECURITY.md section 3).

Over-redacting is fine; leaking is not. Patterns are intentionally simple and reviewable.
"""

import re

_SECRET_NAMES = (
    r"[A-Za-z0-9_.-]*(?:password|passwd|secret|token|api[_-]?key|private[_-]?key)[A-Za-z0-9_.-]*"
)

_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), "[REDACTED_AWS_KEY]"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*", re.DOTALL), "[REDACTED_PRIVATE_KEY]"),
    # name = "value", name: value, "name": "value" (name kept). A value is redacted to the end
    # of the line: it may be an expression that ends in a literal secret.
    (
        re.compile(rf"(?i)\b({_SECRET_NAMES}[\"']?\s*[=:]\s*)[^\n]*"),
        r"\1[REDACTED]",
    ),
    # scheme://user:password@host
    (re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://[^\s:/@]+):[^\s@/]+@"), r"\1:[REDACTED]@"),
]


def redact(text: str) -> str:
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text
