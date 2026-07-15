from uuid import UUID

from sqlalchemy.orm import Session

from onyx.db.models import MCPServer__User
from onyx.db.models import MCPServer__UserGroup


def make_mcp_server_private(
    server_id: int,
    user_ids: list[UUID] | None,
    group_ids: list[int] | None,
    db_session: Session,
) -> None:
    """Replace provided grant dimensions. None preserves; an empty list clears."""
    if user_ids is not None:
        db_session.query(MCPServer__User).filter(
            MCPServer__User.mcp_server_id == server_id
        ).delete(synchronize_session="fetch")
        for user_id in user_ids:
            db_session.add(MCPServer__User(mcp_server_id=server_id, user_id=user_id))

    if group_ids is not None:
        db_session.query(MCPServer__UserGroup).filter(
            MCPServer__UserGroup.mcp_server_id == server_id
        ).delete(synchronize_session="fetch")
        for group_id in group_ids:
            db_session.add(
                MCPServer__UserGroup(mcp_server_id=server_id, user_group_id=group_id)
            )
