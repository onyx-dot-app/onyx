"""Utilities for gating endpoints that require a vector database."""

from fastapi import HTTPException
from starlette.status import HTTP_501_NOT_IMPLEMENTED

from onyx.configs.app_configs import DISABLE_VECTOR_DB


def require_vector_db() -> None:
    """FastAPI dependency — raises 501 when the vector DB is disabled."""
    if DISABLE_VECTOR_DB:
        raise HTTPException(
            status_code=HTTP_501_NOT_IMPLEMENTED,
            detail="This feature requires a vector database (DISABLE_VECTOR_DB is set).",
        )
