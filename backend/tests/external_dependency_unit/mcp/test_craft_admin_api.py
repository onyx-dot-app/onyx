"""Craft-facing MCP admin API (ext-dep): per-tool policy PATCH round-trip and
the user-facing disconnect endpoint, against a real DB."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.auth.schemas import UserRole
from onyx.db.enums import (
    EndpointPolicy,
    GatedAppKind,
    MCPAuthenticationPerformer,
    MCPAuthenticationType,
    MCPTransport,
)
from onyx.db.gated_app import get_action_policies
from onyx.db.mcp import (
    create_mcp_server__no_commit,
    get_user_connection_config,
    upsert_user_connection_config,
)
from onyx.db.models import MCPServer, Tool
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.mcp import api as mcp_api
from onyx.server.features.mcp.models import (
    MCPConnectionData,
    MCPServerSimpleUpdateRequest,
)
from tests.external_dependency_unit.conftest import create_test_user


def _make_server(db_session: Session, *, tool_names: list[str]) -> MCPServer:
    server = create_mcp_server__no_commit(
        owner_email="admin@example.com",
        name=f"craft-admin-mcp-{uuid4().hex[:8]}",
        description=None,
        server_url=f"https://api-{uuid4().hex[:8]}.example.com/mcp",
        auth_type=MCPAuthenticationType.API_TOKEN,
        transport=MCPTransport.STREAMABLE_HTTP,
        auth_performer=MCPAuthenticationPerformer.PER_USER,
        db_session=db_session,
    )
    for name in tool_names:
        db_session.add(Tool(name=name, mcp_server_id=server.id, enabled=True))
    db_session.commit()
    return server


def test_tool_policies_patch_round_trip(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    admin = create_test_user(db_session, "mcp_admin", role=UserRole.ADMIN)
    server = _make_server(db_session, tool_names=["send_email", "list_inbox"])

    resp = mcp_api.update_mcp_server_simple(
        server.id,
        MCPServerSimpleUpdateRequest(tool_policies={"send_email": EndpointPolicy.DENY}),
        db_session,
        admin,
    )
    assert resp.tool_policies == {"send_email": EndpointPolicy.DENY}
    # Sparse: the unlisted tool has no stored override (effective default ASK).
    assert get_action_policies(db_session, GatedAppKind.MCP_SERVER, server.id) == {
        "send_email": EndpointPolicy.DENY
    }

    # Default (ASK) entries are canonicalized away at the boundary, so a client
    # may send a full map without persisting redundant rows.
    resp = mcp_api.update_mcp_server_simple(
        server.id,
        MCPServerSimpleUpdateRequest(
            tool_policies={
                "send_email": EndpointPolicy.DENY,
                "list_inbox": EndpointPolicy.ASK,
            }
        ),
        db_session,
        admin,
    )
    assert get_action_policies(db_session, GatedAppKind.MCP_SERVER, server.id) == {
        "send_email": EndpointPolicy.DENY
    }

    # Full replace: an empty map clears every override.
    mcp_api.update_mcp_server_simple(
        server.id,
        MCPServerSimpleUpdateRequest(tool_policies={}),
        db_session,
        admin,
    )
    assert get_action_policies(db_session, GatedAppKind.MCP_SERVER, server.id) == {}

    # Unknown tool names are rejected.
    with pytest.raises(OnyxError):
        mcp_api.update_mcp_server_simple(
            server.id,
            MCPServerSimpleUpdateRequest(
                tool_policies={"not_a_tool": EndpointPolicy.ALWAYS}
            ),
            db_session,
            admin,
        )


def test_disconnect_removes_only_callers_credentials(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    user_a = create_test_user(db_session, "mcp_disc_a")
    user_b = create_test_user(db_session, "mcp_disc_b")
    server = _make_server(db_session, tool_names=["t"])
    for user in (user_a, user_b):
        upsert_user_connection_config(
            server_id=server.id,
            user_email=user.email,
            config_data=MCPConnectionData(
                headers={"Authorization": "Bearer user-token"}
            ),
            db_session=db_session,
        )
    db_session.commit()

    resp = mcp_api.delete_user_credentials(server.id, db_session, user_a)
    assert resp.success is True
    assert get_user_connection_config(server.id, user_a.email, db_session) is None
    assert get_user_connection_config(server.id, user_b.email, db_session) is not None
