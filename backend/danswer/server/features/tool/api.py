from fastapi import APIRouter
from fastapi import Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from danswer.auth.users import current_user
from danswer.db.engine import get_session
from danswer.db.models import Tool
from danswer.db.models import User


router = APIRouter(prefix="/tool")


class ToolSnapshot(BaseModel):
    id: int
    name: str
    description: str
    in_code_tool_id: str | None

    @classmethod
    def from_model(cls, tool: Tool) -> "ToolSnapshot":
        return cls(
            id=tool.id,
            name=tool.name,
            description=tool.description,
            in_code_tool_id=tool.in_code_tool_id,
        )


@router.get("")
def list_tools(
    db_session: Session = Depends(get_session),
    _: User | None = Depends(current_user),
) -> list[ToolSnapshot]:
    tools = db_session.execute(select(Tool)).scalars().all()
    return [ToolSnapshot.from_model(tool) for tool in tools]
