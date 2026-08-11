"""Shared fixtures, and the guard that keeps the promise made in pyproject.toml.

Every test in this tree runs offline. A test that reaches the network is a test
that fails when Open Data DC is slow, when CI has no egress, and when someone
runs pytest on a train -- and worse, one that passes on the author's machine
while doing so. So the socket is closed by default and a test has to ask for it
by name.
"""

from __future__ import annotations

import socket

import pytest


@pytest.fixture(autouse=True)
def _offline(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail any test that opens a socket, unless it is marked `network`.

    This covers `socket.socket.connect`, which is what requests, urllib and
    psycopg all end up calling. It is a guard rail rather than a sandbox: code
    reaching below the `socket` module would slip past it.
    """
    if request.node.get_closest_marker("network"):
        return

    def blocked(self: socket.socket, address: object, *args: object, **kwargs: object) -> None:
        raise RuntimeError(
            f"This test tried to reach {address!r}, but tests run offline.\n"
            "Use a fixture under tests/data/, or -- if the test genuinely needs "
            "egress -- mark it @pytest.mark.network and say why in its docstring."
        )

    monkeypatch.setattr(socket.socket, "connect", blocked)
