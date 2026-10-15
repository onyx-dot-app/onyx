"""MCPTool encodes a server's JSON text result once, not as an escaped string
inside another JSON object (onyx-dot-app/onyx#16016)."""

import json
from unittest.mock import patch

import pytest
from pydantic import JsonValue

from onyx.agents.tools import ToolInvocation
from onyx.chat.renderer import ToolRenderer
from onyx.db.enums import MCPAuthenticationType, MCPOAuthProviderMode
from onyx.db.models import MCPServer
from onyx.llm.cancellation import CancellationSignal
from onyx.llm.models import ToolCall, ToolResult, ToolResultMessage
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import CustomToolDelta
from onyx.tools.interface import ToolContext
from onyx.tools.models import CustomToolCallSummary
from onyx.tools.tool_implementations.mcp.mcp_tool import MCPTool


def _reject_non_finite_number(constant: str) -> float:
    raise ValueError(f"Non-finite JSON number: {constant}")


def _run_with_server_text(text: str) -> tuple[ToolResult, CustomToolDelta]:
    server = MCPServer(
        id=1,
        name="GitHub",
        server_url="https://mcp.example",
        auth_type=MCPAuthenticationType.NONE,
        transport=None,
        oauth_provider_mode=MCPOAuthProviderMode.AUTO_DISCOVERY,
        oauth_authorization_endpoint=None,
        oauth_token_endpoint=None,
    )
    tool = MCPTool(
        tool_id=1,
        mcp_server=server,
        tool_name="list_issues",
        tool_description="List issues",
        tool_definition={"type": "object", "properties": {}},
    )
    with patch(
        "onyx.tools.tool_implementations.mcp.mcp_tool.call_mcp_tool",
        return_value=text,
    ):
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
    response, delta = _run_with_server_text(server_text)
    expected = {"tool_result": expected_tool_result}

    llm_facing = json.loads(response.text, parse_constant=_reject_non_finite_number)
    assert llm_facing == expected
    assert isinstance(response.details, CustomToolCallSummary)
    assert response.details.tool_result == expected
    assert delta.data == expected


def test_json_object_reaches_the_model_without_extra_escaping() -> None:
    server_text = '{"number":12,"title":"Fix the \\"widget\\" parser"}'

    response, _ = _run_with_server_text(server_text)

    assert response.text == (
        '{"tool_result": {"number": 12, "title": "Fix the \\"widget\\" parser"}}'
    )
    old_response = json.dumps({"tool_result": server_text})
    assert len(response.text) < len(old_response)
