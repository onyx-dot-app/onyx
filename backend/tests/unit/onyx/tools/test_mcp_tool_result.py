"""MCPTool encodes a server's JSON text result once, not as an escaped string
inside another JSON object (onyx-dot-app/onyx#16016)."""

import json
from unittest.mock import MagicMock, patch

import pytest
from pydantic import JsonValue

from onyx.db.enums import MCPAuthenticationType, MCPOAuthProviderMode
from onyx.db.models import MCPServer
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import CustomToolDelta
from onyx.tools.models import CustomToolCallSummary, ToolResponse
from onyx.tools.tool_implementations.mcp.mcp_tool import MCPTool


def _reject_non_finite_number(constant: str) -> float:
    raise ValueError(f"Non-finite JSON number: {constant}")


def _run_with_server_text(text: str) -> tuple[ToolResponse, CustomToolDelta]:
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
    emitter = MagicMock()
    tool = MCPTool(
        tool_id=1,
        emitter=emitter,
        mcp_server=server,
        tool_name="list_issues",
        tool_description="List issues",
        tool_definition={"type": "object", "properties": {}},
    )
    with patch(
        "onyx.tools.tool_implementations.mcp.mcp_tool.call_mcp_tool",
        return_value=text,
    ):
        response = tool.run(Placement(turn_index=0))
    delta = emitter.emit.call_args.args[0].obj
    assert isinstance(delta, CustomToolDelta)
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

    llm_facing = json.loads(
        response.llm_facing_response, parse_constant=_reject_non_finite_number
    )
    assert llm_facing == expected
    assert isinstance(response.rich_response, CustomToolCallSummary)
    assert response.rich_response.tool_result == expected
    assert delta.data == expected


def test_json_object_reaches_the_model_without_extra_escaping() -> None:
    server_text = '{"number":12,"title":"Fix the \\"widget\\" parser"}'

    response, _ = _run_with_server_text(server_text)

    assert response.llm_facing_response == (
        '{"tool_result": {"number": 12, "title": "Fix the \\"widget\\" parser"}}'
    )
    old_response = json.dumps({"tool_result": server_text})
    assert len(response.llm_facing_response) < len(old_response)
