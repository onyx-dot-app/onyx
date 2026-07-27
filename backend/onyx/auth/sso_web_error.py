"""Render SSO callback failures for browsers and drop the flow's PKCE cookie.

Non-legacy OIDC provider rows and all SAML callbacks terminate directly in
FastAPI (no Next.js wrapper), so an ``OnyxError`` from those handlers would
reach the browser as raw JSON. This decorator converts it into a redirect to
the ``/auth/error`` page for browser navigations, while non-browser callers
(mobile, API, tests) get the standard JSON error. Either way the flow's
single-use PKCE cookie is deleted with the error response.
"""

import enum
import functools
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any, ParamSpec
from urllib.parse import quote

from fastapi import Request
from fastapi.responses import RedirectResponse
from starlette.responses import Response

from onyx.auth.users import get_pkce_cookie_name
from onyx.configs.app_configs import WEB_DOMAIN
from onyx.error_handling.exceptions import (
    OnyxError,
    log_onyx_error,
    onyx_error_to_json_response,
)

_COOKIE_SECURE = WEB_DOMAIN.startswith("https")


def delete_pkce_cookie(response: Response, state: str) -> None:
    """Path must match the set-cookie or browsers treat the delete as a
    different cookie and keep the original."""
    response.delete_cookie(
        key=get_pkce_cookie_name(state),
        path="/",
        secure=_COOKIE_SECURE,
        httponly=True,
        samesite="lax",
    )


def _delete_flow_pkce_cookie(request: Request, response: Response) -> None:
    state = request.query_params.get("state")
    if state and request.cookies.get(get_pkce_cookie_name(state)) is not None:
        delete_pkce_cookie(response, state)


_P = ParamSpec("_P")


def redirect_sso_errors_to_web(
    handler: Callable[_P, Awaitable[Response]],
) -> Callable[_P, Coroutine[Any, Any, Response]]:
    @functools.wraps(handler)
    async def wrapper(*args: _P.args, **kwargs: _P.kwargs) -> Response:
        try:
            return await handler(*args, **kwargs)
        except OnyxError as error:
            request = kwargs.get("request")
            if not isinstance(request, Request):
                raise
            log_onyx_error(error)
            accept = request.headers.get("accept", "")
            # Only browser navigations get the page. Mobile and API clients keep
            # the JSON error they can parse.
            if "text/html" in accept.lower():
                detail = error.detail
                detail_str = (
                    detail.value if isinstance(detail, enum.Enum) else str(detail)
                )
                response: Response = RedirectResponse(
                    f"{WEB_DOMAIN}/auth/error?error={quote(detail_str)}",
                    status_code=302,
                )
            else:
                response = onyx_error_to_json_response(error)
            _delete_flow_pkce_cookie(request, response)
            return response

    return wrapper
