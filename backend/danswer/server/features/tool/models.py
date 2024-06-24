from typing import Any

from pydantic import BaseModel

from danswer.db.models import Tool


class ToolSnapshot(BaseModel):
    id: int
    name: str
    description: str
    definition: dict[str, Any] | None
    in_code_tool_id: str | None

    @classmethod
    def from_model(cls, tool: Tool) -> "ToolSnapshot":
        return cls(
            id=tool.id,
            name=tool.name,
            description=tool.description,
            definition=tool.openapi_schema,
            in_code_tool_id=tool.in_code_tool_id,
        )
