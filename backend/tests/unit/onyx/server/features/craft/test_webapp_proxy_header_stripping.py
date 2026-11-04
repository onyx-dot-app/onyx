"""The webapp proxy must strip Set-Cookie and policy headers from upstream
responses, sandbox every proxied document into an opaque origin with its CSP,
issue a viewer cookie that admits only that session's subresources, and strip
browser-context headers (Origin, sec-fetch-*) from forwarded requests."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import httpx
import pytest
from starlette.requests import Request
from starlette.responses import Response

from onyx.db.enums import SharingScope
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.build import webapp_proxy


def _make_request(headers: list[tuple[bytes, bytes]] | None = None) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "scheme": "http",
            "path": "/",
            "query_string": b"",
            "headers": headers or [],
        }
    )


class _FakeCache:
    def __init__(self) -> None:
        self.values: dict[str, bytes] = {}

    def get(self, key: str) -> bytes | None:
        return self.values.get(key)

    def set(self, key: str, value: str | bytes, ex: int | None = None) -> None:  # noqa: ARG002
        self.values[key] = value.encode() if isinstance(value, str) else value


def _viewer_token(response: Response) -> str:
    cookie = response.headers["set-cookie"]
    return cookie.split("onyx_craft_webapp=", 1)[1].split(";", 1)[0]


def _run_get_webapp(
    session_id: UUID, user: MagicMock | None, cookie: str | None
) -> Response:
    with patch.object(webapp_proxy, "_check_webapp_access", AsyncMock()):
        return _run_get_webapp_raw(session_id, cookie, user)


def _run_get_webapp_raw(
    session_id: UUID, cookie: str | None, user: MagicMock | None = None
) -> Response:
    client = MagicMock()
    client.build_request = MagicMock()
    client.send = AsyncMock(return_value=_make_upstream())
    headers = [(b"cookie", cookie.encode())] if cookie else []
    with (
        patch.object(
            webapp_proxy,
            "_get_sandbox_url",
            AsyncMock(return_value="http://sandbox-x:3000"),
        ),
        patch.object(webapp_proxy, "_get_proxy_client", return_value=client),
        patch.object(
            webapp_proxy,
            "_load_webapp_access",
            AsyncMock(return_value=(SharingScope.PRIVATE, uuid4())),
        ),
    ):
        return asyncio.run(
            webapp_proxy.get_webapp(session_id, _make_request(headers), "", user)
        )


async def _no_bytes(chunk_size: int = 8192) -> AsyncGenerator[bytes, None]:  # noqa: ARG001
    return
    yield b""  # pragma: no cover


def _make_upstream() -> MagicMock:
    upstream = MagicMock(spec=httpx.Response)
    upstream.status_code = 200
    upstream.headers = httpx.Headers({"content-type": "text/html"})
    upstream.aiter_bytes = _no_bytes
    upstream.aclose = AsyncMock()
    return upstream


def _run_proxy_request(request: Request, client: MagicMock) -> Response:
    with (
        patch.object(
            webapp_proxy,
            "_get_sandbox_url",
            AsyncMock(return_value="http://sandbox-x:3000"),
        ),
        patch.object(webapp_proxy, "_get_proxy_client", return_value=client),
    ):
        return asyncio.run(webapp_proxy._proxy_request("", request, uuid4()))


def _assert_sandboxed(response: Response) -> None:
    csp = response.headers["content-security-policy"]
    directives = {
        directive.split(" ", 1)[0]: directive.split(" ", 1)[1]
        for directive in csp.split("; ")
    }
    sandbox_flags = set(directives["sandbox"].split(" "))
    assert "allow-same-origin" not in sandbox_flags
    assert {"allow-scripts", "allow-forms", "allow-popups"} <= sandbox_flags
    assert directives["frame-ancestors"] == "'self'"
    assert response.headers["x-content-type-options"] == "nosniff"


def test_proxy_strips_set_cookie_keeps_other_headers() -> None:
    upstream = _make_upstream()
    upstream.headers = httpx.Headers(
        {
            "content-type": "text/html",
            "set-cookie": "sid=leak; Path=/",
            "x-upstream": "kept",
        }
    )

    client = MagicMock()
    client.build_request = MagicMock()
    client.send = AsyncMock(return_value=upstream)

    response = _run_proxy_request(_make_request(), client)

    header_names = {name.lower() for name in response.headers}
    assert "set-cookie" not in header_names
    assert response.headers.get("x-upstream") == "kept"


def test_proxy_strips_browser_context_request_headers() -> None:
    """Origin/sec-fetch-* must not reach the sandbox dev server — Next dev
    blocks /_next/* requests whose Origin isn't allowlisted."""
    client = MagicMock()
    client.build_request = MagicMock()
    client.send = AsyncMock(return_value=_make_upstream())

    request = _make_request(
        headers=[
            (b"origin", b"https://cloud.onyx.app"),
            (b"sec-fetch-mode", b"cors"),
            (b"sec-fetch-site", b"same-origin"),
            (b"sec-fetch-dest", b"empty"),
            (b"cookie", b"fastapiusersauth=secret"),
            (b"accept", b"text/html"),
            (b"user-agent", b"test-agent"),
        ]
    )
    _run_proxy_request(request, client)

    forwarded = client.build_request.call_args.kwargs["headers"]
    forwarded_names = {name.lower() for name in forwarded}
    assert "origin" not in forwarded_names
    assert not any(name.startswith("sec-fetch-") for name in forwarded_names)
    assert "cookie" not in forwarded_names
    assert forwarded_names >= {"accept", "user-agent"}


def test_proxy_sandboxes_document_and_drops_upstream_policy_headers() -> None:
    upstream = _make_upstream()
    upstream.headers = httpx.Headers(
        {
            "content-type": "text/html",
            "content-security-policy": "default-src *",
            "service-worker-allowed": "/",
            "x-frame-options": "ALLOWALL",
            "cross-origin-opener-policy": "unsafe-none",
        }
    )
    client = MagicMock()
    client.build_request = MagicMock()
    client.send = AsyncMock(return_value=upstream)

    response = _run_proxy_request(_make_request(), client)

    header_names = {name.lower() for name in response.headers}
    assert "service-worker-allowed" not in header_names
    assert "x-frame-options" not in header_names
    assert "cross-origin-opener-policy" not in header_names
    _assert_sandboxed(response)


def test_offline_response_carries_the_same_policy() -> None:
    response = webapp_proxy._offline_html_response()

    assert response.status_code == 503
    _assert_sandboxed(response)


def test_document_load_issues_viewer_cookie_scoped_to_the_webapp_path() -> None:
    cache = _FakeCache()
    session_id = uuid4()
    user = MagicMock()
    user.id = uuid4()

    with patch.object(webapp_proxy, "get_shared_cache_backend", return_value=cache):
        response = _run_get_webapp(session_id, user, None)
        grant = webapp_proxy._load_viewer_grant(_viewer_token(response), session_id)

    assert response.status_code == 200
    cookie = response.headers["set-cookie"]
    assert cookie.startswith("onyx_craft_webapp=")
    assert f"Path={webapp_proxy.webapp_base_path(session_id)};" in cookie
    assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=none" in cookie
    assert grant is not None and grant.user_id == user.id


def test_viewer_cookie_admits_only_its_own_session() -> None:
    cache = _FakeCache()
    session_id = uuid4()
    user = MagicMock()
    user.id = uuid4()

    with patch.object(webapp_proxy, "get_shared_cache_backend", return_value=cache):
        token = _viewer_token(_run_get_webapp(session_id, user, None))
        admitted = _run_get_webapp(session_id, None, f"onyx_craft_webapp={token}")
        other = _run_get_webapp(uuid4(), None, f"onyx_craft_webapp={token}")
        unknown = _run_get_webapp(session_id, None, "onyx_craft_webapp=nope")

    assert admitted.status_code == 200
    assert "set-cookie" not in admitted.headers  # a grant never renews itself
    assert other.status_code == 302 and other.headers["location"] == "/auth/login"
    assert unknown.status_code == 302


def test_viewer_cookie_rechecks_access_on_every_request() -> None:
    cache = _FakeCache()
    session_id = uuid4()
    user = MagicMock()
    user.id = uuid4()

    with patch.object(webapp_proxy, "get_shared_cache_backend", return_value=cache):
        token = _viewer_token(_run_get_webapp(session_id, user, None))
        with (
            patch.object(
                webapp_proxy,
                "_check_webapp_access",
                AsyncMock(side_effect=OnyxError(OnyxErrorCode.NOT_FOUND)),
            ),
            pytest.raises(OnyxError),
        ):
            _run_get_webapp_raw(session_id, f"onyx_craft_webapp={token}")


def test_deactivated_viewer_is_refused() -> None:
    session_id = uuid4()
    user_id = uuid4()
    cache = _FakeCache()

    class _NoopSession:
        async def __aenter__(self) -> object:
            return object()

        async def __aexit__(self, *args: object) -> None:
            return None

    with (
        patch.object(webapp_proxy, "get_cache_backend", return_value=cache),
        patch.object(
            webapp_proxy, "get_async_session_context_manager", lambda: _NoopSession()
        ),
        patch.object(
            webapp_proxy,
            "get_webapp_access_async",
            AsyncMock(return_value=(SharingScope.PUBLIC_ORG, uuid4())),
        ),
        patch.object(
            webapp_proxy, "is_user_active_async", AsyncMock(return_value=False)
        ),
        pytest.raises(OnyxError) as exc,
    ):
        asyncio.run(webapp_proxy._check_webapp_access(session_id, user_id))

    assert exc.value.error_code == OnyxErrorCode.UNAUTHORIZED
    assert not cache.values
