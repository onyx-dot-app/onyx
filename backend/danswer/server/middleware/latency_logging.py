import logging
import time
from collections.abc import Awaitable
from collections.abc import Callable

from fastapi import FastAPI
from fastapi import Request
from fastapi import Response


def add_latency_logging_middleware(app: FastAPI, logger: logging.LoggerAdapter) -> None:
    @app.middleware("http")
    async def log_latency(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        start_time = time.monotonic()
        response = await call_next(request)
        process_time = time.monotonic() - start_time
        logger.debug(
            f"Path: {request.url.path} - Method: {request.method} - "
            f"Status Code: {response.status_code} - Time: {process_time:.4f} secs"
        )
        return response
