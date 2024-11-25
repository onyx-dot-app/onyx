from typing import Any
from typing import cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from danswer.db.models import Tool
from danswer.server.features.tool.models import Header
from danswer.utils.headers import HeaderItemDict
from danswer.utils.logger import setup_logger

logger = setup_logger()


def get_tools(db_session: Session) -> list[Tool]:
    return list(db_session.scalars(select(Tool)).all())


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


def create_tool(
    name: str,
    description: str | None,
    openapi_schema: dict[str, Any] | None,
    custom_headers: list[Header] | None,
    user_id: UUID | None,
    db_session: Session,
) -> Tool:
    new_tool = Tool(
        name=name,
        description=description,
        in_code_tool_id=None,
        openapi_schema=openapi_schema,
        custom_headers=[header.model_dump() for header in custom_headers]
        if custom_headers
        else [],
        user_id=user_id,
    )
    db_session.add(new_tool)
    db_session.commit()
    return new_tool


def update_tool(
    tool_id: int,
    name: str | None,
    description: str | None,
    openapi_schema: dict[str, Any] | None,
    custom_headers: list[Header] | None,
    user_id: UUID | None,
    db_session: Session,
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
    db_session.commit()

    return tool


def delete_tool(tool_id: int, db_session: Session) -> None:
    tool = get_tool_by_id(tool_id, db_session)
    if tool is None:
        raise ValueError(f"Tool with ID {tool_id} does not exist")

    db_session.delete(tool)
    db_session.commit()
