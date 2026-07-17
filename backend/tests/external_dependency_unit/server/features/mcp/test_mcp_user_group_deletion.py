"""Group deletion must clear MCP server grants (no ON DELETE CASCADE on
mcp_server__user_group.user_group_id)."""

from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from ee.onyx.db.user_group import prepare_user_group_for_deletion
from onyx.db.models import MCPServer
from onyx.db.models import MCPServer__UserGroup
from onyx.db.models import UserGroup

pytestmark = pytest.mark.usefixtures("enable_ee")


def test_prepare_group_deletion_clears_mcp_grants(db_session: Session) -> None:
    group = UserGroup(name=f"mcp_del_group_{uuid4().hex[:8]}", is_up_to_date=True)
    server = MCPServer(
        owner="admin@example.com",
        name=f"mcp_del_server_{uuid4().hex[:8]}",
        server_url="https://example.com/mcp",
        is_public=False,
    )
    db_session.add_all([group, server])
    db_session.commit()
    db_session.refresh(group)
    db_session.refresh(server)

    db_session.add(
        MCPServer__UserGroup(mcp_server_id=server.id, user_group_id=group.id)
    )
    db_session.commit()

    prepare_user_group_for_deletion(db_session, group.id)

    remaining = db_session.scalar(
        select(MCPServer__UserGroup).where(
            MCPServer__UserGroup.user_group_id == group.id
        )
    )
    assert remaining is None
