from collections.abc import Generator
from typing import Any

from sqlalchemy.orm import Session

from onyx.chat.prompt_builder.answer_prompt_builder import AnswerPromptBuilder
from onyx.db.kg_config import get_kg_config_settings
from onyx.llm.interfaces import LLM
from onyx.llm.models import PreviousMessage
from onyx.tools.message import ToolCallSummary
from onyx.tools.models import ToolResponse
from onyx.tools.tool import Tool
from onyx.utils.logger import setup_logger
from onyx.utils.special_types import JSON_ro


logger = setup_logger()

QUERY_FIELD = "query"


class KnowledgeGraphTool(Tool[None]):
    _NAME = "run_kg_search"
    _DESCRIPTION = "Search the knowledge graph for information. Never call this tool."
    _DISPLAY_NAME = "Knowledge Graph Search"

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

    @classmethod
    def is_available(cls, db_session: Session) -> bool:
        """Available only if KG is enabled and exposed."""
        kg_configs = get_kg_config_settings()
        return kg_configs.KG_ENABLED and kg_configs.KG_EXPOSED

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
        raise ValueError(
            "KnowledgeGraphTool should only be used by the Deep Research Agent, "
            "not via tool calling."
        )

    def build_tool_message_content(
        self, *args: ToolResponse
    ) -> str | list[str | dict[str, Any]]:
        raise ValueError(
            "KnowledgeGraphTool should only be used by the Deep Research Agent, "
            "not via tool calling."
        )

    def run(
        self, override_kwargs: None = None, **kwargs: str
    ) -> Generator[ToolResponse, None, None]:
        raise ValueError(
            "KnowledgeGraphTool should only be used by the Deep Research Agent, "
            "not via tool calling."
        )

    def final_result(self, *args: ToolResponse) -> JSON_ro:
        raise ValueError(
            "KnowledgeGraphTool should only be used by the Deep Research Agent, "
            "not via tool calling."
        )

    def build_next_prompt(
        self,
        prompt_builder: AnswerPromptBuilder,
        tool_call_summary: ToolCallSummary,
        tool_responses: list[ToolResponse],
        using_tool_calling_llm: bool,
    ) -> AnswerPromptBuilder:
        raise ValueError(
            "KnowledgeGraphTool should only be used by the Deep Research Agent, "
            "not via tool calling."
        )
