import pytest

from prodpath.redact import redact


@pytest.mark.parametrize(
    "text, secret",
    [
        ('password = "hunter2"', "hunter2"),
        ("password=hunter2 extra", "hunter2"),
        ('{"api_key": "abc123xyz"}', "abc123xyz"),
        ("token: s3cr3t-value", "s3cr3t-value"),
        ("key AKIAIOSFODNN7EXAMPLE here", "AKIAIOSFODNN7EXAMPLE"),
        ("ASIAIOSFODNN7EXAMPLE", "ASIAIOSFODNN7EXAMPLE"),
        ("postgres://admin:hunter2@db/app", "hunter2"),
        ("-----BEGIN RSA PRIVATE KEY-----\nMIIabc", "MIIabc"),
        ("DB_PASSWORD = os.environ.get('x') or 'hunter2'", "hunter2"),
    ],
)
def test_secrets_are_removed(text: str, secret: str) -> None:
    assert secret not in redact(text)


def test_harmless_text_is_untouched() -> None:
    line = "app.run(port=8000)  # start the server"
    assert redact(line) == line


def test_names_are_kept_so_evidence_stays_useful() -> None:
    assert redact("password=hunter2").startswith("password=")
    assert redact("postgres://admin:hunter2@db/app") == "postgres://admin:[REDACTED]@db/app"
