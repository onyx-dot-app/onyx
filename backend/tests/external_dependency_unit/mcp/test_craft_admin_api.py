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
    SandboxStatus,
)
from onyx.db.gated_app import get_action_policies
from onyx.db.mcp import (
    add_user_to_mcp_server,
    affected_user_ids_for_mcp_server,
    create_mcp_server__no_commit,
    get_user_connection_config,
    update_mcp_server__no_commit,
    upsert_user_connection_config,
)
from onyx.db.models import MCPServer, Tool
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.build.sandbox.util.mcp_config import (
    craft_mcp_fingerprint,
    resolve_craft_mcp_servers,
)
from onyx.server.features.mcp import api as mcp_api
from onyx.server.features.mcp.models import (
    MCPConnectionData,
    MCPServerSimpleUpdateRequest,
)
from tests.external_dependency_unit.conftest import create_test_user
from tests.external_dependency_unit.craft.db_helpers import make_sandbox


def _make_craft_server(
    db_session: Session, *, owner_email: str, is_public: bool
) -> MCPServer:
    server = create_mcp_server__no_commit(
        owner_email=owner_email,
        name=f"craft-{uuid4().hex[:8]}",
        description=None,
        server_url=f"https://api-{uuid4().hex[:8]}.example.com/mcp",
        auth_type=MCPAuthenticationType.API_TOKEN,
        transport=MCPTransport.STREAMABLE_HTTP,
        auth_performer=MCPAuthenticationPerformer.PER_USER,
        db_session=db_session,
        is_public=is_public,
    )
    update_mcp_server__no_commit(
        server_id=server.id, db_session=db_session, available_in_craft=True
    )
    db_session.commit()
    return server


def test_affected_user_ids_cover_direct_owner_admin_not_unrelated(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    owner = create_test_user(db_session, "aff_owner")
    direct = create_test_user(db_session, "aff_direct")
    unrelated = create_test_user(db_session, "aff_unrelated")
    admin = create_test_user(db_session, "aff_admin", role=UserRole.ADMIN)
    for u in (owner, direct, unrelated, admin):
        make_sandbox(db_session, u, status=SandboxStatus.RUNNING)

    server = _make_craft_server(db_session, owner_email=owner.email, is_public=False)
    add_user_to_mcp_server(server.id, direct.id, db_session)
    db_session.commit()

    affected = affected_user_ids_for_mcp_server(server, db_session)
    assert direct.id in affected
    assert owner.id in affected
    # Admins bypass the access filter (so they see every craft server) and must
    # be reloaded even for a private server they aren't explicitly shared on.
    assert admin.id in affected
    assert unrelated.id not in affected

    # A public server reaches every running-sandbox user.
    server.is_public = True
    db_session.flush()
    public_affected = affected_user_ids_for_mcp_server(server, db_session)
    assert {owner.id, direct.id, unrelated.id, admin.id} <= public_affected


def test_public_to_private_recipient_union_covers_losing_user(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    # The recipient set differs across a public -> private transition; the union
    # of pre- and post-change recipients that update_mcp_server_simple reloads
    # must still cover a user who was reachable only while the server was public.
    # (The transition itself is EE-gated at the API layer, so this exercises the
    # db-level recipient calc the endpoint unions over.)
    losing = create_test_user(db_session, "union_losing")
    make_sandbox(db_session, losing, status=SandboxStatus.RUNNING)
    server = _make_craft_server(
        db_session, owner_email="union_owner@example.com", is_public=True
    )

    before = affected_user_ids_for_mcp_server(server, db_session)
    assert losing.id in before  # public reaches every running-sandbox user

    server.is_public = False
    db_session.flush()
    after = affected_user_ids_for_mcp_server(server, db_session)
    assert losing.id not in after  # private no longer reaches them

    # The reload set is the union, so the losing user is still reloaded.
    assert losing.id in (before | after)


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


def test_delete_server_restamps_affected_running_sandbox(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    # Deleting a craft server must restamp affected users' running sandboxes so
    # their live sessions detect staleness and drop the server on the next turn.
    admin = create_test_user(db_session, "del_reload_admin", role=UserRole.ADMIN)
    sandbox = make_sandbox(db_session, admin, status=SandboxStatus.RUNNING)
    server = _make_craft_server(db_session, owner_email=admin.email, is_public=True)

    fp_before = craft_mcp_fingerprint(resolve_craft_mcp_servers(db_session, admin))
    sandbox.mcp_config_hash = fp_before
    db_session.commit()

    assert mcp_api.delete_mcp_server_admin(server.id, db_session, admin) == {
        "success": True
    }

    # Restamped to the post-delete fingerprint (the server dropped out of the
    # resolved craft set), so the live session detects staleness next turn.
    db_session.refresh(sandbox)
    assert sandbox.mcp_config_hash != fp_before
    assert sandbox.mcp_config_hash == craft_mcp_fingerprint(
        resolve_craft_mcp_servers(db_session, admin)
    )


def test_disconnect_restamps_callers_running_sandbox(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    # Disconnecting flips the server's authenticated flag (tool discovery is
    # credential-gated), so the caller's running sandbox must be restamped.
    user = create_test_user(db_session, "disc_reload")
    sandbox = make_sandbox(db_session, user, status=SandboxStatus.RUNNING)
    server = _make_craft_server(db_session, owner_email=user.email, is_public=True)
    upsert_user_connection_config(
        server_id=server.id,
        user_email=user.email,
        config_data=MCPConnectionData(headers={"Authorization": "Bearer user-token"}),
        db_session=db_session,
    )
    db_session.commit()

    fp_connected = craft_mcp_fingerprint(resolve_craft_mcp_servers(db_session, user))
    sandbox.mcp_config_hash = fp_connected
    db_session.commit()

    mcp_api.delete_user_credentials(server.id, db_session, user)

    db_session.refresh(sandbox)
    assert sandbox.mcp_config_hash != fp_connected
    assert sandbox.mcp_config_hash == craft_mcp_fingerprint(
        resolve_craft_mcp_servers(db_session, user)
    )
