from collections.abc import Generator
from typing import Any

from sqlalchemy.orm import Session
from typing_extensions import override

from onyx.chat.prompt_builder.answer_prompt_builder import AnswerPromptBuilder
from onyx.configs.chat_configs import EXA_API_KEY
from onyx.configs.chat_configs import SERPER_API_KEY
from onyx.llm.interfaces import LLM
from onyx.llm.models import PreviousMessage
from onyx.tools.message import ToolCallSummary
from onyx.tools.models import ToolResponse
from onyx.tools.tool import Tool
from onyx.utils.logger import setup_logger
from onyx.utils.special_types import JSON_ro


logger = setup_logger()

# TODO: Align on separation of Tools and SubAgents. Right now, we're only keeping this around for backwards compatibility.
QUERY_FIELD = "query"
_GENERIC_ERROR_MESSAGE = "WebSearchTool should only be used by the Deep Research Agent, not via tool calling."


class WebSearchTool(Tool[None]):
    _NAME = "run_web_search"
    _DESCRIPTION = "Search the web for information. Never call this tool."
    _DISPLAY_NAME = "Web Search"

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
        """Available only if EXA or SERPER API key is configured."""
        return bool(EXA_API_KEY) or bool(SERPER_API_KEY)

    def tool_definition(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        QUERY_FIELD: {
                            "type": "string",
                            "description": "What to search for",
                        },
                    },
                    "required": [QUERY_FIELD],
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
        raise ValueError(_GENERIC_ERROR_MESSAGE)

    def build_tool_message_content(
        self, *args: ToolResponse
    ) -> str | list[str | dict[str, Any]]:
        raise ValueError(_GENERIC_ERROR_MESSAGE)

    def run(
        self, override_kwargs: None = None, **llm_kwargs: str
    ) -> Generator[ToolResponse, None, None]:
        raise ValueError(_GENERIC_ERROR_MESSAGE)

    def final_result(self, *args: ToolResponse) -> JSON_ro:
        raise ValueError(_GENERIC_ERROR_MESSAGE)

    def build_next_prompt(
        self,
        prompt_builder: AnswerPromptBuilder,
        tool_call_summary: ToolCallSummary,
        tool_responses: list[ToolResponse],
        using_tool_calling_llm: bool,
    ) -> AnswerPromptBuilder:
        raise ValueError(_GENERIC_ERROR_MESSAGE)
