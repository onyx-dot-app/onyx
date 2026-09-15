from enum import Enum
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, Field

from onyx.agents.transcript import RunStatus
from onyx.context.search.models import SearchDoc
from onyx.server.query_and_chat.placement import Placement
from onyx.tools.progress import (
    BashOutput,
    BashStarted,
    CodingCompleted,
    CodingStarted,
    CustomToolArguments,
    CustomToolOutput,
    CustomToolStarted,
    FileReadResult,
    FileReadStarted,
    ImageGenerationHeartbeat,
    ImageGenerationStarted,
    ImagesGenerated,
    MemoryStarted,
    MemoryUpdated,
    OpenUrlStarted,
    OpenUrlTargets,
    PythonOutput,
    PythonStarted,
    ResearchStarted,
    SearchDocuments,
    SearchFilters,
    SearchQueries,
    SearchStarted,
    UrlDocuments,
)


class StreamingType(Enum):
    """Enum defining all streaming packet types. This is the single source of truth for type strings."""

    OPERATION_STATUS = "operation_status"
    SECTION_END = "section_end"
    STOP = "stop"
    TOP_LEVEL_BRANCHING = "top_level_branching"
    ERROR = "error"
    CHAT_HEARTBEAT = "chat_heartbeat"

    MESSAGE_START = "message_start"
    MESSAGE_DELTA = "message_delta"
    SEARCH_TOOL_START = "search_tool_start"
    SEARCH_TOOL_QUERIES_DELTA = "search_tool_queries_delta"
    SEARCH_TOOL_FILTER_DELTA = "search_tool_filter_delta"
    SEARCH_TOOL_DOCUMENTS_DELTA = "search_tool_documents_delta"
    OPEN_URL_START = "open_url_start"
    OPEN_URL_URLS = "open_url_urls"
    OPEN_URL_DOCUMENTS = "open_url_documents"
    IMAGE_GENERATION_START = "image_generation_start"
    IMAGE_GENERATION_HEARTBEAT = "image_generation_heartbeat"
    IMAGE_GENERATION_FINAL = "image_generation_final"
    PYTHON_TOOL_START = "python_tool_start"
    PYTHON_TOOL_DELTA = "python_tool_delta"
    CUSTOM_TOOL_START = "custom_tool_start"
    CUSTOM_TOOL_ARGS = "custom_tool_args"
    CUSTOM_TOOL_DELTA = "custom_tool_delta"
    FILE_READER_START = "file_reader_start"
    FILE_READER_RESULT = "file_reader_result"
    REASONING_START = "reasoning_start"
    REASONING_DELTA = "reasoning_delta"
    REASONING_DONE = "reasoning_done"
    CITATION_INFO = "citation_info"
    TOOL_CALL_DEBUG = "tool_call_debug"
    TOOL_CALL_ARGUMENT_DELTA = "tool_call_argument_delta"

    MEMORY_TOOL_START = "memory_tool_start"
    MEMORY_TOOL_DELTA = "memory_tool_delta"
    MEMORY_TOOL_NO_ACCESS = "memory_tool_no_access"

    DEEP_RESEARCH_PLAN_START = "deep_research_plan_start"
    DEEP_RESEARCH_PLAN_DELTA = "deep_research_plan_delta"
    RESEARCH_AGENT_START = "research_agent_start"
    INTERMEDIATE_REPORT_START = "intermediate_report_start"
    INTERMEDIATE_REPORT_DELTA = "intermediate_report_delta"
    INTERMEDIATE_REPORT_CITED_DOCS = "intermediate_report_cited_docs"

    CODING_AGENT_START = "coding_agent_start"
    CODING_AGENT_THINKING_DELTA = "coding_agent_thinking_delta"
    CODING_AGENT_FINAL = "coding_agent_final"

    BASH_TOOL_START = "bash_tool_start"
    BASH_TOOL_DELTA = "bash_tool_delta"


class BaseObj(BaseModel):
    type: str = ""


