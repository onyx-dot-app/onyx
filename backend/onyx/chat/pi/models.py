"""Validated messages at the agent-service boundary."""

from typing import Any, Literal

from pydantic import BaseModel, Field


class PiToolCall(BaseModel):
    id: str
    name: str
    arguments: dict[str, Any]


class PiTextContent(BaseModel):
    type: Literal["text"]
    text: str


class PiToolResult(BaseModel):
    tool_call_id: str = Field(alias="toolCallId")
    tool_name: str = Field(alias="toolName")
    content: list[PiTextContent]
    is_error: bool = Field(alias="isError")
