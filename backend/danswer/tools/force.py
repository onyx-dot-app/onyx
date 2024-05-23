from typing import Any

from langchain_core.messages import AIMessage
from langchain_core.messages import BaseMessage
from pydantic import BaseModel

from danswer.tools.tool import Tool


class ForceUseTool(BaseModel):
    tool_name: str
    args: dict[str, Any] | None = None

    def build_openai_tool_choice_dict(self) -> dict[str, Any]:
        """Build dict in the format that OpenAI expects which tells them to use this tool."""
        return {"type": "function", "function": {"name": self.tool_name}}


def modify_message_chain_for_force_use_tool(
    messages: list[BaseMessage], force_use_tool: ForceUseTool | None = None
) -> list[BaseMessage]:
    """NOTE: modifies `messages` in place."""
    if not force_use_tool:
        return messages

    for message in messages:
        if isinstance(message, AIMessage) and message.tool_calls:
            for tool_call in message.tool_calls:
                tool_call["args"] = force_use_tool.args or {}

    return messages


def filter_tools_for_force_tool_use(
    tools: list[Tool], force_use_tool: ForceUseTool | None = None
) -> list[Tool]:
    if not force_use_tool:
        return tools

    return [tool for tool in tools if tool.name() == force_use_tool.tool_name]
