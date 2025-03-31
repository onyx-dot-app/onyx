import base64
import hashlib
import logging
from collections.abc import Awaitable
from collections.abc import Callable
from datetime import datetime
from datetime import timezone

from fastapi import FastAPI
from fastapi import Request
from fastapi import Response

from shared_configs.contextvars import ONYX_REQUEST_ID_CONTEXTVAR


def add_fastapi_request_id_middleware(
    app: FastAPI, prefix: str, logger: logging.LoggerAdapter
) -> None:
    @app.middleware("http")
    async def set_request_id(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Generate a request hash that can be used to track the lifecycle
        of a request.  The hash is prefixed with API: to indicate it started at the API
        server.

        Format is f"{PREFIX}:{ID}" where PREFIX is 3 chars and ID is 8 chars.
        Total length is 12 chars.
        """

        onyx_request_id = request.headers.get("X-Onyx-Request-ID")
        if not onyx_request_id:
            hash_input = f"{request.url}:{datetime.now(timezone.utc)}"
            hash_obj = hashlib.md5(hash_input.encode("utf-8"))
            hash_bytes = hash_obj.digest()[:6]  # Truncate to 6 bytes (64 bits)

            # 6 bytes becomes 8 bytes. we shouldn't need to strip but just in case
            hash_str = base64.urlsafe_b64encode(hash_bytes).decode("utf-8").rstrip("=")
            onyx_request_id = f"{prefix}:{hash_str}"

        ONYX_REQUEST_ID_CONTEXTVAR.set(onyx_request_id)
        return await call_next(request)
