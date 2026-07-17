import asyncio
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient

from onyx.db.enums import MCPAuthenticationType
from onyx.mcp_server.api import create_mcp_fastapi_app
from onyx.mcp_server.auth import OnyxTokenVerifier
from onyx.mcp_server.tools import search
from onyx.server.metrics import mcp_client
from onyx.server.metrics import metrics_auth
from onyx.server.metrics.mcp_common import MCPToolCallStatus
from onyx.server.metrics.mcp_server import MCPAuthResult
from onyx.server.metrics.mcp_server import MCPServerToolName
from onyx.server.query_and_chat.placement import Placement
from onyx.tools.tool_implementations.mcp.mcp_tool import MCPTool


def _mcp_tool(
    auth_type: MCPAuthenticationType = MCPAuthenticationType.NONE,
) -> MCPTool:
    server = MagicMock()
    server.name = "Customer MCP"
    server.server_url = "https://mcp.example"
    server.auth_type = auth_type
    server.transport = None
    return MCPTool(
        tool_id=1,
        emitter=MagicMock(),
        mcp_server=server,
        tool_name="lookup",
        tool_description="Lookup",
        tool_definition={"type": "object", "properties": {}},
    )


def test_client_records_success_once() -> None:
    tool = _mcp_tool()
    with (
        patch(
            "onyx.tools.tool_implementations.mcp.mcp_tool.call_mcp_tool",
            return_value={"ok": True},
        ),
        patch(
            "onyx.tools.tool_implementations.mcp.mcp_tool."
            "record_mcp_client_tool_outcome"
        ) as record,
    ):
        tool.run(Placement(turn_index=0))

    record.assert_called_once()
    assert record.call_args.kwargs["status"] == MCPToolCallStatus.SUCCESS


def test_client_records_missing_credentials_as_auth_error() -> None:
    tool = _mcp_tool(MCPAuthenticationType.API_TOKEN)
    with patch(
        "onyx.tools.tool_implementations.mcp.mcp_tool.record_mcp_client_tool_outcome"
    ) as record:
        tool.run(Placement(turn_index=0))

    record.assert_called_once()
    assert record.call_args.kwargs["status"] == MCPToolCallStatus.AUTH_ERROR


def test_client_records_post_call_failure_once() -> None:
    tool = _mcp_tool()
    with (
        patch.object(
            tool.emitter,
            "emit",
            side_effect=[RuntimeError("emit failed"), None],
        ),
        patch(
            "onyx.tools.tool_implementations.mcp.mcp_tool.call_mcp_tool",
            return_value={"ok": True},
        ),
        patch(
            "onyx.tools.tool_implementations.mcp.mcp_tool."
            "record_mcp_client_tool_outcome"
        ) as record,
    ):
        response = tool.run(Placement(turn_index=0))

    assert "emit failed" in response.llm_facing_response
    record.assert_called_once()
    assert record.call_args.kwargs["status"] == MCPToolCallStatus.ERROR


def test_client_metric_failure_does_not_raise() -> None:
    with patch.object(
        mcp_client.MCP_CLIENT_TOOL_LATENCY,
        "labels",
        side_effect=RuntimeError("metric failed"),
    ):
        mcp_client.record_mcp_client_tool_outcome(
            server_name="Customer MCP",
            tool_name="lookup",
            start_time=0.0,
            status=MCPToolCallStatus.SUCCESS,
        )


def test_server_empty_state_is_success() -> None:
    with (
        patch.object(search, "require_access_token", return_value=MagicMock()),
        patch.object(search, "get_indexed_sources", new=AsyncMock(return_value=[])),
        patch.object(search, "record_mcp_server_tool_outcome") as outcome,
        patch.object(search, "record_mcp_search_results") as results,
    ):
        response = asyncio.run(search.search_indexed_documents("query"))

    assert response["results"] == []
    outcome.assert_called_once()
    assert outcome.call_args.args[2] == MCPToolCallStatus.SUCCESS
    results.assert_called_once_with(MCPServerToolName.SEARCH_INDEXED_DOCUMENTS, 0)


def test_server_upstream_failure_is_recorded_once() -> None:
    failed_response = httpx.Response(
        503,
        json={"detail": "unavailable"},
        request=httpx.Request("POST", "https://api.example/search"),
    )
    with (
        patch.object(search, "require_access_token", return_value=MagicMock()),
        patch.object(
            search,
            "_post_model",
            new=AsyncMock(return_value=failed_response),
        ),
        patch.object(search, "record_mcp_server_tool_outcome") as outcome,
    ):
        response = asyncio.run(search.search_web("query"))

    assert response["error"] == "unavailable"
    outcome.assert_called_once()
    assert outcome.call_args.args[2] == MCPToolCallStatus.ERROR


def test_server_deduplicates_requested_sources() -> None:
    with patch.object(search, "record_mcp_search_source") as record:
        search._record_requested_sources(["github", "GITHUB", "invalid", "other"])

    assert {call.args[0] for call in record.call_args_list} == {
        "github",
        "unknown",
    }


def test_auth_verifier_records_success() -> None:
    client = MagicMock()
    client.get = AsyncMock(return_value=MagicMock(status_code=200))
    with (
        patch("onyx.mcp_server.auth.get_http_client", return_value=client),
        patch("onyx.mcp_server.auth.record_mcp_auth_result") as record,
    ):
        token = asyncio.run(OnyxTokenVerifier().verify_token("token"))

    assert token is not None
    record.assert_called_once_with(MCPAuthResult.SUCCESS)


def test_auth_verifier_records_rejection_and_backend_error() -> None:
    client = MagicMock()
    client.get = AsyncMock(return_value=MagicMock(status_code=401))
    with (
        patch("onyx.mcp_server.auth.get_http_client", return_value=client),
        patch("onyx.mcp_server.auth.record_mcp_auth_result") as record,
    ):
        assert asyncio.run(OnyxTokenVerifier().verify_token("token")) is None
    record.assert_called_once_with(MCPAuthResult.REJECTED)

    client.get = AsyncMock(side_effect=RuntimeError("offline"))
    with (
        patch("onyx.mcp_server.auth.get_http_client", return_value=client),
        patch("onyx.mcp_server.auth.record_mcp_auth_result") as record,
    ):
        assert asyncio.run(OnyxTokenVerifier().verify_token("token")) is None
    record.assert_called_once_with(MCPAuthResult.ERROR)


def test_mcp_metrics_endpoint_uses_shared_bearer_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(metrics_auth, "DISABLE_METRICS_AUTH", False)
    monkeypatch.setattr(metrics_auth, "METRICS_AUTH_TOKEN", "metrics-token")
    client = TestClient(create_mcp_fastapi_app(), raise_server_exceptions=False)

    assert client.get("/metrics").status_code == 401
    response = client.get(
        "/metrics",
        headers={"Authorization": "Bearer metrics-token"},
    )

    assert response.status_code == 200
    assert "onyx_mcp_server_auth_total" in response.text
