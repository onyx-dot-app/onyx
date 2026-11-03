from collections.abc import Coroutine
from typing import Any

import pytest
from mcp import ClientSession

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
