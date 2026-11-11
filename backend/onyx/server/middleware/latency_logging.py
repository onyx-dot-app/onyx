import logging
import time

from fastapi import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send


def latency_logging_middleware(
    app: ASGIApp, *, logger: logging.LoggerAdapter
) -> ASGIApp:
    async def log_latency(scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await app(scope, receive, send)
            return

        start_time = time.monotonic()

        async def send_response(message: Message) -> None:
            if message["type"] == "http.response.start":
                request = Request(scope)
                process_time = time.monotonic() - start_time
                logger.debug(
                    "Path: %s - Method: %s - Status Code: %s - Time: %s secs",
                    request.url.path,
                    request.method,
                    message["status"],
                    format(process_time, ".4f"),
                )
            await send(message)

        await app(scope, receive, send_response)

    return log_latency
