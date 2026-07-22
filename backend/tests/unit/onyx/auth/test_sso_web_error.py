"""The SSO web-error decorator turns OnyxError into a readable /auth/error
redirect for browser navigations, while non-browser callers still receive the
JSON error they can parse."""

import enum

import pytest
from fastapi import Request
from fastapi.responses import RedirectResponse

from onyx.auth.sso_web_error import redirect_sso_errors_to_web
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError


def _request_with_accept(accept: str) -> Request:
    return Request(
        {
            "type": "http",
            "headers": [(b"accept", accept.encode())],
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
