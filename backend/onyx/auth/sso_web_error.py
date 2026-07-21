"""Render SSO callback failures as a readable page for browsers.

Non-legacy OIDC provider rows and all SAML callbacks terminate directly in
FastAPI (no Next.js wrapper), so an ``OnyxError`` from those handlers would
reach the browser as raw JSON. This decorator converts it into a redirect to
the ``/auth/error`` page for browser navigations, while non-browser callers
(mobile, API, tests) still get the JSON error via content negotiation.
"""

import enum
import functools
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import quote

from fastapi import Request
from fastapi.responses import RedirectResponse
from starlette.responses import Response

from onyx.configs.app_configs import WEB_DOMAIN
from onyx.error_handling.exceptions import OnyxError


def redirect_sso_errors_to_web(
    handler: Callable[..., Awaitable[Response]],
) -> Callable[..., Awaitable[Response]]:
    @functools.wraps(handler)
    async def wrapper(*args: Any, **kwargs: Any) -> Response:
        try:
            return await handler(*args, **kwargs)
        except OnyxError as error:
            request = kwargs.get("request")
            accept = (
                request.headers.get("accept", "")
                if isinstance(request, Request)
                else ""
            )
            # Only browser navigations get the page. Mobile and API clients keep
            # the JSON error they can parse.
            if "text/html" not in accept.lower():
                raise
            detail = error.detail
            detail_str = detail.value if isinstance(detail, enum.Enum) else str(detail)
            return RedirectResponse(
                f"{WEB_DOMAIN}/auth/error?error={quote(detail_str)}",
                status_code=302,
            )

    return wrapper
