"""The SSO web-error decorator turns OnyxError into a readable /auth/error
redirect for browser navigations, serves the standard JSON error to other
callers, and deletes the flow's single-use PKCE cookie either way."""

import enum
import json
from typing import Any

import pytest
from fastapi import Request
from fastapi.responses import RedirectResponse

from onyx.auth.sso_web_error import redirect_sso_errors_to_web
from onyx.auth.users import get_pkce_cookie_name
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError


def _request(
    accept: str, query_string: bytes = b"", cookie: str | None = None
) -> Request:
    headers = [(b"accept", accept.encode())]
    if cookie:
        headers.append((b"cookie", cookie.encode()))
    # query_string is always present on real ASGI scopes.
    return Request({"type": "http", "headers": headers, "query_string": query_string})


def _request_with_pkce_cookie(accept: str, state: str) -> Request:
    return Request(
        {
            "type": "http",
            "headers": [
                (b"accept", accept.encode()),
                (b"cookie", f"{get_pkce_cookie_name(state)}=verifier".encode()),
            ],
            "query_string": f"state={state}".encode(),
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
        request=_request("text/html,application/xhtml+xml"),
        raise_error=True,
    )
    assert isinstance(resp, RedirectResponse)
    assert resp.status_code == 302
    assert "/auth/error?error=" in resp.headers["location"]
    assert "invite" in resp.headers["location"]


@pytest.mark.asyncio
async def test_non_browser_gets_standard_json_error() -> None:
    resp = await _handler(request=_request("application/json"), raise_error=True)
    assert resp.status_code == OnyxErrorCode.UNAUTHORIZED.status_code
    body = json.loads(bytes(resp.body))
    assert body["error_code"] == OnyxErrorCode.UNAUTHORIZED.code
    assert body["detail"] == "invite only"


@pytest.mark.asyncio
async def test_no_request_kwarg_reraises() -> None:
    @redirect_sso_errors_to_web
    async def _no_request_handler(**_: Any) -> RedirectResponse:
        raise OnyxError(OnyxErrorCode.UNAUTHORIZED, "nope")

    with pytest.raises(OnyxError):
        await _no_request_handler()


@pytest.mark.asyncio
async def test_success_passes_through_untouched() -> None:
    resp = await _handler(request=_request("text/html"), raise_error=False)
    assert resp.headers["location"] == "/ok"


@pytest.mark.asyncio
async def test_enum_detail_uses_value_in_url() -> None:
    class _Code(str, enum.Enum):
        SAMPLE = "SAMPLE_CODE"

    @redirect_sso_errors_to_web
    async def _enum_handler(*, request: Request) -> RedirectResponse:  # noqa: ARG001
        raise OnyxError(OnyxErrorCode.VALIDATION_ERROR, _Code.SAMPLE)

    resp = await _enum_handler(request=_request("text/html"))
    assert isinstance(resp, RedirectResponse)
    assert "error=SAMPLE_CODE" in resp.headers["location"]


@pytest.mark.asyncio
async def test_error_redirect_deletes_flow_pkce_cookie() -> None:
    resp = await _handler(
        request=_request_with_pkce_cookie("text/html", "abc123"),
        raise_error=True,
    )
    set_cookie = resp.headers.get("set-cookie", "")
    assert get_pkce_cookie_name("abc123") in set_cookie
    assert "Max-Age=0" in set_cookie or "expires" in set_cookie.lower()


@pytest.mark.asyncio
async def test_json_error_deletes_flow_pkce_cookie() -> None:
    resp = await _handler(
        request=_request_with_pkce_cookie("application/json", "xyz789"),
        raise_error=True,
    )
    set_cookie = resp.headers.get("set-cookie", "")
    assert get_pkce_cookie_name("xyz789") in set_cookie


@pytest.mark.asyncio
async def test_error_without_state_sets_no_cookie() -> None:
    resp = await _handler(request=_request("text/html"), raise_error=True)
    assert "set-cookie" not in resp.headers


@pytest.mark.asyncio
async def test_error_with_state_but_no_cookie_sets_nothing() -> None:
    resp = await _handler(
        request=_request("text/html", query_string=b"state=lonely"),
        raise_error=True,
    )
    assert "set-cookie" not in resp.headers
