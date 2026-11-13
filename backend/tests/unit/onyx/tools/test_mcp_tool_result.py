"""MCPTool results: a server's JSON text is encoded once, not as an escaped string
inside another JSON object (onyx-dot-app/onyx#16016), and a failure that the server
reports is a tool error."""

import json
import logging
from unittest.mock import patch

import httpx
import pytest
from mcp.types import AudioContent, CallToolResult, ImageContent, TextContent
from pydantic import JsonValue

from onyx.agents.tools import ToolInvocation
from onyx.chat.renderer import ToolRenderer
from onyx.db.enums import (
    MCPAuthenticationPerformer,
    MCPAuthenticationType,
    MCPOAuthProviderMode,
)
from onyx.db.models import MCPServer
from onyx.llm.cancellation import AgentCancelled, CancellationSignal
from onyx.llm.models import ToolCall, ToolResult, ToolResultMessage
from onyx.server.features.mcp.credentials import ResolvedMCPCredentials
from onyx.server.metrics.mcp_common import MCPToolCallStatus
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import CustomToolDelta
from onyx.tools.models import CustomToolCallSummary, ToolContext
from onyx.tools.tool_implementations.mcp.mcp_tool import MCPTool


def _reject_non_finite_number(constant: str) -> float:
    raise ValueError(f"Non-finite JSON number: {constant}")


MODULE = "onyx.tools.tool_implementations.mcp.mcp_tool"


def _github_tool(*, user_managed_credentials: bool = False) -> MCPTool:
    server = MCPServer(
        id=1,
        name="GitHub",
        server_url="https://mcp.example",
        auth_type=(
            MCPAuthenticationType.API_TOKEN
            if user_managed_credentials
            else MCPAuthenticationType.NONE
        ),
        auth_performer=MCPAuthenticationPerformer.PER_USER,
        transport=None,
        oauth_provider_mode=MCPOAuthProviderMode.AUTO_DISCOVERY,
        oauth_cimd_enabled=True,
        oauth_authorization_endpoint=None,
        oauth_token_endpoint=None,
    )
    return MCPTool(
        tool_id=1,
        mcp_server=server,
        tool_name="list_issues",
        tool_description="List issues",
        tool_definition={"type": "object", "properties": {}},
        resolved_credentials=(
            ResolvedMCPCredentials(
                connection_config_id=7,
                connection_data={"headers": {"Authorization": "Bearer valid"}},
                user_oauth_token=None,
                auth_type=MCPAuthenticationType.API_TOKEN,
            )
            if user_managed_credentials
            else None
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


def _text_result(text: str) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=text)])


def _run_with_server_result(
    result: CallToolResult,
) -> tuple[ToolResult, CustomToolDelta]:
    tool = _github_tool()
    with patch(f"{MODULE}.call_mcp_tool", return_value=result):
        response = _run(tool)
    renderer = ToolRenderer(
        ToolCall(id="call", name=tool.name, arguments={}),
        Placement(turn_index=0),
        tool_id=1,
    )
    packets = renderer.complete(
        ToolResultMessage(
            tool_call_id="call",
            tool_name=tool.name,
            content=response.content,
            details=response.details,
            is_error=response.is_error,
        )
    )
    delta = next(
        packet.obj for packet in packets if isinstance(packet.obj, CustomToolDelta)
    )
    return response, delta


@pytest.mark.parametrize(
    ("server_text", "expected_tool_result"),
    [
        pytest.param(
            '{"number": 12, "title": "Fix the \\"widget\\" parser"}',
            {"number": 12, "title": 'Fix the "widget" parser'},
            id="json-object",
        ),
        pytest.param('[{"id": 1}, {"id": 2}]', [{"id": 1}, {"id": 2}], id="json-array"),
        pytest.param(
            'Fix the "widget" parser', 'Fix the "widget" parser', id="plain-text"
        ),
        pytest.param("42", "42", id="json-number-stays-text"),
        pytest.param('"quoted"', '"quoted"', id="json-string-stays-text"),
        pytest.param('{"value": NaN}', '{"value": NaN}', id="non-finite-stays-text"),
        pytest.param(
            'Found 1 issue\n\n{"id": 1}',
            'Found 1 issue\n\n{"id": 1}',
            id="several-content-blocks-stay-text",
        ),
    ],
)
def test_tool_result_is_encoded_once(
    server_text: str, expected_tool_result: JsonValue
) -> None:
    response, delta = _run_with_server_result(_text_result(server_text))
    expected = {"tool_result": expected_tool_result}

    llm_facing = json.loads(response.text, parse_constant=_reject_non_finite_number)
    assert llm_facing == expected
    assert isinstance(response.details, CustomToolCallSummary)
    assert response.details.tool_result == expected
    assert delta.data == expected


