"""Module-level proxy to the active FastAPI ``TestClient``.

The integration ``conftest.py`` builds one ``TestClient`` per test session
and registers it via :func:`set_test_client`. Test code imports ``client``
from this module and calls it like a normal ``TestClient`` /
``httpx.Client``: ``client.get("/foo")``, ``client.post("/foo", json=...)``,
``with client.stream("GET", "/sse") as r: ...``.

The indirection (proxy instead of the bare TestClient) exists because the
client is created lazily by a session-scoped fixture, after test modules
have already been imported and bound their ``client`` reference.
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

_test_client: TestClient | None = None


def set_test_client(c: TestClient | None) -> None:
    global _test_client
    _test_client = c


def _require_client() -> TestClient:
    if _test_client is None:
        raise RuntimeError(
            "TestClient not initialized; integration conftest must call "
            "set_test_client() before any HTTP-using fixture runs."
        )
    return _test_client


class _TestClientProxy:
    """Forwards every attribute access to the active TestClient."""

    def __getattr__(self, name: str) -> Any:
        return getattr(_require_client(), name)


client = _TestClientProxy()
