"""Utilities for gating endpoints that require a vector database."""

from onyx.configs.app_configs import DISABLE_VECTOR_DB
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError


def require_vector_db() -> None:
    """FastAPI dependency — raises 501 when the vector DB is disabled."""
    if DISABLE_VECTOR_DB:
        raise OnyxError(
            OnyxErrorCode.NOT_IMPLEMENTED,
            "This feature requires a vector database (DISABLE_VECTOR_DB is set).",
        )
