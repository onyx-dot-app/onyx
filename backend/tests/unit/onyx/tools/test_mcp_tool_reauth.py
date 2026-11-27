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
from onyx.server.features.mcp.oauth import MCPReauthenticationRequired
from onyx.server.metrics.mcp_common import MCPToolCallStatus
from onyx.tools.models import (
    CUSTOM_TOOL_ERROR_RESPONSE_TYPE,
    CustomToolCallSummary,
    ToolContext,
)
from onyx.tools.tool_implementations.mcp.mcp_tool import MCPTool

MODULE = "onyx.tools.tool_implementations.mcp.mcp_tool"


def _http_error(
    status: int, url: str = "https://mcp.example/mcp"
) -> httpx.HTTPStatusError:
    return httpx.HTTPStatusError(
        f"upstream rejected request to {url}",
        request=httpx.Request("POST", url),
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
        integration_description=None,
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


REJECTED_TOKEN = "rejected-token-fingerprint"


def _reauthentication(token_rejected: bool) -> MCPReauthenticationRequired:
    error = MCPReauthenticationRequired()
    error.rejected_token_fingerprint = REJECTED_TOKEN if token_rejected else None
    return error


@pytest.mark.parametrize(
    "error,unauthorized",
    [
        (_http_error(401), True),
        (_wrapped_unauthorized(), True),
        (_reauthentication(token_rejected=True), True),
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
        patch(f"{MODULE}.mark_credential_rejected") as mark,
        patch(f"{MODULE}.record_mcp_client_tool_outcome") as record_outcome,
    ):
        response = _run(_tool(credentials))

    assert response.is_error
    if unauthorized:
        assert "Authentication failed" in response.text
        assert record_outcome.call_args.kwargs["status"] == MCPToolCallStatus.AUTH_ERROR
        fingerprint = (
            error.rejected_token_fingerprint
            if isinstance(error, MCPReauthenticationRequired)
            else None
        )
        mark.assert_called_once_with(
            credentials, rejected_token_fingerprint=fingerprint
        )
    else:
        mark.assert_not_called()


def test_a_reauthentication_that_did_not_reject_the_token_keeps_the_connection() -> (
    None
):
    """A failed refresh or a 403 insufficient_scope asks for a new sign-in
    but does not prove that the stored sign-in is bad."""
    credentials = _credentials(IntegrationAuthMethod.OAUTH2)
    with (
        patch(
            f"{MODULE}.call_mcp_tool",
            side_effect=_reauthentication(token_rejected=False),
        ),
        patch(f"{MODULE}.mark_credential_rejected") as mark,
        patch(f"{MODULE}.record_mcp_client_tool_outcome"),
    ):
        response = _run(_tool(credentials))

    assert response.is_error
    assert "Authentication failed" in response.text
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


@pytest.mark.parametrize(
    "error,is_auth_error,is_unreachable,status_code",
    [
        (_http_error(401), True, False, 401),
        (_wrapped_unauthorized(), True, False, 401),
        (_http_error(403), True, False, 403),
        (_http_error(503), False, False, 503),
        (
            _http_error(503, "https://mcp.example/authentication/mcp"),
            False,
            False,
            503,
        ),
        (httpx.ConnectError("connection refused"), False, True, None),
        (httpx.ReadTimeout("timeout"), False, True, None),
    ],
)
def test_a_failed_call_tells_the_chat_how_it_failed(
    error: Exception, is_auth_error: bool, is_unreachable: bool, status_code: int | None
) -> None:
    with (
        patch(f"{MODULE}.call_mcp_tool", side_effect=error),
        patch(f"{MODULE}.mark_credential_rejected"),
        patch(f"{MODULE}.record_mcp_client_tool_outcome"),
    ):
        response = _run(_tool(_credentials(IntegrationAuthMethod.API_KEY)))

    assert isinstance(response.details, CustomToolCallSummary)
    assert response.details.integration_id == 5
    error_info = response.details.error
    assert error_info is not None
    assert error_info.is_auth_error is is_auth_error
    assert error_info.is_unreachable is is_unreachable
    assert error_info.status_code == status_code
    assert "Plugins page" not in response.text


def test_an_unexplained_failure_is_a_failed_step() -> None:
    with (
        patch(f"{MODULE}.call_mcp_tool", side_effect=ValueError("bad input")),
        patch(f"{MODULE}.record_mcp_client_tool_outcome"),
    ):
        response = _run(_tool(_credentials(None)))

    assert isinstance(response.details, CustomToolCallSummary)
    assert response.details.response_type == CUSTOM_TOOL_ERROR_RESPONSE_TYPE
    assert response.details.error is None
