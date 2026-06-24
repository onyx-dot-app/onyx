"""Module-level proxy to the active integration HTTP client.

The default integration ``conftest.py`` builds one in-process FastAPI
``TestClient`` per test session and registers it via :func:`set_test_client`.
Directory-specific suites can install a raw ``httpx.Client`` instead when they
need to hit an out-of-process API server. Test code imports ``client`` from this
module and calls it like a normal client:
``client.get("/foo")``, ``client.post("/foo", json=...)``, ``with
client.stream("GET", "/sse") as r: ...``.

The indirection exists because the client is created lazily by a session-scoped
fixture, after test modules have already imported and bound their ``client``
reference.
"""

from __future__ import annotations

from typing import Any

import httpx

from tests.integration.common_utils.constants import API_SERVER_URL

# Typed as ``httpx.Client`` so both FastAPI's ``TestClient`` and a raw
# ``httpx.Client`` satisfy the signature.
_test_client: httpx.Client | None = None


def set_test_client(c: httpx.Client | None) -> None:
    global _test_client
    _test_client = c


def _require_client() -> httpx.Client:
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


def request_status(headers: dict[str, str], route: tuple[str, str]) -> int:
    """
    Issues ``route`` (method, path) with ``headers`` and return the status code.
    """
    method, path = route
    return client.request(
        method, f"{API_SERVER_URL}{path}", headers=headers, timeout=30
    ).status_code
