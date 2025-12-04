from typing import Any

from sqlalchemy.orm import Session
from typing_extensions import override

from onyx.chat.emitter import Emitter
from onyx.tools.models import ToolResponse
from onyx.tools.tool import Tool
from onyx.utils.logger import setup_logger


logger = setup_logger()

_GENERIC_ERROR_MESSAGE = (
    "PythonTool should only be used with v2 tools, not via direct calls to PythonTool."
)


class PythonTool(Tool[None]):
    """
    Wrapper class for Python code execution tool.

    This class provides availability checking and integrates with the Tool infrastructure.
    Actual execution is handled by the v2 function-based implementation.
    """

    _NAME = "python"
    _DESCRIPTION = "Execute Python code in a secure, isolated environment. Never call this tool directly."
    # in the UI, call it `Code Interpreter` since this is a well known term for this tool
    _DISPLAY_NAME = "Code Interpreter"

    def __init__(self, tool_id: int, emitter: Emitter | None = None) -> None:
        super().__init__(emitter)
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
        return False
        # is_available = bool(CODE_INTERPRETER_BASE_URL)
        # logger.info(
        #     "PythonTool.is_available() called: "
        #     f"CODE_INTERPRETER_BASE_URL={CODE_INTERPRETER_BASE_URL!r}, "
        #     f"returning {is_available}"
        # )

        # return is_available

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

    def emit_start(self, turn_index: int) -> None:
        """Not supported - Python tool is only used via v2 agent framework."""
        raise NotImplementedError(_GENERIC_ERROR_MESSAGE)

    def run(
        self,
        turn_index: int,
        override_kwargs: None,
        **llm_kwargs: Any,
    ) -> ToolResponse:
        """Not supported - Python tool is only used via v2 agent framework."""
        raise NotImplementedError(_GENERIC_ERROR_MESSAGE)
