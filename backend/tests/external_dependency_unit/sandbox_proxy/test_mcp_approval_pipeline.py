"""External-dependency-unit tests for the shared approval pipeline carrying an
MCP-server target.

Companion `mcp_server_id` columns let one approval/policy code path serve both
external apps and MCP servers. These pin the MCP half: an approval row attributes
to a server, session-grant lookups isolate by target, the exactly-one-target
constraint holds, and per-tool policy defaults to ASK.
"""

from __future__ import annotations

from collections.abc import Callable, Generator
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from onyx.db.enums import (
    ApprovalDecidedVia,
    ApprovalDecision,
    EndpointPolicy,
    GatedAppKind,
    MCPAuthenticationPerformer,
    MCPAuthenticationType,
    MCPTransport,
)
from onyx.db.gated_app import get_gated_app_id
from onyx.db.mcp import (
    create_mcp_server__no_commit,
    effective_mcp_tool_policy,
    get_mcp_tool_policies,
    set_mcp_tool_policies__no_commit,
    update_mcp_server__no_commit,
)
from onyx.db.models import BuildSession, GatedApp, MCPServer
from onyx.server.features.build.db import action_approval
from tests.external_dependency_unit.conftest import create_test_user

CraftServerFactory = Callable[..., MCPServer]

_ASK_ACTION = [
    {
        "action_type": "send_email",
        "display_name": "send_email",
        "description": "Call send_email.",
        "policy": EndpointPolicy.ASK.value,
    }
]


@pytest.fixture
def craft_server(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Generator[CraftServerFactory, None, None]:
    created: list[MCPServer] = []

    def _make() -> MCPServer:
        server = create_mcp_server__no_commit(
            owner_email="admin@example.com",
            name=f"test-mcp-{uuid4().hex[:8]}",
            description=None,
            server_url=f"https://api-{uuid4().hex[:8]}.example.com/mcp",
            auth_type=MCPAuthenticationType.API_TOKEN,
            transport=MCPTransport.STREAMABLE_HTTP,
            auth_performer=MCPAuthenticationPerformer.ADMIN,
            db_session=db_session,
        )
        update_mcp_server__no_commit(
            server_id=server.id, db_session=db_session, available_in_craft=True
        )
        db_session.commit()
        created.append(server)
        return server

    yield _make
    db_session.rollback()
    for server in created:
        db_session.delete(server)
    db_session.commit()


def _build_session(db_session: Session, user_id: object) -> BuildSession:
    session = BuildSession(user_id=user_id)
    db_session.add(session)
    db_session.commit()
    return session


def test_mcp_approval_row_round_trips_and_isolates_by_target(
    db_session: Session, craft_server: CraftServerFactory
) -> None:
    user = create_test_user(db_session, "mcp_pipeline_grant")
    session = _build_session(db_session, user.id)
    server = craft_server()

    action_approval.insert_action_approval(
        db_session,
        session_id=session.id,
        actions=list(_ASK_ACTION),
        app_name=server.name,
        payload={"method": "tools/call"},
        target=(GatedAppKind.MCP_SERVER, server.id),
        decision=ApprovalDecision.APPROVED,
        decided_via=ApprovalDecidedVia.SESSION_GRANT,
    )
    db_session.commit()

    granted = action_approval.list_session_grant_action_approvals(
        db_session,
        session_id=session.id,
        gated_app_id=get_gated_app_id(db_session, GatedAppKind.MCP_SERVER, server.id),
    )
    assert len(granted) == 1
    assert granted[0].gated_app is not None
    assert granted[0].gated_app.kind is GatedAppKind.MCP_SERVER
    assert granted[0].gated_app.target_id == server.id
    assert granted[0].gated_app.external_app_id is None

    # A grant for the same numeric id but the external-app catalog must not match.
    assert (
        action_approval.list_session_grant_action_approvals(
            db_session,
            session_id=session.id,
            gated_app_id=get_gated_app_id(
                db_session, GatedAppKind.EXTERNAL_APP, server.id
            ),
        )
        == []
    )


def test_gated_app_rejects_two_targets(
    db_session: Session, craft_server: CraftServerFactory
) -> None:
    # The single-target invariant lives on the gated_app identity row; the
    # consumer tables carry only a gated_app_id, so two targets is unrepresentable
    # there by construction.
    server = craft_server()

    db_session.add(
        GatedApp(
            external_app_id=1,
            mcp_server_id=server.id,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_mcp_tool_policies_default_ask_and_reflect_overrides(
    db_session: Session, craft_server: CraftServerFactory
) -> None:
    server = craft_server()
    assert get_mcp_tool_policies(server.id, db_session) == {}
    assert effective_mcp_tool_policy("anything", {}) is EndpointPolicy.ASK

    set_mcp_tool_policies__no_commit(
        server.id,
        {"read_inbox": EndpointPolicy.ALWAYS, "wipe": EndpointPolicy.DENY},
        db_session,
    )
    db_session.commit()

    stored = get_mcp_tool_policies(server.id, db_session)
    assert stored == {
        "read_inbox": EndpointPolicy.ALWAYS,
        "wipe": EndpointPolicy.DENY,
    }
    assert effective_mcp_tool_policy("read_inbox", stored) is EndpointPolicy.ALWAYS
    assert effective_mcp_tool_policy("wipe", stored) is EndpointPolicy.DENY
    assert effective_mcp_tool_policy("unset_tool", stored) is EndpointPolicy.ASK

    # Re-setting replaces the prior rows rather than colliding on the unique key.
    set_mcp_tool_policies__no_commit(
        server.id, {"read_inbox": EndpointPolicy.ASK}, db_session
    )
    db_session.commit()
    assert get_mcp_tool_policies(server.id, db_session) == {
        "read_inbox": EndpointPolicy.ASK
    }
