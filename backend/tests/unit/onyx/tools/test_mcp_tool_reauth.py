"""An MCP call sends the credential that construction resolved, resolves it
again only when its token is near expiry, and a service that rejects an API
key sets that connection to Needs reconnect."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from uuid import uuid4

import httpx
import pytest

from onyx.agents.tools import ToolInvocation
from onyx.db.enums import IntegrationAuthMethod
from onyx.integrations.call_credentials import CallCredentials
from onyx.integrations.connection_models import ConnectionState
from onyx.integrations.connections import ConnectionProblem
from onyx.llm.cancellation import CancellationSignal
from onyx.llm.models import ToolResult
from onyx.server.metrics.mcp_common import MCPToolCallStatus
from onyx.tools.models import ToolContext
from onyx.tools.tool_implementations.mcp.mcp_tool import MCPTool

MODULE = "onyx.tools.tool_implementations.mcp.mcp_tool"


def _http_error(status: int) -> httpx.HTTPStatusError:
    return httpx.HTTPStatusError(
        "upstream rejected request",
        request=httpx.Request("POST", "https://mcp.example/mcp"),
        response=httpx.Response(status),
    )


def _wrapped_unauthorized() -> Exception:
    error = RuntimeError("MCP call failed")
    error.__cause__ = ExceptionGroup("transport errors", [_http_error(401)])
    return error


def _tool(credentials: CallCredentials) -> MCPTool:
    return MCPTool(
        integration_id=5,
        integration_name="test",
        server_url="https://mcp.example/mcp",
        transport=None,
        tool_name="test",
        tool_description="test",
        tool_definition={},
        acting_user_id=uuid4(),
        credentials=credentials,
        additional_headers={"X-Request": "1", "Host": "evil"},
    )


def _credentials(
    method: IntegrationAuthMethod | None,
    *,
    expires_in: timedelta | None = None,
    token: str = "stored",
) -> CallCredentials:
    return CallCredentials(
        integration_id=5,
        auth_method=method,
        connection_id=7 if method is not None else None,
        connection_user_id=None,
        headers={"Authorization": f"Bearer {token}"},
        expires_at=(
            datetime.now(timezone.utc) + expires_in if expires_in is not None else None
        ),
    )


def _run(tool: MCPTool) -> ToolResult:
    response = tool.run(
        ToolInvocation(
            call_id="call",
            arguments={},
            cancellation=CancellationSignal(),
            update=lambda _: None,
        ),
        ToolContext(),
    )
    assert isinstance(response, ToolResult)
    return response


@pytest.mark.parametrize(
    "error,unauthorized",
    [
        (_http_error(401), True),
        (_wrapped_unauthorized(), True),
        (_http_error(403), False),
        (_http_error(503), False),
        (httpx.ReadTimeout("timeout"), False),
        (ValueError("401 invalid api key"), False),
    ],
)
@pytest.mark.parametrize(
    "method",
    [
        IntegrationAuthMethod.API_KEY,
        IntegrationAuthMethod.OAUTH2,
        IntegrationAuthMethod.ONYX_LOGIN,
        None,
    ],
)
def test_only_a_rejected_call_reports_the_credential(
    error: Exception, unauthorized: bool, method: IntegrationAuthMethod | None
) -> None:
    credentials = _credentials(method)
    with (
        patch(f"{MODULE}.call_mcp_tool", side_effect=error),
        patch(f"{MODULE}.mark_api_key_rejected") as mark,
        patch(f"{MODULE}.record_mcp_client_tool_outcome") as record_outcome,
    ):
        response = _run(_tool(credentials))

    assert "error" in response.text
    if unauthorized:
        assert "Authentication failed" in response.text
        assert record_outcome.call_args.kwargs["status"] == MCPToolCallStatus.AUTH_ERROR
        mark.assert_called_once_with(credentials)
    else:
        mark.assert_not_called()


def test_a_call_sends_the_construction_credential_with_no_new_resolve() -> None:
    call = MagicMock()
    tool = _tool(
        _credentials(IntegrationAuthMethod.OAUTH2, expires_in=timedelta(hours=1))
    )
    with (
        patch(f"{MODULE}.resolve_fresh_call_credentials") as resolve,
        patch(f"{MODULE}.call_mcp_tool", call),
        patch(f"{MODULE}.record_mcp_client_tool_outcome"),
    ):
        _run(tool)
        _run(tool)

    resolve.assert_not_called()
    assert call.call_count == 2
    assert call.call_args.kwargs["connection_headers"] == {
        "X-Request": "1",
        "Authorization": "Bearer stored",
    }


@pytest.mark.parametrize(
    "method", [IntegrationAuthMethod.OAUTH2, IntegrationAuthMethod.ONYX_LOGIN]
)
def test_a_token_near_expiry_resolves_again_once(
    method: IntegrationAuthMethod,
) -> None:
    call = MagicMock()
    tool = _tool(_credentials(method, expires_in=timedelta(seconds=30)))
    fresh = _credentials(method, expires_in=timedelta(hours=1), token="fresh")
    with (
        patch(
            f"{MODULE}.resolve_fresh_call_credentials", return_value=fresh
        ) as resolve,
        patch(f"{MODULE}.call_mcp_tool", call),
        patch(f"{MODULE}.record_mcp_client_tool_outcome"),
    ):
        _run(tool)
        _run(tool)

    resolve.assert_called_once()
    assert resolve.call_args.args[0] == 5
    assert call.call_args.kwargs["connection_headers"]["Authorization"] == (
        "Bearer fresh"
    )


def test_an_api_key_with_an_expiry_does_not_resolve_again() -> None:
    tool = _tool(
        _credentials(IntegrationAuthMethod.API_KEY, expires_in=timedelta(seconds=-5))
    )
    with (
        patch(f"{MODULE}.resolve_fresh_call_credentials") as resolve,
        patch(f"{MODULE}.call_mcp_tool"),
        patch(f"{MODULE}.record_mcp_client_tool_outcome"),
    ):
        _run(tool)

    resolve.assert_not_called()


def test_a_call_whose_credential_no_longer_resolves_does_not_run() -> None:
    tool = _tool(
        _credentials(IntegrationAuthMethod.OAUTH2, expires_in=timedelta(seconds=30))
    )
    with (
        patch(
            f"{MODULE}.resolve_fresh_call_credentials",
            return_value=ConnectionProblem(
                code=ConnectionState.NOT_CONNECTED,
                reason="Connect your test account to use it.",
            ),
        ),
        patch(f"{MODULE}.call_mcp_tool") as call,
        patch(f"{MODULE}.record_mcp_client_tool_outcome") as record_outcome,
    ):
        response = _run(tool)

    call.assert_not_called()
    assert response.is_error
    assert "Connect your test account" in response.text
    assert record_outcome.call_args.kwargs["status"] == MCPToolCallStatus.AUTH_ERROR
