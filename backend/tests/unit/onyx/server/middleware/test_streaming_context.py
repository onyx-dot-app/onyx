import asyncio
import logging
import re
from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from starlette.background import BackgroundTask
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import StreamingResponse
from starlette.types import Message, Scope

from onyx.server.middleware.latency_logging import latency_logging_middleware
from onyx.utils.middleware import (
    add_endpoint_context_middleware,
    request_id_middleware,
    tenant_header_middleware,
)
from shared_configs.contextvars import (
    CURRENT_ENDPOINT_CONTEXTVAR,
    CURRENT_TENANT_ID_CONTEXTVAR,
    ONYX_REQUEST_ID_CONTEXTVAR,
)

logger = logging.LoggerAdapter(logging.getLogger(__name__), {})


def _add_context(app: FastAPI) -> None:
    app.add_middleware(request_id_middleware, prefix="API")
    add_endpoint_context_middleware(app)


async def _request(
    app: FastAPI,
    path: str,
    request_id: str | None = None,
    tenant_id: str | None = None,
    spec_version: str = "2.4",
) -> list[Message]:
    scope: Scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": spec_version},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "root_path": "",
        "query_string": b"",
        "headers": (
            [(b"x-onyx-request-id", request_id.encode())] if request_id else []
        ),
        "client": ("127.0.0.1", 1234),
        "server": ("test", 80),
    }
    if tenant_id:
        scope["headers"].append((b"x-onyx-tenant-id", tenant_id.encode()))
    messages: list[Message] = []

    async def receive() -> Message:
        await asyncio.Event().wait()
        return {"type": "http.disconnect"}

    async def send(message: Message) -> None:
        messages.append(message)

    await app(scope, receive, send)
    return messages


@pytest.mark.asyncio
@pytest.mark.parametrize("spec_version", ["2.3", "2.4"])
async def test_concurrent_streams_keep_context_until_background_completion(
    spec_version: str,
) -> None:
    app = FastAPI()
    arrivals = 0
    both_streams_started = asyncio.Event()
    observations: list[tuple[str, str | None, str | None]] = []

    def observe(stage: str) -> None:
        observations.append(
            (stage, ONYX_REQUEST_ID_CONTEXTVAR.get(), CURRENT_ENDPOINT_CONTEXTVAR.get())
        )

    @app.get("/first/{item}")
    @app.get("/second/{item}")
    async def endpoint(item: str) -> StreamingResponse:
        async def body() -> AsyncIterator[bytes]:
            nonlocal arrivals
            arrivals += 1
            if arrivals == 2:
                both_streams_started.set()
            await both_streams_started.wait()
            observe("first")
            yield item.encode()
            await asyncio.sleep(0)
            observe("last")
            yield b"done"

        async def background() -> None:
            observe("background")

        return StreamingResponse(body(), background=BackgroundTask(background))

    _add_context(app)
    assert all(
        not isinstance(middleware.cls, type)
        or not issubclass(middleware.cls, BaseHTTPMiddleware)
        for middleware in app.user_middleware
    )
    request_token = ONYX_REQUEST_ID_CONTEXTVAR.set("parent-request")
    endpoint_token = CURRENT_ENDPOINT_CONTEXTVAR.set("parent-endpoint")
    try:

        async def run(path: str, request_id: str) -> list[Message]:
            result = await _request(app, path, request_id, spec_version=spec_version)
            assert ONYX_REQUEST_ID_CONTEXTVAR.get() == "parent-request"
            assert CURRENT_ENDPOINT_CONTEXTVAR.get() == "parent-endpoint"
            return result

        results = await asyncio.wait_for(
            asyncio.gather(run("/first/1", "first-id"), run("/second/2", "second-id")),
            timeout=5,
        )
        assert set(observations) == {
            (stage, request_id, route)
            for stage in ("first", "last", "background")
            for request_id, route in (
                ("first-id", "/first/{item}"),
                ("second-id", "/second/{item}"),
            )
        }
        for result, item in zip(results, (b"1", b"2"), strict=True):
            assert (
                b"".join(message.get("body", b"") for message in result)
                == item + b"done"
            )
    finally:
        CURRENT_ENDPOINT_CONTEXTVAR.reset(endpoint_token)
        ONYX_REQUEST_ID_CONTEXTVAR.reset(request_token)


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_context_is_restored_after_stream_error_or_cancellation(
    cancel: bool,
) -> None:
    app = FastAPI()

    @app.get("/stream")
    async def endpoint() -> StreamingResponse:
        async def body() -> AsyncIterator[bytes]:
            yield b"first"
            assert ONYX_REQUEST_ID_CONTEXTVAR.get() == "stream-id"
            assert CURRENT_ENDPOINT_CONTEXTVAR.get() == "/stream"
            if cancel:
                raise asyncio.CancelledError
            raise RuntimeError("stream failed")

        return StreamingResponse(body())

    _add_context(app)
    request_token = ONYX_REQUEST_ID_CONTEXTVAR.set("parent-request")
    endpoint_token = CURRENT_ENDPOINT_CONTEXTVAR.set("parent-endpoint")
    try:
        with pytest.raises(asyncio.CancelledError if cancel else RuntimeError):
            await _request(app, "/stream", "stream-id")
        assert ONYX_REQUEST_ID_CONTEXTVAR.get() == "parent-request"
        assert CURRENT_ENDPOINT_CONTEXTVAR.get() == "parent-endpoint"
    finally:
        CURRENT_ENDPOINT_CONTEXTVAR.reset(endpoint_token)
        ONYX_REQUEST_ID_CONTEXTVAR.reset(request_token)


