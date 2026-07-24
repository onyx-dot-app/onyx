"""OnyxError — the single exception type for all Onyx business errors.

Raise ``OnyxError`` instead of ``HTTPException`` in business code.  A global
FastAPI exception handler (registered via ``register_onyx_exception_handlers``)
converts it into a JSON response with the standard
``{"error_code": "...", "detail": "..."}`` shape.

Usage::

    from onyx.error_handling.error_codes import OnyxErrorCode
    from onyx.error_handling.exceptions import OnyxError

    raise OnyxError(OnyxErrorCode.NOT_FOUND, "Session not found")

For upstream errors with a dynamic HTTP status (e.g. billing service),
use ``status_code_override``::

    raise OnyxError(
        OnyxErrorCode.BAD_GATEWAY,
        detail,
        status_code_override=upstream_status,
    )
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse, Response

from onyx.configs.app_configs import WEB_DOMAIN
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Routes that set a single-use cookie (e.g. the OIDC PKCE verifier) mark the
# request with the cookie's name so any error response, whichever handler
# builds it, deletes the cookie instead of leaving it until expiry. The marker
# carries the computed name, keeping auth knowledge out of this module.
CLEANUP_COOKIE_STATE_ATTR = "onyx_cleanup_cookie_name"

_COOKIE_SECURE = WEB_DOMAIN.startswith("https")


def clear_marked_cookie(request: Request, response: Response) -> None:
    """Delete the request's marked single-use cookie on an error response.
    Path must match the set-cookie or browsers treat it as a different
    cookie and keep the original."""
    cookie_name = getattr(request.state, CLEANUP_COOKIE_STATE_ATTR, None)
    if not cookie_name or request.cookies.get(cookie_name) is None:
        return
    response.delete_cookie(
        key=cookie_name,
        path="/",
        secure=_COOKIE_SECURE,
        httponly=True,
        samesite="lax",
    )


class OnyxError(Exception):
    """Structured error that maps to a specific ``OnyxErrorCode``.

    Attributes:
        error_code: The ``OnyxErrorCode`` enum member.
        detail: Human-readable detail (defaults to the error code string).
        status_code: HTTP status — either overridden or from the error code.
    """

    def __init__(
        self,
        error_code: OnyxErrorCode,
        detail: str | None = None,
        *,
        status_code_override: int | None = None,
        extra: dict[str, object] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        resolved_detail = detail or error_code.code
        super().__init__(resolved_detail)
        self.error_code = error_code
        self.detail = resolved_detail
        self._status_code_override = status_code_override
        # extra: machine-readable fields merged into the JSON body (e.g. reset_at).
        # headers: response headers the FE/clients need (e.g. Retry-After).
        self.extra = extra
        self.headers = headers

    @property
    def status_code(self) -> int:
        return self._status_code_override or self.error_code.status_code


def log_onyx_error(exc: OnyxError) -> None:
    detail = exc.detail
    status_code = exc.status_code
    if status_code >= 500:
        logger.error("OnyxError %s: %s", exc.error_code.code, detail)
    elif status_code >= 400:
        logger.warning("OnyxError %s: %s", exc.error_code.code, detail)


def onyx_error_to_json_response(exc: OnyxError) -> JSONResponse:
    content = exc.error_code.detail(exc.detail)
    if exc.extra:
        # extra first so the canonical error_code/detail can't be overwritten.
        content = {**exc.extra, **content}
    return JSONResponse(
        status_code=exc.status_code,
        content=content,
        headers=exc.headers,
    )


def register_onyx_exception_handlers(app: FastAPI) -> None:
    """Register a global handler that converts ``OnyxError`` to JSON responses.

    Must be called *after* the app is created but *before* it starts serving.
    The handler logs at WARNING for 4xx and ERROR for 5xx.
    """

    @app.exception_handler(OnyxError)
    async def _handle_onyx_error(
        request: Request,
        exc: OnyxError,
    ) -> JSONResponse:
        log_onyx_error(exc)
        response = onyx_error_to_json_response(exc)
        clear_marked_cookie(request, response)
        return response

    # Starlette re-raises the exception after this response is sent, so
    # logging and error tracking still see unhandled errors. The plain 500
    # matches the default ServerErrorMiddleware body.
    @app.exception_handler(Exception)
    async def _handle_unhandled_error(
        request: Request,
        exc: Exception,  # noqa: ARG001
    ) -> Response:
        response = PlainTextResponse("Internal Server Error", status_code=500)
        clear_marked_cookie(request, response)
        return response
