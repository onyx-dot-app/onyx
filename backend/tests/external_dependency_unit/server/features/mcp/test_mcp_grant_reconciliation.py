"""MCP grant updates preserve share dimensions omitted from the request."""

from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.auth.schemas import UserRole
from onyx.db.models import MCPServer
from onyx.db.models import MCPServer__User
from onyx.db.models import MCPServer__UserGroup
from onyx.db.models import UserGroup
from onyx.server.features.mcp.api import update_mcp_server_simple
from onyx.server.features.mcp.models import MCPServerSimpleUpdateRequest
from tests.external_dependency_unit.conftest import create_test_user


def test_omitted_mcp_grant_dimensions_are_preserved(
    db_session: Session,
    enable_ee: None,  # noqa: ARG001
) -> None:
    user = create_test_user(db_session, "mcp_grant_reconcile", role=UserRole.ADMIN)
    group = UserGroup(name=f"mcp_grant_{uuid4().hex[:8]}", is_up_to_date=True)
    server = MCPServer(
        owner=user.email,
        name=f"mcp_grant_server_{uuid4().hex[:8]}",
        server_url="https://example.com/mcp",
        is_public=False,
    )
    db_session.add_all([group, server])
    db_session.flush()
    db_session.add_all(
        [
            MCPServer__User(mcp_server_id=server.id, user_id=user.id),
            MCPServer__UserGroup(
                mcp_server_id=server.id,
                user_group_id=group.id,
            ),
        ]
    )
    db_session.flush()

    update_mcp_server_simple(
        server_id=server.id,
        request=MCPServerSimpleUpdateRequest(is_public=False, groups=[]),
        db_session=db_session,
        user=user,
    )
    assert (
        db_session.scalar(
            select(MCPServer__User).where(MCPServer__User.mcp_server_id == server.id)
        )
        is not None
    )
    assert (
        db_session.scalar(
            select(MCPServer__UserGroup).where(
                MCPServer__UserGroup.mcp_server_id == server.id
            )
        )
        is None
    )

    db_session.add(
        MCPServer__UserGroup(mcp_server_id=server.id, user_group_id=group.id)
    )
    db_session.flush()
    update_mcp_server_simple(
        server_id=server.id,
        request=MCPServerSimpleUpdateRequest(is_public=False, users=[]),
        db_session=db_session,
        user=user,
    )
    assert (
        db_session.scalar(
            select(MCPServer__User).where(MCPServer__User.mcp_server_id == server.id)
        )
        is None
    )
    assert (
        db_session.scalar(
            select(MCPServer__UserGroup).where(
                MCPServer__UserGroup.mcp_server_id == server.id
            )
        )
        is not None
    )
