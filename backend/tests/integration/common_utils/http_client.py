"""TestClient-backed HTTP client shim.

Integration tests call ``client.get/post/put/patch/delete/request(url, ...)``,
backed by a FastAPI ``TestClient`` (an ``httpx.Client``) that drives the
ASGI app in-process — no uvicorn, no socket.

The returned ``httpx.Response`` exposes the attributes tests rely on:
``.status_code``, ``.json()``, ``.headers``, ``.cookies``,
``.iter_lines()``, ``.raise_for_status()``, ``.content``, ``.text``.

The active ``TestClient`` is owned by a session-scoped fixture in the
integration ``conftest.py`` which calls :func:`set_test_client` on startup
and clears it on teardown.
"""

from __future__ import annotations

from typing import Any

import httpx
from fastapi.testclient import TestClient

# Re-exports for callers that want the exception/response types directly.
HTTPError = httpx.HTTPStatusError
RequestException = httpx.RequestError
Response = httpx.Response
CaseInsensitiveDict = httpx.Headers


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


class _Exceptions:
    HTTPError = httpx.HTTPStatusError
    RequestException = httpx.RequestError
    # `requests` raises ChunkedEncodingError when a streamed body's
    # chunked-transfer framing is malformed; httpx surfaces the equivalent
    # as RemoteProtocolError.
    ChunkedEncodingError = httpx.RemoteProtocolError


class _Client:
    """Thin HTTP surface backed by the active TestClient."""

    Response = httpx.Response
    HTTPError = httpx.HTTPStatusError
    RequestException = httpx.RequestError
    exceptions = _Exceptions

    def request(self, method: str, url: str, **kwargs: Any) -> Any:
        return _dispatch(method, url, **kwargs)

    def get(self, url: str, **kwargs: Any) -> Any:
        return _dispatch("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> Any:
        return _dispatch("POST", url, **kwargs)

    def put(self, url: str, **kwargs: Any) -> Any:
        return _dispatch("PUT", url, **kwargs)

    def patch(self, url: str, **kwargs: Any) -> Any:
        return _dispatch("PATCH", url, **kwargs)

    def delete(self, url: str, **kwargs: Any) -> Any:
        return _dispatch("DELETE", url, **kwargs)

    def head(self, url: str, **kwargs: Any) -> Any:
        return _dispatch("HEAD", url, **kwargs)

    def options(self, url: str, **kwargs: Any) -> Any:
        return _dispatch("OPTIONS", url, **kwargs)


def _dispatch(method: str, url: str, **kwargs: Any) -> Any:
    """Route a single call to TestClient.stream() or .request().

    `stream=True` (the ``requests`` flag) becomes httpx's context-manager
    streaming API. All other kwargs pass through unchanged.
    """
    c = _require_client()
    stream = kwargs.pop("stream", False)
    if stream:
        return c.stream(method, url, **kwargs)
    return c.request(method, url, **kwargs)


client = _Client()
