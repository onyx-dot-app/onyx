"""The SSO web-error decorator turns OnyxError into a readable /auth/error
redirect for browser navigations, while non-browser callers still receive the
JSON error they can parse."""

import enum
from typing import Any, cast

import pytest
from fastapi import Request
from fastapi.responses import RedirectResponse

from onyx.auth.sso_web_error import redirect_sso_errors_to_web
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError


def _request_with_accept(accept: str) -> Request:
    # query_string is always present on real ASGI scopes.
    return Request(
        {
            "type": "http",
            "headers": [(b"accept", accept.encode())],
            "query_string": b"",
        }
    )


@redirect_sso_errors_to_web
async def _handler(*, request: Request, raise_error: bool) -> RedirectResponse:  # noqa: ARG001
    if raise_error:
        raise OnyxError(OnyxErrorCode.UNAUTHORIZED, "invite only")
    return RedirectResponse("/ok", status_code=302)


@pytest.mark.asyncio
async def test_browser_gets_redirect_to_auth_error() -> None:
    resp = await _handler(
        request=_request_with_accept("text/html,application/xhtml+xml"),
        raise_error=True,
    )
    assert isinstance(resp, RedirectResponse)
    assert resp.status_code == 302
    assert "/auth/error?error=" in resp.headers["location"]
    assert "invite" in resp.headers["location"]


@pytest.mark.asyncio
async def test_non_browser_still_raises_for_json() -> None:
    with pytest.raises(OnyxError):
        await _handler(
            request=_request_with_accept("application/json"),
            raise_error=True,
        )


@pytest.mark.asyncio
async def test_success_passes_through_untouched() -> None:
    resp = await _handler(
        request=_request_with_accept("text/html"),
        raise_error=False,
    )
    assert resp.headers["location"] == "/ok"


@pytest.mark.asyncio
async def test_enum_detail_uses_value_in_url() -> None:
    class _Code(str, enum.Enum):
        SAMPLE = "SAMPLE_CODE"

    @redirect_sso_errors_to_web
    async def _enum_handler(*, request: Request) -> RedirectResponse:  # noqa: ARG001
        raise OnyxError(OnyxErrorCode.VALIDATION_ERROR, _Code.SAMPLE)

    resp = await _enum_handler(request=_request_with_accept("text/html"))
    assert isinstance(resp, RedirectResponse)
    assert "error=SAMPLE_CODE" in resp.headers["location"]


def _browser_request_with_marked_cookie(cookie_name: str) -> Request:
    from onyx.error_handling.exceptions import CLEANUP_COOKIE_STATE_ATTR

    request = Request(
        {
            "type": "http",
            "headers": [
                (b"accept", b"text/html"),
                (b"cookie", f"{cookie_name}=verifier".encode()),
            ],
            "query_string": b"",
        }
    )
    setattr(request.state, CLEANUP_COOKIE_STATE_ATTR, cookie_name)
    return request


@pytest.mark.asyncio
async def test_error_redirect_clears_marked_cookie() -> None:
    resp = await _handler(
        request=_browser_request_with_marked_cookie("onyx_pkce_abc123"),
        raise_error=True,
    )
    set_cookie = resp.headers.get("set-cookie", "")
    assert "onyx_pkce_abc123" in set_cookie
    assert "Max-Age=0" in set_cookie or "expires" in set_cookie.lower()


@pytest.mark.asyncio
async def test_error_redirect_without_pkce_cookie_sets_nothing() -> None:
    resp = await _handler(
        request=_request_with_accept("text/html"),
        raise_error=True,
    )
    assert "set-cookie" not in resp.headers


@pytest.mark.asyncio
async def test_onyx_error_json_handler_clears_marked_cookie() -> None:
    # JSON clients get the cleanup from the global handler, not the decorator.
    from fastapi import FastAPI

    from onyx.error_handling.error_codes import OnyxErrorCode
    from onyx.error_handling.exceptions import register_onyx_exception_handlers

    app = FastAPI()
    register_onyx_exception_handlers(app)
    handler = cast(Any, app.exception_handlers[OnyxError])

    request = _browser_request_with_marked_cookie("onyx_pkce_json")
    resp = await handler(request, OnyxError(OnyxErrorCode.UNAUTHORIZED, "nope"))
    set_cookie = resp.headers.get("set-cookie", "")
    assert "onyx_pkce_json" in set_cookie


@pytest.mark.asyncio
async def test_unhandled_error_handler_clears_marked_cookie() -> None:
    from fastapi import FastAPI

    from onyx.error_handling.exceptions import register_onyx_exception_handlers

    app = FastAPI()
    register_onyx_exception_handlers(app)
    handler = cast(Any, app.exception_handlers[Exception])

    request = _browser_request_with_marked_cookie("onyx_pkce_boom")
    resp = await handler(request, RuntimeError("boom"))
    assert resp.status_code == 500
    set_cookie = resp.headers.get("set-cookie", "")
    assert "onyx_pkce_boom" in set_cookie
