from typing import Any

from pydantic import BaseModel


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
        return {"type": "function", "name": self.tool_name}
