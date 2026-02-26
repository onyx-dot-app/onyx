"""SCIM-specific exception handlers.

IdPs like Okta and Azure AD/Entra ID expect error responses in the
SCIM error format (RFC 7644 §3.12) with ``Content-Type: application/scim+json``.
Without these handlers, FastAPI's default exception handling returns errors in
its own format (``{"detail": ...}`` for HTTPException, 422 for validation errors)
which IdPs cannot parse, leading to opaque errors in the IdP admin console.

These handlers intercept exceptions for ``/scim/v2/`` routes and return
SCIM-compliant JSON while preserving default behavior for all other routes.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi import Request
from fastapi.exception_handlers import (
    http_exception_handler as _default_http_handler,
)
from fastapi.exception_handlers import (
    request_validation_exception_handler as _default_validation_handler,
)
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from ee.onyx.server.scim.models import ScimError
from onyx.utils.logger import setup_logger

logger = setup_logger()

_SCIM_PREFIX = "/scim/v2/"


def _is_scim_request(request: Request) -> bool:
    return request.url.path.startswith(_SCIM_PREFIX)


def _build_scim_error_response(
    status_code: int,
    detail: str,
) -> dict:
    """Build a SCIM error body dict."""
    return ScimError(
        status=str(status_code),
        detail=detail,
    ).model_dump(exclude_none=True)


def register_scim_error_handlers(app: FastAPI) -> None:
    """Register exception handlers that return SCIM-formatted errors.

    For requests to ``/scim/v2/*``, exceptions are converted to RFC 7644
    §3.12 error responses. All other routes use FastAPI's default handlers.
    """
    # Import here to avoid circular imports at module level
    from ee.onyx.server.scim.api import ScimJSONResponse

    @app.exception_handler(StarletteHTTPException)
    async def scim_http_exception_handler(
        request: Request,
        exc: StarletteHTTPException,
    ) -> ScimJSONResponse:
        if not _is_scim_request(request):
            return await _default_http_handler(request, exc)  # type: ignore[return-value]

        detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
        return ScimJSONResponse(
            status_code=exc.status_code,
            content=_build_scim_error_response(exc.status_code, detail),
        )

    @app.exception_handler(RequestValidationError)
    async def scim_validation_error_handler(
        request: Request,
        exc: RequestValidationError,
    ) -> ScimJSONResponse:
        if not _is_scim_request(request):
            return await _default_validation_handler(request, exc)  # type: ignore[return-value]

        # Flatten Pydantic validation errors into a single human-readable string.
        parts: list[str] = []
        for err in exc.errors():
            loc = ".".join(str(segment) for segment in err.get("loc", []))
            msg = err.get("msg", "validation error")
            parts.append(f"{loc}: {msg}" if loc else msg)
        detail = "; ".join(parts) or "Invalid request body"

        return ScimJSONResponse(
            status_code=400,
            content=_build_scim_error_response(400, detail),
        )

    @app.exception_handler(Exception)
    async def scim_generic_exception_handler(
        request: Request,
        exc: Exception,
    ) -> ScimJSONResponse:
        if not _is_scim_request(request):
            # Re-raise so FastAPI's default 500 handler picks it up
            raise exc

        logger.exception(
            "Unhandled exception in SCIM endpoint %s %s",
            request.method,
            request.url.path,
        )
        return ScimJSONResponse(
            status_code=500,
            content=_build_scim_error_response(500, "Internal server error"),
        )
