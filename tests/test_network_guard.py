import socket

import pytest


def test_non_localhost_connection_is_blocked() -> None:
    with socket.socket() as sock, pytest.raises(AssertionError, match="network guard"):
        sock.connect(("93.184.216.34", 80))


def test_localhost_is_allowed_through_the_guard() -> None:
    # Nothing listens on port 9, so we expect a normal refusal, not the guard's AssertionError.
    with socket.socket() as sock, pytest.raises(OSError):
        sock.connect(("127.0.0.1", 9))
