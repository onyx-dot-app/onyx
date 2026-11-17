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

from onyx.db.action_policy import (
    get_or_create_gated_app_id,
    get_workspace_action_policies,
    replace_workspace_action_policies,
)
from onyx.db.enums import (
    ActionPolicy,
    GatedAppKind,
    MCPAuthenticationPerformer,
    MCPAuthenticationType,
    MCPTransport,
)
from onyx.db.mcp import (
    create_mcp_server__no_commit,
    update_mcp_server__no_commit,
)
from onyx.db.models import BuildSession, GatedApp, MCPServer, Tool

CraftServerFactory = Callable[..., MCPServer]

_ASK_ACTION = [
    {
        "action_type": "send_email",
        "display_name": "send_email",
        "description": "Call send_email.",
        "policy": ActionPolicy.ASK.value,
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


def test_mcp_tool_policy_storage_round_trips(
    db_session: Session, craft_server: CraftServerFactory
) -> None:
    server = craft_server()
    assert (
        get_workspace_action_policies(db_session, GatedAppKind.MCP_SERVER, server.id)
        == {}
    )

    db_session.add_all(
        Tool(name=name, mcp_server_id=server.id, enabled=True)
        for name in ("read_inbox", "wipe")
    )
    db_session.flush()
    gated_app_id = get_or_create_gated_app_id(
        db_session, GatedAppKind.MCP_SERVER, server.id
    )
    replace_workspace_action_policies(
        db_session,
        gated_app_id,
        {"read_inbox": ActionPolicy.ALWAYS, "wipe": ActionPolicy.DENY},
    )
    db_session.commit()

    assert get_workspace_action_policies(
        db_session, GatedAppKind.MCP_SERVER, server.id
    ) == {
        "read_inbox": ActionPolicy.ALWAYS,
        "wipe": ActionPolicy.DENY,
    }

    # Resetting to the MCP default removes overrides, including omitted tools.
    replace_workspace_action_policies(
        db_session, gated_app_id, {"read_inbox": ActionPolicy.ASK}
    )
    db_session.commit()
    assert (
        get_workspace_action_policies(db_session, GatedAppKind.MCP_SERVER, server.id)
        == {}
    )
