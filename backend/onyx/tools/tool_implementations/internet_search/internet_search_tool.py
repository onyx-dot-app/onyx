from collections.abc import Generator
from typing import Any

from onyx.chat.prompt_builder.answer_prompt_builder import AnswerPromptBuilder
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
_GENERIC_ERROR_MESSAGE = "InternetSearchTool should only be used by the Deep Research Agent, not via tool calling."


class InternetSearchTool(Tool[None]):
    _NAME = "run_internet_search"
    _DESCRIPTION = "Search the internet for information. Never call this tool."
    _DISPLAY_NAME = "Internet Search"

    def __init__(self, tool_id: int) -> None:
        self._id = tool_id

    @property
    def id(self) -> int:
        return self._id
    def __init__(
        self,
        db_session: Session,
        persona: Persona,
        prompt_config: PromptConfig,
        llm: LLM,
        document_pruning_config: DocumentPruningConfig,
        answer_style_config: AnswerStyleConfig,
        provider: str | None = None,
        num_results: int = NUM_INTERNET_SEARCH_RESULTS,
        max_chunks: int = NUM_INTERNET_SEARCH_CHUNKS,
    ) -> None:
        self.db_session = db_session
        self.persona = persona
        self.prompt_config = prompt_config
        self.llm = llm
        self.max_chunks = max_chunks

        self.chunks_above = (
            persona.chunks_above
            if persona.chunks_above is not None
            else CONTEXT_CHUNKS_ABOVE
        )

        self.chunks_below = (
            persona.chunks_below
            if persona.chunks_below is not None
            else CONTEXT_CHUNKS_BELOW
        )

        self.provider = (
            get_provider_by_name("bing")
        )

        if not self.provider:
            raise ValueError("No internet search providers are configured")

        self.provider.num_results = num_results

        max_input_tokens = compute_max_llm_input_tokens(
            llm_config=llm.config,
        )
        if max_input_tokens < 3 * GEN_AI_MODEL_FALLBACK_MAX_TOKENS:
            self.chunks_above = 0
            self.chunks_below = 0

        num_chunk_multiple = self.chunks_above + self.chunks_below + 1

        self.answer_style_config = answer_style_config
        self.contextual_pruning_config = (
            ContextualPruningConfig.from_doc_pruning_config(
                num_chunk_multiple=num_chunk_multiple,
                doc_pruning_config=document_pruning_config,
            )
        )

    """For explicit tool calling"""

    @property
    def name(self) -> str:
        return self._NAME

    @property
    def description(self) -> str:
        return self._DESCRIPTION

    @property
    def display_name(self) -> str:
        return self._DISPLAY_NAME

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
        """Build the next prompt for the LLM using the search results"""
        return build_next_prompt_for_search_like_tool(
            prompt_builder=prompt_builder,
            tool_call_summary=tool_call_summary,
            tool_responses=tool_responses,
            using_tool_calling_llm=using_tool_calling_llm,
            answer_style_config=self.answer_style_config,
            prompt_config=self.prompt_config,
            context_type="internet search results",
        )