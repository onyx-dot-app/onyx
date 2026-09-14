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
