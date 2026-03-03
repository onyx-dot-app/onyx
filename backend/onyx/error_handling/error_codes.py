"""
Standardized error codes for the Onyx backend.

Usage:
    from onyx.error_handling.error_codes import OnyxErrorCode

    raise HTTPException(
        status_code=OnyxErrorCode.UNAUTHENTICATED.status_code,
        detail=OnyxErrorCode.UNAUTHENTICATED.detail("Token expired"),
    )
"""

from enum import Enum


class OnyxErrorCode(Enum):
    """
    Each member is a tuple of (error_code_string, http_status_code).

    The error_code_string is a stable, machine-readable identifier that
    API consumers can match on. The http_status_code is the default HTTP
    status to return.
    """

    # ------------------------------------------------------------------
    # Authentication (401)
    # ------------------------------------------------------------------
    UNAUTHENTICATED = ("UNAUTHENTICATED", 401)
    INVALID_TOKEN = ("INVALID_TOKEN", 401)
    TOKEN_EXPIRED = ("TOKEN_EXPIRED", 401)
    CSRF_FAILURE = ("CSRF_FAILURE", 403)

    # ------------------------------------------------------------------
    # Authorization (403)
    # ------------------------------------------------------------------
    UNAUTHORIZED = ("UNAUTHORIZED", 403)
    INSUFFICIENT_PERMISSIONS = ("INSUFFICIENT_PERMISSIONS", 403)
    ADMIN_ONLY = ("ADMIN_ONLY", 403)
    EE_REQUIRED = ("EE_REQUIRED", 403)

    # ------------------------------------------------------------------
    # Validation / Bad Request (400)
    # ------------------------------------------------------------------
    VALIDATION_ERROR = ("VALIDATION_ERROR", 400)
    INVALID_INPUT = ("INVALID_INPUT", 400)
    MISSING_REQUIRED_FIELD = ("MISSING_REQUIRED_FIELD", 400)

    # ------------------------------------------------------------------
    # Not Found (404)
    # ------------------------------------------------------------------
    NOT_FOUND = ("NOT_FOUND", 404)
    CONNECTOR_NOT_FOUND = ("CONNECTOR_NOT_FOUND", 404)
    CREDENTIAL_NOT_FOUND = ("CREDENTIAL_NOT_FOUND", 404)
    PERSONA_NOT_FOUND = ("PERSONA_NOT_FOUND", 404)
    DOCUMENT_NOT_FOUND = ("DOCUMENT_NOT_FOUND", 404)
    SESSION_NOT_FOUND = ("SESSION_NOT_FOUND", 404)
    USER_NOT_FOUND = ("USER_NOT_FOUND", 404)

    # ------------------------------------------------------------------
    # Conflict (409)
    # ------------------------------------------------------------------
    CONFLICT = ("CONFLICT", 409)
    DUPLICATE_RESOURCE = ("DUPLICATE_RESOURCE", 409)

    # ------------------------------------------------------------------
    # Rate Limiting / Quotas (429 / 402)
    # ------------------------------------------------------------------
    RATE_LIMITED = ("RATE_LIMITED", 429)
    SEAT_LIMIT_EXCEEDED = ("SEAT_LIMIT_EXCEEDED", 402)

    # ------------------------------------------------------------------
    # Connector / Credential Errors (400-range)
    # ------------------------------------------------------------------
    CONNECTOR_VALIDATION_FAILED = ("CONNECTOR_VALIDATION_FAILED", 400)
    CREDENTIAL_INVALID = ("CREDENTIAL_INVALID", 400)
    CREDENTIAL_EXPIRED = ("CREDENTIAL_EXPIRED", 400)

    # ------------------------------------------------------------------
    # Server Errors (5xx)
    # ------------------------------------------------------------------
    INTERNAL_ERROR = ("INTERNAL_ERROR", 500)
    NOT_IMPLEMENTED = ("NOT_IMPLEMENTED", 501)
    SERVICE_UNAVAILABLE = ("SERVICE_UNAVAILABLE", 503)
    BAD_GATEWAY = ("BAD_GATEWAY", 502)
    LLM_PROVIDER_ERROR = ("LLM_PROVIDER_ERROR", 502)
    GATEWAY_TIMEOUT = ("GATEWAY_TIMEOUT", 504)

    def __init__(self, code: str, status_code: int) -> None:
        self.code = code
        self.status_code = status_code

    def detail(self, message: str | None = None) -> dict[str, str]:
        """Build a structured error detail dict.

        Returns a dict like:
            {"error_code": "UNAUTHENTICATED", "message": "Token expired"}

        If no message is supplied, the error code itself is used as the message.
        """
        return {
            "error_code": self.code,
            "message": message or self.code,
        }
