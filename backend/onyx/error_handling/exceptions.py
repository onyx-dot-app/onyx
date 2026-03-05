"""OnyxError — the single exception type for all Onyx business errors.

Raise ``OnyxError`` instead of ``HTTPException`` in business code.  A global
FastAPI exception handler (registered via ``register_onyx_exception_handlers``)
converts it into a JSON response with the standard
``{"error_code": "...", "message": "..."}`` shape.

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

from fastapi import FastAPI
from fastapi import Request
from fastapi.responses import JSONResponse

from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.utils.logger import setup_logger

logger = setup_logger()


class OnyxError(Exception):
    """Structured error that maps to a specific ``OnyxErrorCode``.

    Attributes:
        error_code: The ``OnyxErrorCode`` enum member.
        message: Human-readable message (defaults to the error code string).
        status_code: HTTP status — either overridden or from the error code.
    """

    def __init__(
        self,
        error_code: OnyxErrorCode,
        message: str | None = None,
        *,
        status_code_override: int | None = None,
    ) -> None:
        resolved_message = message or error_code.code
        super().__init__(resolved_message)
        self.error_code = error_code
        self.message = resolved_message
        self._status_code_override = status_code_override
        self._status_code_override = status_code_override

    @property
    def status_code(self) -> int:
        return self._status_code_override or self.error_code.status_code


def register_onyx_exception_handlers(app: FastAPI) -> None:
    """Register a global handler that converts ``OnyxError`` to JSON responses.

    Must be called *after* the app is created but *before* it starts serving.
    The handler logs at WARNING for 4xx and ERROR for 5xx.
    """

    @app.exception_handler(OnyxError)
    async def _handle_onyx_error(
        request: Request,  # noqa: ARG001
        exc: OnyxError,
    ) -> JSONResponse:
        status_code = exc.status_code
        if status_code >= 500:
            logger.error(f"OnyxError {exc.error_code.code}: {exc.message}")
        elif status_code >= 400:
            logger.warning(f"OnyxError {exc.error_code.code}: {exc.message}")

        return JSONResponse(
            status_code=status_code,
            content=exc.error_code.detail(exc.message),
        )
