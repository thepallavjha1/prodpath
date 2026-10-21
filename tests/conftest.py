import socket
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
LOCALHOST = {"127.0.0.1", "::1", "localhost"}

_real_connect = socket.socket.connect


@pytest.fixture(autouse=True, scope="session")
def no_network_guard():
    """Fail any test that opens a non-localhost connection (ADR-004, SECURITY.md section 2)."""
    original = _real_connect

    def guarded_connect(self: socket.socket, address):  # type: ignore[no-untyped-def]
        # AF_UNIX addresses are plain strings (local IPC), not network hosts.
        if self.family in (socket.AF_INET, socket.AF_INET6) and address[0] not in LOCALHOST:
            raise AssertionError(f"network guard: blocked connection to {address[0]!r}")
        return original(self, address)

    socket.socket.connect = guarded_connect  # type: ignore[method-assign]
    yield
    socket.socket.connect = original  # type: ignore[method-assign]


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--update-golden",
        action="store_true",
        help="rewrite tests/golden/ files; explain why in the commit message",
    )


@pytest.fixture
def update_golden(request: pytest.FixtureRequest) -> bool:
    return bool(request.config.getoption("--update-golden"))


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES
