from __future__ import annotations

import json
from enum import Enum
from typing import Any
from typing import Literal
from uuid import UUID

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import model_validator

from onyx.chat.emitter import Emitter
from onyx.configs.chat_configs import MAX_CHUNKS_FED_TO_CHAT
from onyx.configs.chat_configs import NUM_RETURNED_HITS
from onyx.configs.constants import MessageType
from onyx.context.search.models import SearchDoc
from onyx.context.search.models import SearchDocsResponse
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import GeneratedImage
from onyx.tools.tool_implementations.images.models import FinalImageGenerationResponse


TOOL_CALL_MSG_FUNC_NAME = "function_name"
TOOL_CALL_MSG_ARGUMENTS = "arguments"


class ToolCallException(Exception):
    """Exception raised for errors during tool calls."""

    def __init__(self, message: str, llm_facing_message: str):
        # This is the full error message which is used for tracing
        super().__init__(message)
        # LLM made tool calls are acceptable and not flow terminating, this is the message
        # which will populate the tool response.
        self.llm_facing_message = llm_facing_message


class SearchToolUsage(str, Enum):
    DISABLED = "disabled"
    ENABLED = "enabled"
    AUTO = "auto"


class CustomToolUserFileSnapshot(BaseModel):
    file_ids: list[str]  # References to saved images or CSVs


class CustomToolCallSummary(BaseModel):
    tool_name: str
    response_type: str  # e.g., 'json', 'image', 'csv', 'graph'
    tool_result: Any  # The response data


class ToolCallKickoff(BaseModel):
    tool_call_id: str
    tool_name: str
    tool_args: dict[str, Any]

    placement: Placement

    def to_msg_str(self) -> str:
        return json.dumps(
            {
                TOOL_CALL_MSG_FUNC_NAME: self.tool_name,
                TOOL_CALL_MSG_ARGUMENTS: self.tool_args,
            }
        )


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
    # The original tool call that triggered this response - set by tool_runner
    tool_call: ToolCallKickoff | None = None


class ParallelToolCallResponse(BaseModel):
    tool_responses: list[ToolResponse]
    updated_citation_mapping: dict[int, str]


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
    # without help and a specific custom prompt for this
    original_query: str | None = None
    message_history: list[ChatMinimalTextMessage] | None = None
    memories: list[str] | None = None
    user_info: str | None = None

    # Used for tool calls after the first one but in the same chat turn. The reason for this is that if the initial pass through
    # the custom flow did not yield good results, we don't want to go through it again. In that case, we defer entirely to the LLM
    skip_query_expansion: bool = False

    # Number of results to return in the richer object format so that it can be rendered in the UI
    num_hits: int | None = NUM_RETURNED_HITS
    # Number of chunks (token approx) to include in the string to the LLM
    max_llm_chunks: int | None = MAX_CHUNKS_FED_TO_CHAT

    model_config = ConfigDict(arbitrary_types_allowed=True)


class ChatFile(BaseModel):
    """File from a chat session that can be passed to tools."""

    filename: str
    content: bytes

    model_config = ConfigDict(arbitrary_types_allowed=True)


class PythonToolOverrideKwargs(BaseModel):
    """Override kwargs for the Python/Code Interpreter tool."""

    chat_files: list[ChatFile] = []


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
    # The parent_tool_call_id is the actual generated tool call id
    # It is NOT the DB ID which often does not exist yet when the ToolCallInfo is created
    # None if attached to the Chat Message directly
    parent_tool_call_id: str | None
    turn_index: int
    tab_index: int
    tool_name: str
    tool_call_id: str
    tool_id: int
    reasoning_tokens: str | None
    tool_call_arguments: dict[str, Any]
    tool_call_response: str
    search_docs: list[SearchDoc] | None = None
    generated_images: list[GeneratedImage] | None = None


CHAT_SESSION_ID_PLACEHOLDER = "CHAT_SESSION_ID"
MESSAGE_ID_PLACEHOLDER = "MESSAGE_ID"


class BaseCiteableToolResult(BaseModel):
    """Base class for tool results that can be cited."""

    document_citation_number: int
    unique_identifier_to_strip_away: str | None = None
    type: str


class LlmInternalSearchResult(BaseCiteableToolResult):
    """Result from an internal search query"""

    type: Literal["internal_search"] = "internal_search"
    title: str
    excerpt: str
    metadata: dict[str, Any]


class LlmWebSearchResult(BaseCiteableToolResult):
    """Result from a web search query"""

    type: Literal["web_search"] = "web_search"
    url: str
    title: str
    snippet: str


class LlmOpenUrlResult(BaseCiteableToolResult):
    """Result from opening/fetching a URL"""

    type: Literal["open_url"] = "open_url"
    content: str


class PythonExecutionFile(BaseModel):
    """File generated during Python execution"""

    filename: str
    file_link: str


class LlmPythonExecutionResult(BaseModel):
    """Result from Python code execution"""

    type: Literal["python_execution"] = "python_execution"

    stdout: str
    stderr: str
    exit_code: int | None
    timed_out: bool
    generated_files: list[PythonExecutionFile]
    error: str | None = None
