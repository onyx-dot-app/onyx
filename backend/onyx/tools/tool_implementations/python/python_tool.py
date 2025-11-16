from collections.abc import Generator
from typing import Any

from sqlalchemy.orm import Session
from typing_extensions import override

from onyx.chat.prompt_builder.answer_prompt_builder import AnswerPromptBuilder
from onyx.llm.interfaces import LLM
from onyx.llm.models import PreviousMessage
from onyx.tools.message import ToolCallSummary
from onyx.tools.models import ToolResponse
from onyx.tools.tool import RunContextWrapper
from onyx.tools.tool import Tool
from onyx.utils.logger import setup_logger
from onyx.utils.special_types import JSON_ro


logger = setup_logger()

_GENERIC_ERROR_MESSAGE = "PythonTool should only be used by the Deep Research Agent with v2 tools, not via direct tool calling."


class PythonTool(Tool[None]):
    """
    Wrapper class for Python code execution tool.

    This class provides availability checking and integrates with the Tool infrastructure.
    Actual execution is handled by the v2 function-based implementation.
    """

    _NAME = "python"
    _DESCRIPTION = "Execute Python code in a secure, isolated environment. Never call this tool directly."
    # in the UI, call it `Analysis` for easier understanding of what is should primarily be used for
    _DISPLAY_NAME = "Analysis"

    def __init__(self, tool_id: int) -> None:
        self._id = tool_id

    @property
    def id(self) -> int:
        return self._id

    @property
    def name(self) -> str:
        return self._NAME

    @property
    def description(self) -> str:
        return self._DESCRIPTION

    @property
    def display_name(self) -> str:
        return self._DISPLAY_NAME

    @override
    @classmethod
    def is_available(cls, db_session: Session) -> bool:
        """
        Available if Code Interpreter service URL is configured.

        Only checks if CODE_INTERPRETER_BASE_URL is set - does not perform health check.
        Service failures will be handled gracefully at execution time.
        """
        from onyx.configs.app_configs import CODE_INTERPRETER_BASE_URL

        is_available = bool(CODE_INTERPRETER_BASE_URL)
        logger.info(
            "PythonTool.is_available() called: "
            f"CODE_INTERPRETER_BASE_URL={CODE_INTERPRETER_BASE_URL!r}, "
            f"returning {is_available}"
        )

        if not is_available:
            return False

        return True

    def tool_definition(self) -> dict:
        """Tool definition for LLMs that support explicit tool calling."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "code": {
                            "type": "string",
                            "description": "Python source code to execute",
                        },
                    },
                    "required": ["code"],
                },
            },
        }

    def get_args_for_non_tool_calling_llm(
        self,
        query: str,
        history: list[PreviousMessage],
        llm: LLM,
        force_run: bool = False,
    ) -> dict[str, Any] | None:
        """Not supported - Python tool is only used via v2 agent framework."""
        raise ValueError(_GENERIC_ERROR_MESSAGE)

    def build_tool_message_content(
        self, *args: ToolResponse
    ) -> str | list[str | dict[str, Any]]:
        """Not supported - Python tool is only used via v2 agent framework."""
        raise ValueError(_GENERIC_ERROR_MESSAGE)

    def run_v2(
        self,
        run_context: RunContextWrapper[Any],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Not supported - Python tool is only used via v2 agent framework."""
        raise ValueError(_GENERIC_ERROR_MESSAGE)

    def run(
        self, override_kwargs: None = None, **llm_kwargs: str
    ) -> Generator[ToolResponse, None, None]:
        """Not supported - Python tool is only used via v2 agent framework."""
        raise ValueError(_GENERIC_ERROR_MESSAGE)

    def final_result(self, *args: ToolResponse) -> JSON_ro:
        """Not supported - Python tool is only used via v2 agent framework."""
        raise ValueError(_GENERIC_ERROR_MESSAGE)

    def build_next_prompt(
        self,
        prompt_builder: AnswerPromptBuilder,
        tool_call_summary: ToolCallSummary,
        tool_responses: list[ToolResponse],
        using_tool_calling_llm: bool,
    ) -> AnswerPromptBuilder:
        """Not supported - Python tool is only used via v2 agent framework."""
        raise ValueError(_GENERIC_ERROR_MESSAGE)
