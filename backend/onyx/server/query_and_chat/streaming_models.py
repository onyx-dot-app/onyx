from enum import Enum
from typing import Annotated
from typing import Literal
from typing import Union

from pydantic import BaseModel
from pydantic import Field

from onyx.context.search.models import SearchDoc
from onyx.server.query_and_chat.placement import Placement


class StreamingType(Enum):
    """Enum defining all streaming packet types. This is the single source of truth for type strings."""

    SECTION_END = "section_end"
    STOP = "stop"
    TOP_LEVEL_BRANCHING = "top_level_branching"
    ERROR = "error"

    MESSAGE_START = "message_start"
    MESSAGE_DELTA = "message_delta"
    SEARCH_TOOL_START = "search_tool_start"
    SEARCH_TOOL_QUERIES_DELTA = "search_tool_queries_delta"
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
    CUSTOM_TOOL_DELTA = "custom_tool_delta"
    REASONING_START = "reasoning_start"
    REASONING_DELTA = "reasoning_delta"
    REASONING_DONE = "reasoning_done"
    CITATION_INFO = "citation_info"

    DEEP_RESEARCH_PLAN_START = "deep_research_plan_start"
    DEEP_RESEARCH_PLAN_DELTA = "deep_research_plan_delta"
    RESEARCH_AGENT_START = "research_agent_start"
    INTERMEDIATE_REPORT_START = "intermediate_report_start"
    INTERMEDIATE_REPORT_DELTA = "intermediate_report_delta"
    INTERMEDIATE_REPORT_CITED_DOCS = "intermediate_report_cited_docs"


class BaseObj(BaseModel):
    type: str = ""


################################################
# Control Packets
################################################
# This one isn't strictly necessary, remove in the future
class SectionEnd(BaseObj):
    type: Literal["section_end"] = StreamingType.SECTION_END.value


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

    exception: Exception
    model_config = {"arbitrary_types_allowed": True}


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


################################################
# Tool Packets
################################################
# Search tool is called and the UI block needs to start
class SearchToolStart(BaseObj):
    type: Literal["search_tool_start"] = StreamingType.SEARCH_TOOL_START.value

    is_internet_search: bool = False


# Queries coming through as the LLM determines what to search
# Mostly for query expansions and advanced search strategies
class SearchToolQueriesDelta(BaseObj):
    type: Literal["search_tool_queries_delta"] = (
        StreamingType.SEARCH_TOOL_QUERIES_DELTA.value
    )

    queries: list[str]


# Documents coming through as the system knows what to add to the context
class SearchToolDocumentsDelta(BaseObj):
    type: Literal["search_tool_documents_delta"] = (
        StreamingType.SEARCH_TOOL_DOCUMENTS_DELTA.value
    )

    # This cannot be the SavedSearchDoc as this is yielded by the SearchTool directly
    # which does not save documents to the DB.
    documents: list[SearchDoc]


# OpenURL tool packets - 3-stage sequence
class OpenUrlStart(BaseObj):
    """Signal that OpenURL tool has started."""

    type: Literal["open_url_start"] = StreamingType.OPEN_URL_START.value


class OpenUrlUrls(BaseObj):
    """URLs to be fetched (sent before crawling begins)."""

    type: Literal["open_url_urls"] = StreamingType.OPEN_URL_URLS.value

    urls: list[str]


class OpenUrlDocuments(BaseObj):
    """Final documents after crawling completes."""

    type: Literal["open_url_documents"] = StreamingType.OPEN_URL_DOCUMENTS.value

    documents: list[SearchDoc]


# Image generation starting, needs to allocate a placeholder block for it on the UI
class ImageGenerationToolStart(BaseObj):
    type: Literal["image_generation_start"] = StreamingType.IMAGE_GENERATION_START.value


# Since image generation can take a while
# we send a heartbeat to the frontend to keep the UI/connection alive
class ImageGenerationToolHeartbeat(BaseObj):
    type: Literal["image_generation_heartbeat"] = (
        StreamingType.IMAGE_GENERATION_HEARTBEAT.value
    )


# Represents an image generated by an image generation tool
class GeneratedImage(BaseModel):
    """Represents an image generated by an image generation tool."""

    file_id: str
    url: str
    revised_prompt: str
    shape: str | None = None


# The final generated images all at once at the end of image generation
class ImageGenerationFinal(BaseObj):
    type: Literal["image_generation_final"] = StreamingType.IMAGE_GENERATION_FINAL.value

    images: list[GeneratedImage]


class PythonToolStart(BaseObj):
    type: Literal["python_tool_start"] = StreamingType.PYTHON_TOOL_START.value
    code: str


class PythonToolDelta(BaseObj):
    type: Literal["python_tool_delta"] = StreamingType.PYTHON_TOOL_DELTA.value

    stdout: str = ""
    stderr: str = ""
    file_ids: list[str] = []


# Custom tool being called, first allocate a placeholder block for it on the UI
class CustomToolStart(BaseObj):
    type: Literal["custom_tool_start"] = StreamingType.CUSTOM_TOOL_START.value

    tool_name: str


# The allowed streamed packets for a custom tool
class CustomToolDelta(BaseObj):
    type: Literal["custom_tool_delta"] = StreamingType.CUSTOM_TOOL_DELTA.value

    tool_name: str
    response_type: str
    # For non-file responses
    data: dict | list | str | int | float | bool | None = None
    # For file-based responses like image/csv
    file_ids: list[str] | None = None


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


class ResearchAgentStart(BaseObj):
    type: Literal["research_agent_start"] = StreamingType.RESEARCH_AGENT_START.value
    research_task: str


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
# Packet Object
################################################
# Discriminated union of all possible packet object types
PacketObj = Union[
    # Control Packets
    OverallStop,
    SectionEnd,
    TopLevelBranching,
    PacketException,
    # Agent Response Packets
    AgentResponseStart,
    AgentResponseDelta,
    # Tool Packets
    SearchToolStart,
    SearchToolQueriesDelta,
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
    CustomToolDelta,
    # Reasoning Packets
    ReasoningStart,
    ReasoningDelta,
    ReasoningDone,
    # Citation Packets
    CitationInfo,
    # Deep Research Packets
    DeepResearchPlanStart,
    DeepResearchPlanDelta,
    ResearchAgentStart,
    IntermediateReportStart,
    IntermediateReportDelta,
    IntermediateReportCitedDocs,
]


class Packet(BaseModel):
    placement: Placement

    obj: Annotated[PacketObj, Field(discriminator="type")]
