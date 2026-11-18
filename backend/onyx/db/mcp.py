from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db.models import (
    MCPServer,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()


def get_mcp_server_by_id(
    server_id: int, db_session: Session, *, for_update: bool = False
) -> MCPServer:
    """Get a server, optionally locking it for an atomic configuration update."""
    stmt = select(MCPServer).where(MCPServer.id == server_id)
    if for_update:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    server = db_session.scalar(stmt)
    if not server:
        raise ValueError("MCP server by specified id does not exist")
    return server
