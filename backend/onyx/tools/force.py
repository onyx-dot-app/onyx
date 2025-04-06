from typing import Any

from pydantic import BaseModel

from onyx.tools.tool import Tool


class ForceUseTool(BaseModel):
    # Could be not a forced usage of the tool but still have args, in which case
    # if the tool is called, then those args are applied instead of what the LLM
    # wanted to call it with
    force_use: bool
    tool_name: str
    args: dict[str, Any] | None = None
    override_kwargs: Any = None  # This will hold tool-specific override kwargs

    def build_openai_tool_choice_dict(self) -> dict[str, Any]:
        """Build dict in the format that OpenAI expects which tells them to use this tool."""
        return {"type": "function", "function": {"name": self.tool_name}}


def filter_tools_for_force_tool_use(
    tools: list[Tool], force_use_tool: ForceUseTool
) -> list[Tool]:
    if not force_use_tool.force_use:
        return tools

    return [tool for tool in tools if tool.name == force_use_tool.tool_name]
