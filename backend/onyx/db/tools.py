from typing import Any
from typing import cast
from typing import Type
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db.models import Tool
from onyx.server.features.tool.models import Header
from onyx.tools.built_in_tools import BUILT_IN_TOOL_TYPES
from onyx.utils.headers import HeaderItemDict
from onyx.utils.logger import setup_logger

if TYPE_CHECKING:
    pass

logger = setup_logger()


def get_tools(db_session: Session, *, only_enabled: bool = False) -> list[Tool]:
    query = select(Tool)
    if only_enabled:
        query = query.where(Tool.enabled.is_(True))
    return list(db_session.scalars(query).all())


def get_tools_by_mcp_server_id(
    mcp_server_id: int,
    db_session: Session,
    *,
    only_enabled: bool = False,
) -> list[Tool]:
    query = select(Tool).where(Tool.mcp_server_id == mcp_server_id)
    if only_enabled:
        query = query.where(Tool.enabled.is_(True))
    return list(db_session.scalars(query).all())


def get_tool_by_id(tool_id: int, db_session: Session) -> Tool:
    tool = db_session.scalar(select(Tool).where(Tool.id == tool_id))
    if not tool:
        raise ValueError("Tool by specified id does not exist")
    return tool


def get_tool_by_name(tool_name: str, db_session: Session) -> Tool:
    tool = db_session.scalar(select(Tool).where(Tool.name == tool_name))
    if not tool:
        raise ValueError("Tool by specified name does not exist")
    return tool


def create_tool__no_commit(
    name: str,
    description: str | None,
    openapi_schema: dict[str, Any] | None,
    custom_headers: list[Header] | None,
    user_id: UUID | None,
    db_session: Session,
    passthrough_auth: bool,
    *,
    mcp_server_id: int | None = None,
    enabled: bool = True,
) -> Tool:
    new_tool = Tool(
        name=name,
        description=description,
        in_code_tool_id=None,
        openapi_schema=openapi_schema,
        custom_headers=(
            [header.model_dump() for header in custom_headers] if custom_headers else []
        ),
        user_id=user_id,
        passthrough_auth=passthrough_auth,
        mcp_server_id=mcp_server_id,
        enabled=enabled,
    )
    db_session.add(new_tool)
    db_session.flush()  # Don't commit yet, let caller decide when to commit
    return new_tool


def update_tool(
    tool_id: int,
    name: str | None,
    description: str | None,
    openapi_schema: dict[str, Any] | None,
    custom_headers: list[Header] | None,
    user_id: UUID | None,
    db_session: Session,
    passthrough_auth: bool | None,
) -> Tool:
    tool = get_tool_by_id(tool_id, db_session)
    if tool is None:
        raise ValueError(f"Tool with ID {tool_id} does not exist")

    if name is not None:
        tool.name = name
    if description is not None:
        tool.description = description
    if openapi_schema is not None:
        tool.openapi_schema = openapi_schema
    if user_id is not None:
        tool.user_id = user_id
    if custom_headers is not None:
        tool.custom_headers = [
            cast(HeaderItemDict, header.model_dump()) for header in custom_headers
        ]
    if passthrough_auth is not None:
        tool.passthrough_auth = passthrough_auth
    db_session.commit()

    return tool


def delete_tool__no_commit(tool_id: int, db_session: Session) -> None:
    tool = get_tool_by_id(tool_id, db_session)
    if tool is None:
        raise ValueError(f"Tool with ID {tool_id} does not exist")

    db_session.delete(tool)
    db_session.flush()  # Don't commit yet, let caller decide when to commit


def get_builtin_tool(
    db_session: Session,
    tool_type: Type[BUILT_IN_TOOL_TYPES],
) -> Tool:
    """
    Retrieves a built-in tool from the database based on the tool type.
    """
    # local import to avoid circular import. DB layer should not depend on tools layer.
    from onyx.tools.built_in_tools import BUILT_IN_TOOL_MAP

    tool_id = next(
        (
            in_code_tool_id
            for in_code_tool_id, tool_cls in BUILT_IN_TOOL_MAP.items()
            if tool_cls.__name__ == tool_type.__name__
        ),
        None,
    )

    if not tool_id:
        raise RuntimeError(
            f"Tool type {tool_type.__name__} not found in the BUILT_IN_TOOLS list."
        )

    db_tool = db_session.execute(
        select(Tool).where(Tool.in_code_tool_id == tool_id)
    ).scalar_one_or_none()

    if not db_tool:
        raise RuntimeError(f"Tool type {tool_type.__name__} not found in the database.")

    return db_tool
