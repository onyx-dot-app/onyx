from enum import Enum
from typing import Annotated
from typing import Literal
from typing import Union

from pydantic import BaseModel
from pydantic import Field

from onyx.context.search.models import SearchDoc


class StreamingType(Enum):
    MESSAGE_START = "message_start"
    MESSAGE_DELTA = "message_delta"
    ERROR = "error"
    STOP = "stop"
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
    AGENT_TOOL_START = "agent_tool_start"
    AGENT_TOOL_DELTA = "agent_tool_delta"
    AGENT_TOOL_FINAL = "agent_tool_final"


class BaseObj(BaseModel):
    type: str = ""


"""Reasoning Packets"""


# Tells the frontend to display the reasoning block
class ReasoningStart(BaseObj):
    type: Literal["reasoning_start"] = StreamingType.REASONING_START.value


# The stream of tokens for the reasoning
class ReasoningDelta(BaseObj):
    type: Literal["reasoning_delta"] = StreamingType.REASONING_DELTA.value

    reasoning: str


class ReasoningDone(BaseObj):
    type: Literal["reasoning_done"] = StreamingType.REASONING_DONE.value


"""Final Agent Response Packets"""


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


"""Control Packets"""


# This one isn't strictly necessary, remove in the future
class SectionEnd(BaseObj):
    type: Literal["section_end"] = "section_end"


class PacketException(BaseObj):
    type: Literal["error"] = StreamingType.ERROR.value

    exception: Exception
    model_config = {"arbitrary_types_allowed": True}


class OverallStop(BaseObj):
    type: Literal["stop"] = StreamingType.STOP.value


"""Tool Packets"""


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


class CustomToolDelta(BaseObj):
    type: Literal["custom_tool_delta"] = StreamingType.CUSTOM_TOOL_DELTA.value

    tool_name: str
    response_type: str
    data: dict | list | str | int | float | bool | None = None
    file_ids: list[str] | None = None


class AgentToolStart(BaseObj):
    type: Literal["agent_tool_start"] = StreamingType.AGENT_TOOL_START.value

    agent_name: str
    agent_id: int


class AgentToolDelta(BaseObj):
    type: Literal["agent_tool_delta"] = StreamingType.AGENT_TOOL_DELTA.value

    agent_name: str
    status_text: str | None = None
    nested_content: str | None = None


class AgentToolFinal(BaseObj):
    type: Literal["agent_tool_final"] = StreamingType.AGENT_TOOL_FINAL.value

    agent_name: str
    summary: str
    full_response: str | None = None


"""Packet"""

PacketObj = Union[
    AgentResponseStart,
    AgentResponseDelta,
    OverallStop,
    SectionEnd,
    PacketException,
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
    AgentToolStart,
    AgentToolDelta,
    AgentToolFinal,
    ReasoningStart,
    ReasoningDelta,
    ReasoningDone,
    CitationInfo,
]


class Packet(BaseModel):
    turn_index: int | None
    obj: Annotated[PacketObj, Field(discriminator="type")]


# This is for replaying it back from the DB to the frontend
class EndStepPacketList(BaseModel):
    turn_index: int
    packet_list: list[Packet]
