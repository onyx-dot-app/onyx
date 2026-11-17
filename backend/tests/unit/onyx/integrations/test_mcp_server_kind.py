"""The ``mcp_server`` integration kind, with the DB getters patched."""

import json
from typing import Any
from unittest.mock import MagicMock

import pytest
from sqlalchemy.orm import Session

from onyx.db.enums import (
    GatedAppKind,
    IntegrationActionPolicyValue,
    IntegrationAuthMode,
    IntegrationKind,
    MCPAuthenticationType,
    MCPOAuthProviderMode,
)
from onyx.db.models import Integration, IntegrationAction, MCPServer
from onyx.external_apps.matching.request import ProxiedRequest
from onyx.integrations.kinds import mcp_server as mcp_kind
from onyx.integrations.kinds.mcp_server import McpServerKindHandler
from onyx.integrations.kinds.models import ChatToolContext
from onyx.sandbox_proxy.request_evaluator import MCP_UNCLASSIFIABLE_ACTION_TYPE
from onyx.tools.models import ToolApprovalScope
from onyx.tools.tool_implementations.mcp.mcp_tool import MCPTool

DB = MagicMock(spec=Session)
SERVER_URL = "https://mcp.example.com/linear/mcp"


@pytest.fixture
def integration() -> Integration:
    return Integration(
        id=7,
        kind=IntegrationKind.MCP,
        name="Linear",
        auth_mode=IntegrationAuthMode.NONE,
        mcp_server_id=3,
    )


@pytest.fixture(autouse=True)
def server(monkeypatch: pytest.MonkeyPatch) -> MCPServer:
    server = MCPServer(
        id=3,
        name="old-name",
        server_url=SERVER_URL,
        auth_type=MCPAuthenticationType.NONE,
        transport=None,
        oauth_provider_mode=MCPOAuthProviderMode.AUTO_DISCOVERY,
        oauth_cimd_enabled=True,
        oauth_authorization_endpoint=None,
        oauth_token_endpoint=None,
    )
    monkeypatch.setattr(
        mcp_kind, "get_mcp_server_for_integration", lambda *_args: server
    )
    return server


def _actions(monkeypatch: pytest.MonkeyPatch, rows: list[IntegrationAction]) -> None:
    monkeypatch.setattr(mcp_kind, "list_integration_actions", lambda *_args: rows)


def _rpc(method: str, **params: Any) -> bytes:
    return json.dumps(
        {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    ).encode()


def _request(
    body: bytes | None, url: str = SERVER_URL, method: str = "POST"
) -> ProxiedRequest:
    return ProxiedRequest(
        method=method,
        path="/linear/mcp",
        body=body,
        url=url,
        headers={"content-type": "application/json"},
    )


def test_match_tools_call_uses_action_defaults(
    monkeypatch: pytest.MonkeyPatch,
    integration: Integration,
) -> None:
    _actions(
        monkeypatch,
        [
            IntegrationAction(
                key="search",
                read_only=True,
                default_policy=IntegrationActionPolicyValue.ALLOW,
            ),
            # A migrated row has no default policy; read_only decides.
            IntegrationAction(key="legacy_read", read_only=True, default_policy=None),
        ],
    )
    body = json.dumps(
        [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "search"},
            },
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "search"},
            },
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "legacy_read"},
            },
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {"name": "unknown"},
            },
        ]
    ).encode()

    matched = McpServerKindHandler().match_request(integration, _request(body), DB)

    assert matched is not None
    assert {(m.action_key, m.default_policy) for m in matched} == {
        ("search", IntegrationActionPolicyValue.ALLOW),
        ("legacy_read", IntegrationActionPolicyValue.ALLOW),
        ("unknown", IntegrationActionPolicyValue.ASK),
    }
    assert all(m.integration_id == integration.id for m in matched)
    search = next(m for m in matched if m.action_key == "search")
    assert "invokes it 2 times" in search.description
    # The integration name, not the old copy on the server row.
    assert "Linear" in search.description


@pytest.mark.parametrize(
    "body,method",
    [
        (_rpc("initialize"), "POST"),
        (_rpc("tools/list"), "POST"),
        (None, "GET"),
        (None, "DELETE"),
    ],
)
def test_match_protocol_message_is_empty_not_none(
    integration: Integration,
    body: bytes | None,
    method: str,
) -> None:
    matched = McpServerKindHandler().match_request(
        integration, _request(body, method=method), DB
    )
    assert matched == []


@pytest.mark.parametrize(
    "body",
    [b"not json", _rpc("tools/call"), _rpc("unknown/method"), b"[]"],
)
def test_match_unparsable_body_is_blocked(
    integration: Integration,
    body: bytes,
) -> None:
    matched = McpServerKindHandler().match_request(integration, _request(body), DB)
    assert matched is not None
    assert [(m.action_key, m.default_policy) for m in matched] == [
        (MCP_UNCLASSIFIABLE_ACTION_TYPE, IntegrationActionPolicyValue.BLOCKED)
    ]


def test_match_upgrade_request_is_blocked(
    integration: Integration,
) -> None:
    request = _request(None, method="GET").model_copy(
        update={"headers": {"Upgrade": "websocket", "Connection": "Upgrade"}}
    )
    matched = McpServerKindHandler().match_request(integration, request, DB)
    assert matched is not None
    assert matched[0].action_key == MCP_UNCLASSIFIABLE_ACTION_TYPE


@pytest.mark.parametrize(
    "url",
    [
        "https://other.example.com/linear/mcp",
        "https://mcp.example.com/github/mcp",
        "http://mcp.example.com/linear/mcp",
        "https://mcp.example.com:8443/linear/mcp",
        # Traversal out of the prefix does not count as the server.
        "https://mcp.example.com/linear/mcp/../../admin",
    ],
)
def test_match_request_for_another_target_is_none(
    integration: Integration,
    url: str,
) -> None:
    matched = McpServerKindHandler().match_request(
        integration, _request(_rpc("tools/call", name="search"), url=url), DB
    )
    assert matched is None


def test_match_request_without_url_is_none(
    integration: Integration,
) -> None:
    request = ProxiedRequest(method="POST", path="/linear/mcp", body=_rpc("ping"))
    assert McpServerKindHandler().match_request(integration, request, DB) is None


def test_build_chat_tools_sets_approval_and_schemas(
    integration: Integration, server: MCPServer
) -> None:
    scope = ToolApprovalScope(
        app_kind=GatedAppKind.MCP_SERVER, target_id=server.id, action_id="create"
    )
    actions = [
        IntegrationAction(
            id=11,
            key="search",
            description="Find",
            input_schema={"type": "object", "properties": {"q": {"type": "string"}}},
            output_schema={"type": "object"},
        ),
        IntegrationAction(id=12, key="create", description=None, input_schema=None),
    ]
    ctx = ChatToolContext(
        user_email="u@example.com",
        approval_for=lambda key: scope if key == "create" else None,
    )

    tools = McpServerKindHandler().build_chat_tools(integration, actions, ctx, DB)

    assert all(isinstance(t, MCPTool) for t in tools)
    search, create = tools
    assert search.approval is None
    assert create.approval == scope
    assert search.id == 11
    assert search.tool_definition().parameters["properties"] == {
        "q": {"type": "string"}
    }
    assert create.tool_definition().parameters == {"type": "object", "properties": {}}
    assert search.bind(MagicMock()).approval_required == frozenset()
    assert create.bind(MagicMock()).approval_required == frozenset({create.name})