################################################
# Control Packets
################################################
# This one isn't strictly necessary, remove in the future
class SectionEnd(BaseObj):
    type: Literal["section_end"] = StreamingType.SECTION_END.value


class OperationStatus(BaseObj):
    type: Literal["operation_status"] = StreamingType.OPERATION_STATUS.value
    status: RunStatus
    tool_name: str | None = None


class OverallStop(BaseObj):
    type: Literal["stop"] = StreamingType.STOP.value
    stop_reason: str | None = None


class TopLevelBranching(BaseObj):
    # This class is used to give advanced heads up to the frontend that the top level flow is branching
    # This is used to avoid having the frontend render the first call then rerendering the other parallel branches
    type: Literal["top_level_branching"] = StreamingType.TOP_LEVEL_BRANCHING.value

    num_parallel_branches: int


class PacketException(BaseObj):
    type: Literal["error"] = StreamingType.ERROR.value

    exception: Exception = Field(exclude=True)
    model_config = {"arbitrary_types_allowed": True}


# Payload-less keepalive so idle proxies don't kill an otherwise-silent stream
class ChatHeartbeat(BaseObj):
    type: Literal["chat_heartbeat"] = StreamingType.CHAT_HEARTBEAT.value


################################################
# Reasoning Packets
################################################
# Tells the frontend to display the reasoning block
class ReasoningStart(BaseObj):
    type: Literal["reasoning_start"] = StreamingType.REASONING_START.value


# The stream of tokens for the reasoning
class ReasoningDelta(BaseObj):
    type: Literal["reasoning_delta"] = StreamingType.REASONING_DELTA.value

    reasoning: str


class ReasoningDone(BaseObj):
    type: Literal["reasoning_done"] = StreamingType.REASONING_DONE.value


################################################
# Final Agent Response Packets
################################################
# Start of the final answer
class AgentResponseStart(BaseObj):
    type: Literal["message_start"] = StreamingType.MESSAGE_START.value

    final_documents: list[SearchDoc] | None = None
    pre_answer_processing_seconds: float | None = None


# The stream of tokens for the final response
# There is no end packet for this as the stream is over and a final OverallStop packet is emitted
class AgentResponseDelta(BaseObj):
    type: Literal["message_delta"] = StreamingType.MESSAGE_DELTA.value

    content: str


# Citation info for the sidebar and inline citations
class CitationInfo(BaseObj):
    type: Literal["citation_info"] = StreamingType.CITATION_INFO.value

    # The numerical number of the citation as provided by the LLM
    citation_number: int
    # The document id of the SearchDoc (same as the field stored in the DB)
    # This is the actual document id from the connector, not the int id
    document_id: str


class ToolCallDebug(BaseObj):
    type: Literal["tool_call_debug"] = StreamingType.TOOL_CALL_DEBUG.value

    tool_call_id: str
    tool_name: str
    tool_args: dict[str, Any]


################################################
# Tool Packets
################################################
# Search tool is called and the UI block needs to start
class SearchToolStart(SearchStarted, BaseObj):
    type: Literal["search_tool_start"] = StreamingType.SEARCH_TOOL_START.value


# Queries coming through as the LLM determines what to search
# Mostly for query expansions and advanced search strategies
class SearchToolQueriesDelta(SearchQueries, BaseObj):
    type: Literal["search_tool_queries_delta"] = (
        StreamingType.SEARCH_TOOL_QUERIES_DELTA.value
    )


# Filters applied to this internal search. Empty `sources` == scope not narrowed
# (searched everything); either time bound may be absent (open-ended).
class SearchToolFilterDelta(SearchFilters, BaseObj):
    type: Literal["search_tool_filter_delta"] = (
        StreamingType.SEARCH_TOOL_FILTER_DELTA.value
    )


# Documents coming through as the system knows what to add to the context
class SearchToolDocumentsDelta(SearchDocuments, BaseObj):
    type: Literal["search_tool_documents_delta"] = (
        StreamingType.SEARCH_TOOL_DOCUMENTS_DELTA.value
    )


