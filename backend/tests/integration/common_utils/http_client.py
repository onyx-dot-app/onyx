"""Module-level proxy to the active FastAPI ``TestClient``.

The integration ``conftest.py`` builds one ``TestClient`` per test session and
registers it via :func:`set_test_client`. Test code imports ``client`` from this
module and calls it like a normal ``TestClient`` / ``httpx.Client``:
``client.get("/foo")``, ``client.post("/foo", json=...)``, ``with
client.stream("GET", "/sse") as r: ...``.

The indirection (proxy instead of the bare TestClient) exists because the client
is created lazily by a session-scoped fixture, after test modules have already
been imported and bound their ``client`` reference.
"""

from __future__ import annotations

from typing import Any

import httpx

from tests.integration.common_utils.constants import API_SERVER_URL

# Typed as ``httpx.Client`` so both FastAPI's ``TestClient`` (in-process, the
# default) and a raw ``httpx.Client`` (used by the docker e2e to hit a real
# dockerized api_server) satisfy the signature.
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
