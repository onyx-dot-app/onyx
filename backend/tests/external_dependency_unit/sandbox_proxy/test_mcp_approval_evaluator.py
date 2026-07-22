"""External-dependency-unit tests for `McpRequestEvaluator` against a real DB.

Pins proxy-authoritative per-tool approvals: a craft MCP `tools/call` becomes an
`AllMatchedActions` targeting the server, carrying the tool's effective policy
(admin override else default ASK); protocol plumbing is ungated (``None``); an
unclassifiable body on a matched host is a DENY verdict so the gate fails closed.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Generator
from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.db.enums import (
    EndpointPolicy,
    GatedAppKind,
    MCPAuthenticationPerformer,
    MCPAuthenticationType,
    MCPTransport,
)
from onyx.db.gated_app import set_action_policies__no_commit
from onyx.db.mcp import (
    create_mcp_server__no_commit,
    update_mcp_server__no_commit,
)
from onyx.db.models import MCPServer
from onyx.sandbox_proxy.request_evaluator import (
    MCP_UNCLASSIFIABLE_ACTION_TYPE,
    McpRequestEvaluator,
)
from shared_configs.contextvars import POSTGRES_DEFAULT_SCHEMA
from tests.external_dependency_unit.conftest import create_test_user

CraftServerFactory = Callable[..., MCPServer]


@pytest.fixture
def craft_server(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Generator[CraftServerFactory, None, None]:
    created: list[MCPServer] = []

    def _make(
        *,
        host: str | None = None,
        path: str = "/mcp",
        available_in_craft: bool = True,
    ) -> MCPServer:
        server = create_mcp_server__no_commit(
            owner_email="admin@example.com",
            name=f"test-mcp-{uuid4().hex[:8]}",
            description=None,
            server_url=f"https://{host or _unique_host()}{path}",
            auth_type=MCPAuthenticationType.API_TOKEN,
            transport=MCPTransport.STREAMABLE_HTTP,
            auth_performer=MCPAuthenticationPerformer.ADMIN,
            db_session=db_session,
        )
        update_mcp_server__no_commit(
            server_id=server.id,
            db_session=db_session,
            available_in_craft=available_in_craft,
        )
        db_session.commit()
        created.append(server)
        return server

    yield _make
    db_session.rollback()
    for server in created:
        db_session.delete(server)
    db_session.commit()


def _unique_host() -> str:
    return f"api-{uuid4().hex[:8]}.example.com"


def _server_host(server: MCPServer) -> str:
    return server.server_url.split("://", 1)[1].split("/", 1)[0]


def _tool_call_body(*names: str) -> bytes:
    if len(names) == 1:
        payload: Any = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": names[0], "arguments": {}},
        }
    else:
        payload = [
            {"jsonrpc": "2.0", "id": i, "method": "tools/call", "params": {"name": n}}
            for i, n in enumerate(names)
        ]
    return json.dumps(payload).encode()


def _request(
    host: str,
    *,
    path: str = "/mcp",
    method: str = "POST",
    body: bytes = b"",
    scheme: str = "https",
    port: int = 443,
) -> MagicMock:
    req = MagicMock()
    req.host = host
    req.port = port
    req.scheme = scheme
    req.path = path
    req.method = method
    req.raw_content = body
    req.headers = {"content-type": "application/json"}
    return req


def _evaluate(request: MagicMock, user_id: Any) -> Any:
    return McpRequestEvaluator().evaluate(request, POSTGRES_DEFAULT_SCHEMA, user_id)


def test_tools_call_defaults_to_ask(
    db_session: Session, craft_server: CraftServerFactory
) -> None:
    user = create_test_user(db_session, "mcp_eval_ask")
    server = craft_server()

    matched = _evaluate(
        _request(_server_host(server), body=_tool_call_body("send_email")), user.id
    )
    assert matched is not None
    assert matched.target.key == (GatedAppKind.MCP_SERVER, server.id)
    assert matched.app_name == server.name
    assert [a.action_type for a in matched.actions] == ["send_email"]
    assert matched.governing_action.policy is EndpointPolicy.ASK
    # The JSON-RPC body is carried through for the approval card.
    assert matched.payload["method"] == "tools/call"


@pytest.mark.parametrize("override", [EndpointPolicy.ALWAYS, EndpointPolicy.DENY])
def test_admin_tool_override_is_reflected(
    db_session: Session,
    craft_server: CraftServerFactory,
    override: EndpointPolicy,
) -> None:
    user = create_test_user(db_session, f"mcp_eval_override_{override.value}")
    server = craft_server()
    set_action_policies__no_commit(
        db_session, GatedAppKind.MCP_SERVER, server.id, {"send_email": override}
    )
    db_session.commit()

    matched = _evaluate(
        _request(_server_host(server), body=_tool_call_body("send_email")), user.id
    )
    assert matched is not None
    assert matched.governing_action.policy is override
    # A tool without an override still defaults to ASK.
    other = _evaluate(
        _request(_server_host(server), body=_tool_call_body("read_inbox")), user.id
    )
    assert other is not None
    assert other.governing_action.policy is EndpointPolicy.ASK


@pytest.mark.parametrize("method", ["initialize", "tools/list", "notifications/x"])
def test_protocol_plumbing_is_not_gated(
    db_session: Session, craft_server: CraftServerFactory, method: str
) -> None:
    user = create_test_user(db_session, "mcp_eval_plumbing")
    server = craft_server()
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method}).encode()
    assert _evaluate(_request(_server_host(server), body=body), user.id) is None


def test_get_stream_is_not_gated(
    db_session: Session, craft_server: CraftServerFactory
) -> None:
    user = create_test_user(db_session, "mcp_eval_get")
    server = craft_server()
    req = _request(_server_host(server), method="GET", body=b"")
    assert _evaluate(req, user.id) is None


def test_unclassifiable_body_on_matched_host_is_denied(
    db_session: Session, craft_server: CraftServerFactory
) -> None:
    user = create_test_user(db_session, "mcp_eval_unclassifiable")
    server = craft_server()
    matched = _evaluate(_request(_server_host(server), body=b"<not-json>"), user.id)
    assert matched is not None
    assert matched.governing_action.policy is EndpointPolicy.DENY
    assert matched.governing_action.action_type == MCP_UNCLASSIFIABLE_ACTION_TYPE
    assert matched.target.key == (GatedAppKind.MCP_SERVER, server.id)


def test_request_outside_prefix_is_not_attributed(
    db_session: Session, craft_server: CraftServerFactory
) -> None:
    user = create_test_user(db_session, "mcp_eval_prefix")
    server = craft_server(path="/mcp")
    # A sibling path on the same host isn't the MCP endpoint — evaluator defers;
    # the resolver fails it closed at injection time.
    req = _request(_server_host(server), path="/other", body=_tool_call_body("x"))
    assert _evaluate(req, user.id) is None


def test_non_craft_enabled_server_is_not_attributed(
    db_session: Session, craft_server: CraftServerFactory
) -> None:
    user = create_test_user(db_session, "mcp_eval_disabled")
    server = craft_server(available_in_craft=False)
    req = _request(_server_host(server), body=_tool_call_body("x"))
    assert _evaluate(req, user.id) is None


def test_batched_tool_calls_sorted_strictest_first(
    db_session: Session, craft_server: CraftServerFactory
) -> None:
    user = create_test_user(db_session, "mcp_eval_batch")
    server = craft_server()
    set_action_policies__no_commit(
        db_session,
        GatedAppKind.MCP_SERVER,
        server.id,
        {"safe_read": EndpointPolicy.ALWAYS, "danger_write": EndpointPolicy.DENY},
    )
    db_session.commit()

    matched = _evaluate(
        _request(
            _server_host(server), body=_tool_call_body("safe_read", "danger_write")
        ),
        user.id,
    )
    assert matched is not None
    # DENY (strictest) governs; both tools are represented.
    assert matched.governing_action.action_type == "danger_write"
    assert matched.governing_action.policy is EndpointPolicy.DENY
    assert {a.action_type for a in matched.actions} == {"safe_read", "danger_write"}


def test_evaluator_failure_after_attribution_denies(
    db_session: Session,
    craft_server: CraftServerFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An evaluator crash on an attributed MCP request must yield a DENY verdict:
    the gate treats evaluator exceptions as off-catalog and the MCP resolver
    claims by host, so a raise would forward the request with credentials."""
    user = create_test_user(db_session, "mcp_eval_crash")
    server = craft_server()

    import onyx.sandbox_proxy.request_evaluator as re_mod

    def _boom(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("policy lookup failed")

    monkeypatch.setattr(re_mod, "get_action_policies", _boom)

    matched = _evaluate(
        _request(_server_host(server), body=_tool_call_body("send_email")), user.id
    )
    assert matched is not None
    assert matched.governing_action.policy is EndpointPolicy.DENY
    assert matched.governing_action.action_type == MCP_UNCLASSIFIABLE_ACTION_TYPE
    assert matched.target.key == (GatedAppKind.MCP_SERVER, server.id)


def test_duplicate_tool_calls_surface_multiplicity(
    db_session: Session, craft_server: CraftServerFactory
) -> None:
    """A batch invoking one tool twice yields a single action (grants key by
    tool name) whose description carries the invocation count, so the approval
    card doesn't understate the request."""
    user = create_test_user(db_session, "mcp_eval_dupes")
    server = craft_server()

    matched = _evaluate(
        _request(
            _server_host(server), body=_tool_call_body("send_email", "send_email")
        ),
        user.id,
    )
    assert matched is not None
    assert [a.action_type for a in matched.actions] == ["send_email"]
    assert "invokes it 2 times" in matched.governing_action.description