# OpenURL tool packets - 3-stage sequence
class OpenUrlStart(OpenUrlStarted, BaseObj):
    type: Literal["open_url_start"] = StreamingType.OPEN_URL_START.value


class OpenUrlUrls(OpenUrlTargets, BaseObj):
    type: Literal["open_url_urls"] = StreamingType.OPEN_URL_URLS.value


class OpenUrlDocuments(UrlDocuments, BaseObj):
    type: Literal["open_url_documents"] = StreamingType.OPEN_URL_DOCUMENTS.value


# Image generation starting, needs to allocate a placeholder block for it on the UI
class ImageGenerationToolStart(ImageGenerationStarted, BaseObj):
    type: Literal["image_generation_start"] = StreamingType.IMAGE_GENERATION_START.value


# Since image generation can take a while
# we send a heartbeat to the frontend to keep the UI/connection alive
class ImageGenerationToolHeartbeat(ImageGenerationHeartbeat, BaseObj):
    type: Literal["image_generation_heartbeat"] = (
        StreamingType.IMAGE_GENERATION_HEARTBEAT.value
    )


# Represents an image generated by an image generation tool


# The final generated images all at once at the end of image generation
class ImageGenerationFinal(ImagesGenerated, BaseObj):
    type: Literal["image_generation_final"] = StreamingType.IMAGE_GENERATION_FINAL.value


class PythonToolStart(PythonStarted, BaseObj):
    type: Literal["python_tool_start"] = StreamingType.PYTHON_TOOL_START.value


class PythonToolDelta(PythonOutput, BaseObj):
    type: Literal["python_tool_delta"] = StreamingType.PYTHON_TOOL_DELTA.value


# Custom tool being called, first allocate a placeholder block for it on the UI
class CustomToolStart(CustomToolStarted, BaseObj):
    type: Literal["custom_tool_start"] = StreamingType.CUSTOM_TOOL_START.value


class CustomToolArgs(CustomToolArguments, BaseObj):
    type: Literal["custom_tool_args"] = StreamingType.CUSTOM_TOOL_ARGS.value


# The allowed streamed packets for a custom tool
class CustomToolDelta(CustomToolOutput, BaseObj):
    type: Literal["custom_tool_delta"] = StreamingType.CUSTOM_TOOL_DELTA.value


class ToolCallArgumentDelta(BaseObj):
    type: Literal["tool_call_argument_delta"] = (
        StreamingType.TOOL_CALL_ARGUMENT_DELTA.value
    )

    tool_type: str
    argument_deltas: dict[str, Any]


################################################
# File Reader Packets
################################################
class FileReaderStart(FileReadStarted, BaseObj):
    type: Literal["file_reader_start"] = StreamingType.FILE_READER_START.value


class FileReaderResult(FileReadResult, BaseObj):
    type: Literal["file_reader_result"] = StreamingType.FILE_READER_RESULT.value


# Memory Tool Packets
################################################
class MemoryToolStart(MemoryStarted, BaseObj):
    type: Literal["memory_tool_start"] = StreamingType.MEMORY_TOOL_START.value


class MemoryToolDelta(MemoryUpdated, BaseObj):
    type: Literal["memory_tool_delta"] = StreamingType.MEMORY_TOOL_DELTA.value


class MemoryToolNoAccess(BaseObj):
    type: Literal["memory_tool_no_access"] = StreamingType.MEMORY_TOOL_NO_ACCESS.value


################################################
# Deep Research Packets
################################################
class DeepResearchPlanStart(BaseObj):
    type: Literal["deep_research_plan_start"] = (
        StreamingType.DEEP_RESEARCH_PLAN_START.value
    )


class DeepResearchPlanDelta(BaseObj):
    type: Literal["deep_research_plan_delta"] = (
        StreamingType.DEEP_RESEARCH_PLAN_DELTA.value
    )

    content: str


