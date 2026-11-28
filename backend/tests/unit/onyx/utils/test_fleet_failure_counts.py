"""Tool, MCP and login failures reach the fleet only as fixed counts: on the
query event, or in one capped `failure_counts` event per process heartbeat."""

from typing import Any
from unittest.mock import Mock, patch
from uuid import uuid4

import httpx
import pytest
from fastapi import Request

from onyx.agents.tools import ToolInvocation
from onyx.auth.sso_web_error import redirect_sso_errors_to_web
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.integrations.call_credentials import CallCredentials
from onyx.llm.cancellation import CancellationSignal
from onyx.llm.models import ToolResult
from onyx.server.features.mcp import client as mcp_client
from onyx.tools.interface import Tool, tool_kind
from onyx.tools.models import ToolContext
from onyx.tools.tool_implementations.api_app.rest_tool import RestTool
from onyx.tools.tool_implementations.mcp.mcp_tool import MCPTool
from onyx.tools.tool_implementations.search.search_tool import SearchTool
from onyx.utils import fleet_query_telemetry as query
from onyx.utils import fleet_telemetry as fleet
from onyx.utils.fleet_telemetry import (
    MAX_FAILURE_COUNT,
    FailureCounts,
    LoginFailure,
    MCPFailure,
    ToolKind,
    count_failure,
    count_login_failures,
    sanitize_data,
)
from tests.utils.fleet_telemetry import make_sender


def _invocation() -> ToolInvocation:
    return ToolInvocation(
        call_id="call-1",
        arguments={"query": "private query"},
        cancellation=CancellationSignal(),
        update=lambda _: None,
    )


def _run_in_query(observation: query.QueryObservation, tool: Any) -> None:
    token = query.CURRENT_QUERY_OBSERVATION.set(observation)
    try:
        Tool.run(tool, _invocation(), ToolContext())
    finally:
        query.CURRENT_QUERY_OBSERVATION.reset(token)


def _mock_tool(tool_type: type[Tool], result: ToolResult | Exception) -> Mock:
    tool = Mock(spec=tool_type)
    tool.name = "private_tool_name"
    if isinstance(result, Exception):
        tool._run.side_effect = result
    else:
        tool._run.return_value = result
    return tool


@pytest.fixture
def counts(monkeypatch: pytest.MonkeyPatch) -> FailureCounts:
    """A fresh process aggregate with telemetry on."""
    fresh = FailureCounts()
    monkeypatch.setattr(fleet, "_failure_counts", fresh)
    monkeypatch.setattr(fleet, "_client", make_sender())
    return fresh


