from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import model_validator

from onyx.chat.infra import Emitter
from onyx.configs.chat_configs import MAX_CHUNKS_FED_TO_CHAT
from onyx.configs.chat_configs import NUM_RETURNED_HITS
from onyx.configs.constants import MessageType
from onyx.context.search.enums import SearchType
from onyx.context.search.models import IndexFilters
from onyx.context.search.models import SearchDoc
from onyx.context.search.models import SearchDocsResponse
from onyx.tools.tool_implementations.images.models import FinalImageGenerationResponse


class CustomToolUserFileSnapshot(BaseModel):
    file_ids: list[str]  # References to saved images or CSVs


class CustomToolCallSummary(BaseModel):
    tool_name: str
    response_type: str  # e.g., 'json', 'image', 'csv', 'graph'
    tool_result: Any  # The response data


class ToolResponse(BaseModel):
    # Rich response is for the objects that are returned but not directly used by the LLM
    # these typically need to be saved to the database to load things in the UI (usually both)
    rich_response: (
        # This comes from image generation, image needs to be saved and the packet about it's location needs to be emitted
        FinalImageGenerationResponse
        # This comes from internal search / web search, search docs need to be saved, already emitted by the tool
        | SearchDocsResponse
        # This comes from open url, web content needs to be saved, maybe this can be consolidated too
        # | WebContentResponse
        # This comes from custom tools, tool result needs to be saved
        | CustomToolCallSummary
        | None  # If nothing needs to be persisted outside of the string value passed to the LLM
    )
    # This is the final string that needs to be wrapped in a tool call response message and concatenated to the history
    llm_facing_response: str


class ToolCallKickoff(BaseModel):
    tool_call_id: str
    tool_name: str
    tool_args: dict[str, Any]


class ToolRunnerResponse(BaseModel):
    tool_run_kickoff: ToolCallKickoff | None = None
    tool_response: ToolResponse | None = None
    tool_message_content: str | list[str | dict[str, Any]] | None = None

    @model_validator(mode="after")
    def validate_tool_runner_response(self) -> "ToolRunnerResponse":
        fields = ["tool_response", "tool_message_content", "tool_run_kickoff"]
        provided = sum(1 for field in fields if getattr(self, field) is not None)

        if provided != 1:
            raise ValueError(
                "Exactly one of 'tool_response', 'tool_message_content', "
                "or 'tool_run_kickoff' must be provided"
            )

        return self


class ToolCallFinalResult(ToolCallKickoff):
    tool_result: Any = (
        None  # we would like to use JSON_ro, but can't due to its recursive nature
    )
    # agentic additions; only need to set during agentic tool calls
    level: int | None = None
    level_question_num: int | None = None


class ChatMinimalTextMessage(BaseModel):
    message: str
    message_type: MessageType


class DynamicSchemaInfo(BaseModel):
    chat_session_id: UUID | None
    message_id: int | None


class SearchQueryInfo(BaseModel):
    predicted_search: SearchType | None
    final_filters: IndexFilters
    recency_bias_multiplier: float


class WebSearchToolOverrideKwargs(BaseModel):
    # To know what citation number to start at for constructing the string to the LLM
    starting_citation_num: int


class OpenURLToolOverrideKwargs(BaseModel):
    # To know what citation number to start at for constructing the string to the LLM
    starting_citation_num: int
    citation_mapping: dict[str, int]


# None indicates that the default value should be used
class SearchToolOverrideKwargs(BaseModel):
    # To know what citation number to start at for constructing the string to the LLM
    starting_citation_num: int
    # This is needed because the LLM won't be able to do a really detailed semantic query well
    original_query: str | None = None
    message_history: list[ChatMinimalTextMessage] | None = None
    memories: list[str] | None = None
    user_info: str | None = None

    # Number of results to return in the richer object format so that it can be rendered in the UI
    num_hits: int | None = NUM_RETURNED_HITS
    # Number of chunks (token approx) to include in the string to the LLM
    max_llm_chunks: int | None = MAX_CHUNKS_FED_TO_CHAT

    model_config = ConfigDict(arbitrary_types_allowed=True)


class SearchToolRunContext(BaseModel):
    emitter: Emitter

    model_config = {"arbitrary_types_allowed": True}


class ImageGenerationToolRunContext(BaseModel):
    emitter: Emitter

    model_config = {"arbitrary_types_allowed": True}


class CustomToolRunContext(BaseModel):
    emitter: Emitter

    model_config = {"arbitrary_types_allowed": True}


class ToolCallInfo(BaseModel):
    parent_tool_call_id: str | None  # None if attached to the Chat Message directly
    turn_index: int
    tool_name: str
    tool_call_id: str
    tool_id: int
    reasoning_tokens: str | None
    tool_call_arguments: dict[str, Any]
    tool_call_response: str
    search_docs: list[SearchDoc] | None = None


CHAT_SESSION_ID_PLACEHOLDER = "CHAT_SESSION_ID"
MESSAGE_ID_PLACEHOLDER = "MESSAGE_ID"
