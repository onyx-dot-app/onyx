from typing import Type

from sqlalchemy.orm import Session

from danswer.db.models import Tool as ToolDBModel
from danswer.tools.built_in_tools import get_built_in_tool_by_id
from danswer.tools.tool import Tool


def get_tool_cls(tool: ToolDBModel, db_session: Session) -> Type[Tool]:
    # Currently only support built-in tools
    return get_built_in_tool_by_id(tool.id, db_session)
