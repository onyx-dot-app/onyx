from typing import Any

from onyx.chat.prompt_builder.answer_prompt_builder import AnswerPromptBuilder
from onyx.tools.message import ToolCallSummary
from onyx.tools.models import ToolResponse
from onyx.tools.tool import Tool


class SimpleTestTool(Tool[dict]):
    """A simple test implementation of the Tool interface."""

    def __init__(self, tool_id: int = 1, name: str = "test_tool"):
        self._id = tool_id
        self._name = name

    @property
    def id(self) -> int:
        return self._id

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return "A simple test tool for testing purposes"

    @property
    def display_name(self) -> str:
        return "Test Tool"

    def tool_definition(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "The search query"}
                    },
                    "required": ["query"],
                },
            },
        }

    def build_tool_message_content(
        self, *args: ToolResponse
    ) -> str | list[str | dict[str, Any]]:
        return "Test tool response"

    def get_args_for_non_tool_calling_llm(
        self,
        query: str,
        history: list,
        llm,
        force_run: bool = False,
    ) -> dict[str, Any] | None:
        return {"query": query}

    def run(self, override_kwargs: dict | None = None, **llm_kwargs: Any):
        yield ToolResponse(id="test_response", response="Test response content")

    def final_result(self, *args: ToolResponse) -> dict:
        return {"result": "test_result"}

    def build_next_prompt(
        self,
        prompt_builder: AnswerPromptBuilder,
        tool_call_summary: ToolCallSummary,
        tool_responses: list[ToolResponse],
        using_tool_calling_llm: bool,
    ) -> AnswerPromptBuilder:
        return prompt_builder