def test_json_object_reaches_the_model_without_extra_escaping() -> None:
    server_text = '{"number":12,"title":"Fix the \\"widget\\" parser"}'

    response, _ = _run_with_server_result(_text_result(server_text))

    assert response.text == (
        '{"tool_result": {"number": 12, "title": "Fix the \\"widget\\" parser"}}'
    )
    old_response = json.dumps({"tool_result": server_text})
    assert len(response.text) < len(old_response)


def test_text_content_takes_precedence_over_structured_content() -> None:
    result = CallToolResult(
        content=[TextContent(type="text", text="2 open issues")],
        structuredContent={"open": 2},
    )
    response, delta = _run_with_server_result(result)
    assert json.loads(response.text) == {"tool_result": "2 open issues"}
    assert delta.data == {"tool_result": "2 open issues"}


def test_structured_content_is_the_text_when_the_server_sends_no_text() -> None:
    result = CallToolResult(content=[], structuredContent={"open": 2})

    response, _ = _run_with_server_result(result)

    assert json.loads(response.text) == {"tool_result": {"open": 2}}


def test_empty_result_does_not_invent_none_text() -> None:
    response, _ = _run_with_server_result(CallToolResult(content=[]))
    assert json.loads(response.text) == {"tool_result": ""}


def test_server_reported_error_is_a_tool_error_not_an_auth_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    message = "403 Forbidden: repo access denied; private request data"
    with (
        patch(
            f"{MODULE}.call_mcp_tool",
            return_value=CallToolResult(
                content=[TextContent(type="text", text=message)], isError=True
            ),
        ),
        patch(f"{MODULE}.mark_connection_config_reauth_required") as mark,
        patch(f"{MODULE}.record_mcp_client_tool_outcome") as record_outcome,
        caplog.at_level(logging.INFO),
    ):
        response = _run(_github_tool(user_managed_credentials=True))

    assert response.is_error
    assert json.loads(response.content) == {"error": message}
    assert record_outcome.call_args.kwargs["status"] == MCPToolCallStatus.ERROR
    mark.assert_not_called()
    assert not [record for record in caplog.records if record.levelno >= logging.ERROR]
    assert message not in caplog.text
    assert "reported an error" in caplog.text


def test_rejected_user_credentials_still_require_reauthentication() -> None:
    error = httpx.HTTPStatusError(
        "upstream rejected request",
        request=httpx.Request("POST", "https://mcp.example"),
        response=httpx.Response(401),
    )
    with (
        patch(f"{MODULE}.call_mcp_tool", side_effect=error),
        patch(f"{MODULE}.get_session_with_current_tenant") as session,
        patch(f"{MODULE}.mark_connection_config_reauth_required") as mark,
    ):
        response = _run(_github_tool(user_managed_credentials=True))

    assert response.is_error
    assert "Authentication failed" in response.text
    mark.assert_called_once_with(
        7,
        {"headers": {"Authorization": "Bearer valid"}},
        session.return_value.__enter__.return_value,
    )


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        pytest.param(
            CallToolResult(
                content=[], structuredContent={"code": "not_found"}, isError=True
            ),
            {"code": "not_found"},
            id="structured-only",
        ),
        pytest.param(
            CallToolResult(
                content=[TextContent(type="text", text='[{"code": "not_found"}]')],
                isError=True,
            ),
            [{"code": "not_found"}],
            id="json-text-array",
        ),
        pytest.param(
            CallToolResult(
                content=[TextContent(type="text", text="Failure details")],
                structuredContent={"code": "not_found"},
                isError=True,
            ),
            "Failure details",
            id="text-takes-precedence",
        ),
    ],
)
def test_server_error_details_are_encoded_once(
    result: CallToolResult, expected: JsonValue
) -> None:
    response, delta = _run_with_server_result(result)
    assert response.is_error
    assert json.loads(response.text) == {"error": expected}
    assert delta.data == {"error": expected}


def test_cancelled_call_has_separate_metric_and_propagates() -> None:
    with (
        patch(f"{MODULE}.call_mcp_tool", side_effect=AgentCancelled),
        patch(f"{MODULE}.record_mcp_client_tool_outcome") as record,
    ):
        with pytest.raises(AgentCancelled):
            _run(_github_tool())
    assert record.call_args.kwargs["status"] == MCPToolCallStatus.CANCELLED


@pytest.mark.parametrize(
    "media",
    [
        ImageContent(type="image", mimeType="image/png", data="aGVsbG8="),
        AudioContent(type="audio", mimeType="audio/wav", data="aGVsbG8="),
    ],
)
@pytest.mark.parametrize("structured", [False, True])
def test_media_does_not_change_json_tool_result(
    media: ImageContent | AudioContent, structured: bool
) -> None:
    payload = {"answer": 42}
    result = CallToolResult(content=[media])
    if structured:
        result.structuredContent = payload
    else:
        result.content.append(TextContent(type="text", text=json.dumps(payload)))
    response, delta = _run_with_server_result(result)
    expected = {"tool_result": payload}
    assert json.loads(response.text) == expected
    assert delta.data == expected
