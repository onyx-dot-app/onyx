"""Security gate: a user cannot attach a restricted MCP server's tools to an
agent by passing tool IDs directly. `upsert_persona` must reject it before
the persona is written."""

import pytest
from sqlalchemy.orm import Session

from onyx.auth.schemas import UserRole
from onyx.db.models import MCPServer
from onyx.db.models import MCPServer__UserGroup
from onyx.db.models import Tool
from onyx.db.models import User__UserGroup
from onyx.db.models import UserGroup
from onyx.db.persona import upsert_persona
from tests.external_dependency_unit.conftest import create_test_user


def _restricted_server_with_tool(
    db_session: Session, group: UserGroup
) -> tuple[MCPServer, Tool]:
    server = MCPServer(
        owner="admin@example.com",
        name="gate_restricted_server",
        server_url="https://example.com/mcp",
        is_public=False,
    )
    db_session.add(server)
    db_session.commit()
    db_session.refresh(server)

    db_session.add(
        MCPServer__UserGroup(mcp_server_id=server.id, user_group_id=group.id)
    )
    tool = Tool(name="gate_restricted_tool", mcp_server_id=server.id)
    db_session.add(tool)
    db_session.commit()
    db_session.refresh(tool)
    return server, tool


def test_non_member_cannot_attach_restricted_mcp_tool(db_session: Session) -> None:
    outsider = create_test_user(db_session, "gate_outsider", role=UserRole.BASIC)
    group = UserGroup(name="gate_group", is_up_to_date=True)
    db_session.add(group)
    db_session.commit()
    db_session.refresh(group)

    _server, tool = _restricted_server_with_tool(db_session, group)

    with pytest.raises(ValueError, match="do not have access"):
        upsert_persona(
            user=outsider,
            name="gate-test-agent",
            description="should be rejected",
            starter_messages=None,
            system_prompt=None,
            task_prompt=None,
            datetime_aware=None,
            is_public=False,
            tool_ids=[tool.id],
            db_session=db_session,
        )


def test_member_passes_the_mcp_access_gate(db_session: Session) -> None:
    member = create_test_user(db_session, "gate_member", role=UserRole.BASIC)
    group = UserGroup(name="gate_group_member", is_up_to_date=True)
    db_session.add(group)
    db_session.commit()
    db_session.refresh(group)
    db_session.add(User__UserGroup(user_id=member.id, user_group_id=group.id))
    db_session.commit()

    _server, tool = _restricted_server_with_tool(db_session, group)

    # A member must not be blocked by the MCP access gate. Other upsert
    # requirements are out of scope, so we only assert the gate doesn't fire.
    try:
        upsert_persona(
            user=member,
            name="gate-member-agent",
            description="should pass the gate",
            starter_messages=None,
            system_prompt=None,
            task_prompt=None,
            datetime_aware=None,
            is_public=False,
            tool_ids=[tool.id],
            db_session=db_session,
        )
    except ValueError as exc:
        assert "do not have access" not in str(exc)