def test_query_counts_tool_calls_and_failures_by_kind(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sink = Mock()
    monkeypatch.setattr(query, "emit_telemetry", sink)
    observation = query.QueryObservation(channel="web", mode=query.QueryMode.CHAT)
    _run_in_query(observation, _mock_tool(SearchTool, ToolResult(content="ok")))
    _run_in_query(observation, _mock_tool(SearchTool, ToolResult(content="ok")))
    _run_in_query(
        observation,
        _mock_tool(MCPTool, ToolResult(content="private error", is_error=True)),
    )
    _run_in_query(observation, _mock_tool(RestTool, RuntimeError("private error")))
    _run_in_query(observation, _mock_tool(Tool, ToolResult(content="ok")))
    observation.mcp_auth_failed()
    observation.finish()

    event_type, data = sink.call_args.args
    assert data["tool_calls"] == {"search": 2, "mcp": 1, "custom": 1, "other": 1}
    assert data["tool_failures"] == {"mcp": 1, "custom": 1}
    assert data["mcp_auth_failures"] == 1
    assert data["tool_usage"] == "search_and_other"
    assert sanitize_data(event_type, data) == data
    assert "private" not in str(data)


def test_query_without_tools_sends_no_tool_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sink = Mock()
    monkeypatch.setattr(query, "emit_telemetry", sink)
    query.QueryObservation(channel="web", mode=query.QueryMode.CHAT).finish()
    data = sink.call_args.args[1]
    assert not {"tool_calls", "tool_failures", "mcp_auth_failures"} & data.keys()


def test_counts_stop_when_the_query_finishes(monkeypatch: pytest.MonkeyPatch) -> None:
    sink = Mock()
    monkeypatch.setattr(query, "emit_telemetry", sink)
    observation = query.QueryObservation(channel="web", mode=query.QueryMode.CHAT)
    observation.tool_started(ToolKind.MCP)
    observation.finish()
    observation.tool_failed(ToolKind.MCP)
    observation.mcp_auth_failed()
    data = sink.call_args.args[1]
    assert data["tool_calls"] == {"mcp": 1}
    assert "tool_failures" not in data and "mcp_auth_failures" not in data


def test_tool_kind_comes_from_the_class_not_the_name() -> None:
    assert tool_kind(_mock_tool(SearchTool, ToolResult(content=""))) is ToolKind.SEARCH
    assert tool_kind(_mock_tool(MCPTool, ToolResult(content=""))) is ToolKind.MCP
    assert tool_kind(_mock_tool(Tool, ToolResult(content=""))) is ToolKind.OTHER


def test_mcp_auth_failure_counts_on_the_query(monkeypatch: pytest.MonkeyPatch) -> None:
    sink = Mock()
    monkeypatch.setattr(query, "emit_telemetry", sink)
    tool = MCPTool(
        integration_id=5,
        integration_name="private server",
        integration_description=None,
        server_url="https://mcp.example/mcp",
        transport=None,
        tool_name="private_tool",
        tool_description="test",
        tool_definition={},
        acting_user_id=uuid4(),
        credentials=CallCredentials(
            integration_id=5,
            auth_method=None,
            connection_id=None,
            connection_user_id=None,
            headers={},
            expires_at=None,
        ),
    )
    unauthorized = httpx.HTTPStatusError(
        "rejected",
        request=httpx.Request("POST", "https://mcp.example/mcp"),
        response=httpx.Response(401),
    )
    observation = query.QueryObservation(channel="web", mode=query.QueryMode.CHAT)
    with patch(
        "onyx.tools.tool_implementations.mcp.mcp_tool.call_mcp_tool",
        side_effect=unauthorized,
    ):
        _run_in_query(observation, tool)
    observation.finish()
    data = sink.call_args.args[1]
    assert data["mcp_auth_failures"] == 1
    assert data["tool_failures"] == {"mcp": 1}
    assert "private" not in str(data)


def test_aggregate_caps_each_count_and_resets_per_window(
    counts: FailureCounts,
) -> None:
    for _ in range(MAX_FAILURE_COUNT + 50):
        count_failure(LoginFailure.PASSWORD)
    count_failure(MCPFailure.DISCOVERY_AUTH)
    data = counts.take()
    assert data == {
        "login_failures": {"password": MAX_FAILURE_COUNT},
        "mcp_failures": {"discovery_auth": 1},
    }
    assert sanitize_data("failure_counts", data) == data
    assert counts.take() is None


def test_nothing_is_counted_when_telemetry_is_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fresh = FailureCounts()
    monkeypatch.setattr(fleet, "_failure_counts", fresh)
    monkeypatch.setattr(fleet, "_client", None)
    count_failure(LoginFailure.SAML)
    assert fresh.take() is None


@pytest.mark.parametrize("failed", [False, True])
def test_sender_adds_one_failure_event_to_the_heartbeat_only_when_nonzero(
    monkeypatch: pytest.MonkeyPatch, counts: FailureCounts, failed: bool
) -> None:
    monkeypatch.setattr(
        "onyx.utils.fleet_telemetry_resources.collect_process_resource", Mock()
    )
    sender = make_sender(capacity=64)
    if failed:
        for _ in range(1000):
            counts.add(LoginFailure.OIDC)
        counts.add(MCPFailure.PROBE_UNREACHABLE)
    monkeypatch.setattr(sender, "flush_once", Mock(return_value=True))
    monkeypatch.setattr(sender._stop, "wait", Mock(side_effect=sender._stop.set))
    sender._run()
    events = [
        event for event in sender._take_batch() if event["event_type"] != "version"
    ]
    failure_events = [e for e in events if e["event_type"] == "failure_counts"]
    assert sender.invalid == 0
    if not failed:
        assert failure_events == []
        return
    assert len(failure_events) == 1
    assert failure_events[0]["data"] == {
        "login_failures": {"oidc": 1000},
        "mcp_failures": {"probe_unreachable": 1},
    }


@pytest.mark.asyncio
async def test_login_handlers_count_each_failure_once(counts: FailureCounts) -> None:
    @count_login_failures(LoginFailure.OAUTH)
    async def oauth_callback() -> None:
        raise OnyxError(OnyxErrorCode.VALIDATION_ERROR, "private detail")

    @redirect_sso_errors_to_web(LoginFailure.SAML)
    async def saml_callback(*, request: Request) -> Any:  # noqa: ARG001
        raise OnyxError(OnyxErrorCode.UNAUTHORIZED, "private detail")

    with pytest.raises(OnyxError):
        await oauth_callback()
    await saml_callback(
        request=Request({"type": "http", "headers": [], "query_string": b""})
    )
    assert counts.take() == {"login_failures": {"oauth": 1, "saml": 1}}


@pytest.mark.parametrize(
    "error,expected",
    [
        (
            httpx.HTTPStatusError(
                "rejected",
                request=httpx.Request("POST", "https://mcp.example"),
                response=httpx.Response(403),
            ),
            MCPFailure.DISCOVERY_AUTH,
        ),
        (httpx.ConnectTimeout("private"), MCPFailure.DISCOVERY_TIMEOUT),
        (httpx.ConnectError("private"), MCPFailure.DISCOVERY_ERROR),
    ],
)
def test_mcp_discovery_failures_count_by_category(
    counts: FailureCounts, error: Exception, expected: MCPFailure
) -> None:
    with (
        patch.object(mcp_client, "_call_mcp_client_function_sync", side_effect=error),
        pytest.raises(httpx.HTTPError),
    ):
        mcp_client.discover_mcp_tools("https://mcp.example")
    assert counts.take() == {"mcp_failures": {expected.value: 1}}