class ResearchAgentStart(ResearchStarted, BaseObj):
    type: Literal["research_agent_start"] = StreamingType.RESEARCH_AGENT_START.value


class IntermediateReportStart(BaseObj):
    type: Literal["intermediate_report_start"] = (
        StreamingType.INTERMEDIATE_REPORT_START.value
    )


class IntermediateReportDelta(BaseObj):
    type: Literal["intermediate_report_delta"] = (
        StreamingType.INTERMEDIATE_REPORT_DELTA.value
    )
    content: str


class IntermediateReportCitedDocs(BaseObj):
    type: Literal["intermediate_report_cited_docs"] = (
        StreamingType.INTERMEDIATE_REPORT_CITED_DOCS.value
    )
    cited_docs: list[SearchDoc] | None = None


################################################
# Coding Agent Packets
################################################
class CodingAgentStart(CodingStarted, BaseObj):
    type: Literal["coding_agent_start"] = StreamingType.CODING_AGENT_START.value


class CodingAgentThinkingDelta(BaseObj):
    type: Literal["coding_agent_thinking_delta"] = (
        StreamingType.CODING_AGENT_THINKING_DELTA.value
    )
    content: str


class CodingAgentFinal(CodingCompleted, BaseObj):
    type: Literal["coding_agent_final"] = StreamingType.CODING_AGENT_FINAL.value


################################################
# Bash Tool Packets
################################################
class BashToolStart(BashStarted, BaseObj):
    type: Literal["bash_tool_start"] = StreamingType.BASH_TOOL_START.value


class BashToolDelta(BashOutput, BaseObj):
    type: Literal["bash_tool_delta"] = StreamingType.BASH_TOOL_DELTA.value


################################################
# Packet Object
################################################
# Discriminated union of all possible packet object types
PacketObj = Union[
    # Control Packets
    OverallStop,
    OperationStatus,
    SectionEnd,
    TopLevelBranching,
    PacketException,
    ChatHeartbeat,
    # Agent Response Packets
    AgentResponseStart,
    AgentResponseDelta,
    # Tool Packets
    SearchToolStart,
    SearchToolQueriesDelta,
    SearchToolFilterDelta,
    SearchToolDocumentsDelta,
    ImageGenerationToolStart,
    ImageGenerationToolHeartbeat,
    ImageGenerationFinal,
    OpenUrlStart,
    OpenUrlUrls,
    OpenUrlDocuments,
    PythonToolStart,
    PythonToolDelta,
    CustomToolStart,
    CustomToolArgs,
    CustomToolDelta,
    FileReaderStart,
    FileReaderResult,
    MemoryToolStart,
    MemoryToolDelta,
    MemoryToolNoAccess,
    # Reasoning Packets
    ReasoningStart,
    ReasoningDelta,
    ReasoningDone,
    # Citation Packets
    CitationInfo,
    ToolCallDebug,
    ToolCallArgumentDelta,
    # Deep Research Packets
    DeepResearchPlanStart,
    DeepResearchPlanDelta,
    ResearchAgentStart,
    IntermediateReportStart,
    IntermediateReportDelta,
    IntermediateReportCitedDocs,
    # Coding Agent Packets
    CodingAgentStart,
    CodingAgentThinkingDelta,
    CodingAgentFinal,
    # Bash Tool Packets
    BashToolStart,
    BashToolDelta,
]


class PacketIdentity(BaseModel):
    response_id: int
    run_id: str
    message_id: str
    parent_run_id: str | None = None
    parent_message_id: str | None = None
    parent_tool_call_id: str | None = None
    tool_call_id: str | None = None
    part_id: str = "answer"


class Packet(BaseModel):
    placement: Placement = Field(default_factory=lambda: Placement(turn_index=0))
    identity: PacketIdentity | None = None

    obj: Annotated[PacketObj, Field(discriminator="type")]


def heartbeat_packet() -> Packet:
    """Keepalive for silent stretches; carries no run state."""
    return Packet(placement=Placement(turn_index=0), obj=ChatHeartbeat())
