import asyncio
import threading
from collections.abc import Coroutine
from typing import Any
from unittest.mock import AsyncMock

import pytest
from mcp import ClientSession
from mcp.types import CallToolResult, TextContent

from onyx.llm.cancellation import AgentCancelled, CancellationSignal
from onyx.server.features.mcp import client
from onyx.server.features.mcp.oauth import MCPReauthenticationRequired


def test_sync_client_unwraps_nested_reauthentication_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reauthentication_required = MCPReauthenticationRequired()

    def raise_nested_error(coroutine: Coroutine[Any, Any, object]) -> object:
        coroutine.close()
        raise ExceptionGroup(
            "transport cleanup",
            [ExceptionGroup("request failed", [reauthentication_required])],
        )

    async def operation(_session: ClientSession) -> None:
        raise AssertionError("transport should fail before opening a session")

    monkeypatch.setattr(client, "run_async_sync_no_cancel", raise_nested_error)

    with pytest.raises(MCPReauthenticationRequired) as exc_info:
        client._call_mcp_client_function_sync(
            operation,
            "https://mcp.example.com/mcp",
        )

    assert exc_info.value is reauthentication_required


@pytest.mark.parametrize("nested", [False, True])
def test_discovery_reports_unauthorized_without_upstream_secrets(
    monkeypatch: pytest.MonkeyPatch,
    nested: bool,
) -> None:
    from httpx import HTTPStatusError, Request, Response

    from onyx.error_handling.error_codes import OnyxErrorCode
    from onyx.error_handling.exceptions import OnyxError

    request = Request(
        "POST",
        "https://mcp.example.com/?token=private",
        headers={"Authorization": "Bearer private"},
    )
    upstream = HTTPStatusError(
        "private upstream response",
        request=request,
        response=Response(401, request=request),
    )

    def fail(coroutine: Coroutine[Any, Any, object]) -> object:
        coroutine.close()
        if nested:
            raise ExceptionGroup(
                "transport",
                [ExceptionGroup("request", [upstream]), ValueError("cleanup private")],
            )
        raise upstream

    monkeypatch.setattr(client, "run_async_sync_no_cancel", fail)
    with pytest.raises(OnyxError) as error:
        client.discover_mcp_tools("https://mcp.example.com/mcp")
    assert error.value.error_code == OnyxErrorCode.UNAUTHENTICATED
    assert "401 Unauthorized" in str(error.value)
    assert "private" not in str(error.value)


@pytest.mark.parametrize("status", [403, 404, 500])
def test_discovery_preserves_non_authentication_failures(
    monkeypatch: pytest.MonkeyPatch,
    status: int,
) -> None:
    from httpx import HTTPStatusError, Request, Response

    request = Request("POST", "https://mcp.example.com")
    upstream = HTTPStatusError(
        "upstream", request=request, response=Response(status, request=request)
    )

    def fail(coroutine: Coroutine[Any, Any, object]) -> object:
        coroutine.close()
        raise upstream

    monkeypatch.setattr(client, "run_async_sync_no_cancel", fail)
    with pytest.raises(HTTPStatusError) as error:
        client.discover_mcp_tools("https://mcp.example.com")
    assert error.value is upstream


def test_runtime_keeps_raw_unauthorized_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from httpx import HTTPStatusError, Request, Response

    request = Request("POST", "https://mcp.example.com")
    upstream = HTTPStatusError(
        "upstream", request=request, response=Response(401, request=request)
    )

    def fail(coroutine: Coroutine[Any, Any, object]) -> object:
        coroutine.close()
        raise upstream

    async def operation(_session: ClientSession) -> None:
        raise AssertionError("Transport fails first")

    monkeypatch.setattr(client, "run_async_sync_no_cancel", fail)
    with pytest.raises(HTTPStatusError) as error:
        client._call_mcp_client_function_sync(operation, "https://mcp.example.com")
    assert error.value is upstream
    assert client.has_unauthorized_response(error.value)


def test_call_tool_preserves_server_error_flag() -> None:
    result = CallToolResult(
        content=[TextContent(type="text", text="Tool request failed")], isError=True
    )
    session = AsyncMock(spec=ClientSession)
    session.call_tool.return_value = result

    received = asyncio.run(client._call_mcp_tool("lookup", {"id": 1})(session))

    assert received is result
    session.initialize.assert_awaited_once()
    session.call_tool.assert_awaited_once_with("lookup", {"id": 1})


def test_cancellation_stops_a_running_call(monkeypatch: pytest.MonkeyPatch) -> None:
    cancellation = CancellationSignal()
    stopped = threading.Event()

    async def slow_call() -> None:
        try:
            # Cancel from the worker thread while the request is running.
            asyncio.get_running_loop().call_soon(cancellation.cancel)
            await asyncio.sleep(30)
        finally:
            stopped.set()

    async def operation(_session: ClientSession) -> None:
        raise AssertionError("the runner is replaced")

    monkeypatch.setattr(
        client,
        "_create_mcp_client_function_runner",
        lambda *_args, **_kwargs: slow_call,
    )
    with pytest.raises(AgentCancelled):
        client._call_mcp_client_function_sync(
            operation, "https://mcp.example.com/mcp", cancellation=cancellation
        )
    assert stopped.is_set()


def test_already_cancelled_call_does_not_start() -> None:
    cancellation = CancellationSignal()
    cancellation.cancel()

    async def operation() -> None:
        pytest.fail("A cancelled request must not start")

    with pytest.raises(AgentCancelled):
        client._run_until_cancelled(operation(), cancellation)


@pytest.mark.parametrize("cancel_on_completion", [False, True])
def test_completed_call_keeps_its_result(cancel_on_completion: bool) -> None:
    cancellation = CancellationSignal()

    async def operation() -> str:
        if cancel_on_completion:
            cancellation.cancel()
        return "completed"

    assert client._run_until_cancelled(operation(), cancellation) == "completed"
    # Completing removes the cancellation callback from the closed event loop.
    cancellation.cancel()


def test_failed_call_keeps_its_error() -> None:
    cancellation = CancellationSignal()
    failure = ValueError("server failed")

    async def operation() -> None:
        raise failure

    with pytest.raises(ValueError) as error:
        client._run_until_cancelled(operation(), cancellation)
    assert error.value is failure
    cancellation.cancel()
