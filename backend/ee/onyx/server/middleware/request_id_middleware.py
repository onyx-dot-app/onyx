import logging
from collections.abc import Awaitable
from collections.abc import Callable

from fastapi import FastAPI
from fastapi import Request
from fastapi import Response

from shared_configs.contextvars import REQUEST_ID_CONTEXTVAR


def add_request_id_middleware(app: FastAPI, logger: logging.LoggerAdapter) -> None:
    @app.middleware("http")
    async def set_request_id(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        REQUEST_ID_CONTEXTVAR.set("")