@pytest.mark.asyncio
async def test_request_id_generation_and_unmatched_endpoint_context() -> None:
    app = FastAPI()
    observed: list[tuple[str | None, str | None]] = []

    @app.exception_handler(404)
    async def missing_route(*_: object) -> StreamingResponse:
        async def body() -> AsyncIterator[bytes]:
            observed.append(
                (ONYX_REQUEST_ID_CONTEXTVAR.get(), CURRENT_ENDPOINT_CONTEXTVAR.get())
            )
            yield b"missing"

        return StreamingResponse(body(), status_code=404)

    _add_context(app)
    for _ in range(2):
        await _request(app, "/missing")
    ids = [request_id for request_id, _ in observed]
    assert len(set(ids)) == 2
    assert all(
        request_id and re.fullmatch(r"API:[A-Za-z0-9_-]{8}", request_id)
        for request_id in ids
    )
    assert all(endpoint == "unmatched" for _, endpoint in observed)


@pytest.mark.asyncio
async def test_latency_logging_occurs_before_stream_body(
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = FastAPI()

    @app.get("/stream")
    async def endpoint() -> StreamingResponse:
        async def body() -> AsyncIterator[bytes]:
            assert len(caplog.records) == 1
            assert "Path: /stream" in caplog.records[0].message
            assert "Status Code: 200" in caplog.records[0].message
            yield b"first"
            await asyncio.sleep(0)
            yield b"last"

        return StreamingResponse(body())

    app.add_middleware(latency_logging_middleware, logger=logger)
    assert all(
        not isinstance(middleware.cls, type)
        or not issubclass(middleware.cls, BaseHTTPMiddleware)
        for middleware in app.user_middleware
    )
    with caplog.at_level(logging.DEBUG, logger=__name__):
        messages = await _request(app, "/stream")
    assert len(caplog.records) == 1
    assert b"".join(message.get("body", b"") for message in messages) == b"firstlast"


@pytest.mark.asyncio
@pytest.mark.parametrize("tenant_id", [None, "requested-tenant"])
async def test_tenant_header_context_lasts_through_stream_and_restores(
    tenant_id: str | None,
) -> None:
    app = FastAPI()
    observed: list[str | None] = []

    @app.get("/stream")
    async def endpoint() -> StreamingResponse:
        async def body() -> AsyncIterator[bytes]:
            observed.append(CURRENT_TENANT_ID_CONTEXTVAR.get())
            yield b"first"
            await asyncio.sleep(0)
            observed.append(CURRENT_TENANT_ID_CONTEXTVAR.get())
            yield b"last"

        return StreamingResponse(body())

    app.add_middleware(tenant_header_middleware)
    token = CURRENT_TENANT_ID_CONTEXTVAR.set("parent-tenant")
    try:
        await _request(app, "/stream", tenant_id=tenant_id)
        assert observed == [tenant_id or "parent-tenant"] * 2
        assert CURRENT_TENANT_ID_CONTEXTVAR.get() == "parent-tenant"
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(token)
