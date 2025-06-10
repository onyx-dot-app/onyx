import base64
import hashlib
import logging
import uuid
from collections.abc import Awaitable
from collections.abc import Callable
from datetime import datetime
from datetime import timezone

from fastapi import FastAPI
from fastapi import Request
from fastapi import Response

from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR
from shared_configs.contextvars import ONYX_REQUEST_ID_CONTEXTVAR


def add_onyx_tenant_id_middleware(app: FastAPI, logger: logging.LoggerAdapter) -> None:
    @app.middleware("http")
    async def set_tenant_id(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Captures and sets the context var for the tenant."""

        onyx_tenant_id = request.headers.get("X-Onyx-Tenant-ID")
        if onyx_tenant_id:
            CURRENT_TENANT_ID_CONTEXTVAR.set(onyx_tenant_id)
        return await call_next(request)


def add_onyx_request_id_middleware(
    app: FastAPI, prefix: str, logger: logging.LoggerAdapter
) -> None:
    @app.middleware("http")
    async def set_request_id(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Generate a request hash that can be used to track the lifecycle
        of a request.  The hash is prefixed to help indicated where the request id
        originated.

        Format is f"{PREFIX}:{ID}" where PREFIX is 3 chars and ID is 8 chars.
        Total length is 12 chars.
        """

        onyx_request_id = request.headers.get("X-Onyx-Request-ID")
        if not onyx_request_id:
            onyx_request_id = make_randomized_onyx_request_id(prefix)

        ONYX_REQUEST_ID_CONTEXTVAR.set(onyx_request_id)
        return await call_next(request)


def make_randomized_onyx_request_id(prefix: str) -> str:
    """generates a randomized request id"""

    hash_input = str(uuid.uuid4())
    return _make_onyx_request_id(prefix, hash_input)


def make_structured_onyx_request_id(prefix: str, request_url: str) -> str:
    """Not used yet, but could be in the future!"""
    hash_input = f"{request_url}:{datetime.now(timezone.utc)}"
    return _make_onyx_request_id(prefix, hash_input)


def _make_onyx_request_id(prefix: str, hash_input: str) -> str:
    """helper function to return an id given a string input"""
    hash_obj = hashlib.md5(hash_input.encode("utf-8"))
    hash_bytes = hash_obj.digest()[:6]  # Truncate to 6 bytes

    # 6 bytes becomes 8 bytes. we shouldn't need to strip but just in case
    # NOTE: possible we'll want more input bytes if id's aren't unique enough
    hash_str = base64.urlsafe_b64encode(hash_bytes).decode("utf-8").rstrip("=")
    onyx_request_id = f"{prefix}:{hash_str}"
    return onyx_request_id
