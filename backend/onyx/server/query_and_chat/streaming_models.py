from enum import Enum
from typing import Annotated
from typing import Any
from typing import Literal
from typing import Type
from typing import Union

from pydantic import BaseModel
from pydantic import Field
from pydantic import model_validator

from onyx.context.search.models import SavedSearchDoc
from onyx.tools.models import GeneratedImage


class StreamingType(Enum):
    """Enum defining all streaming packet types. This is the single source of truth for type strings."""

    MESSAGE_START = "message_start"
    MESSAGE_DELTA = "message_delta"
    ERROR = "error"
    STOP = "stop"
    SECTION_END = "section_end"
    SEARCH_TOOL_START = "search_tool_start"
    SEARCH_TOOL_QUERIES_DELTA = "search_tool_queries_delta"
    SEARCH_TOOL_DOCUMENTS_DELTA = "search_tool_documents_delta"
    OPEN_URL_START = "open_url_start"
    IMAGE_GENERATION_START = "image_generation_start"
    IMAGE_GENERATION_HEARTBEAT = "image_generation_heartbeat"
    IMAGE_GENERATION_FINAL = "image_generation_final"
    CUSTOM_TOOL_START = "custom_tool_start"
    CUSTOM_TOOL_DELTA = "custom_tool_delta"
    REASONING_START = "reasoning_start"
    REASONING_DELTA = "reasoning_delta"
    CITATION_INFO = "citation_info"


class BaseObj(BaseModel):
    # Class variable to store the expected type value for each subclass
    _type_value: str | None = None

    type: str = Field(default="", exclude=False)

    def __init_subclass__(cls: Type["BaseObj"], **kwargs: Any) -> None:  # type: ignore[misc]
        """Automatically add the type field with Literal type for discriminated union."""
        super().__init_subclass__(**kwargs)
        type_value = getattr(cls, "_type_value", None)
        if type_value is not None:
            # Add the type field with Literal type annotation for the discriminator
            if not hasattr(cls, "__annotations__"):
                cls.__annotations__ = {}
            cls.__annotations__["type"] = Literal[type_value]
            # The default will be set by the validator

    @model_validator(mode="before")
    @classmethod
    def set_type_automatically(cls, data: Any) -> Any:
        """Automatically set the type field from the class variable, ignoring any input."""
        if isinstance(data, dict):
            # Get the type value from the class variable
            type_value = getattr(cls, "_type_value", None)
            if type_value is not None:
                # Always set it to the class-defined value, ignoring any input
                data["type"] = type_value
        return data

    @model_validator(mode="after")
    def ensure_type_is_correct(self) -> "BaseObj":
        """Ensure the type field is always set to the class-defined value."""
        type_value = getattr(self.__class__, "_type_value", None)
        if type_value is not None:
            self.type = type_value
        return self


"""Final Agent Response Packets"""


# The begining of the final response from the agent, starts with the final best documents
# Not every response will have docs though.
class AgentResponseStart(BaseObj):
    _type_value = StreamingType.MESSAGE_START.value

    # Merged set of all documents considered
    final_documents: list[SavedSearchDoc] | None


# The stream of tokens for the final response
class AgentResponseDelta(BaseObj):
    _type_value = StreamingType.MESSAGE_DELTA.value

    content: str


"""Control Packets"""


class PacketException(BaseObj):
    _type_value = StreamingType.ERROR.value

    exception: Exception
    model_config = {"arbitrary_types_allowed": True}


class OverallStop(BaseObj):
    _type_value = StreamingType.STOP.value


# Currently frontend does not depend on this packet.
class SectionEnd(BaseObj):
    _type_value = StreamingType.SECTION_END.value


"""Tool Packets"""


# Search tool is called and the UI block needs to start
class SearchToolStart(BaseObj):
    _type_value = StreamingType.SEARCH_TOOL_START.value

    is_internet_search: bool = False


# Queries coming through as the LLM determines what to search
# Mostly for query expansions and advanced search strategies
class SearchToolQueriesDelta(BaseObj):
    _type_value = StreamingType.SEARCH_TOOL_QUERIES_DELTA.value

    queries: list[str]


# Documents coming through as the system knows what to add to the context
class SearchToolDocumentsDelta(BaseObj):
    _type_value = StreamingType.SEARCH_TOOL_DOCUMENTS_DELTA.value

    documents: list[SavedSearchDoc]


# This only needs to show which URLs are being fetched
# no need for any further updates on the frontend as the crawling happens
class OpenUrl(BaseObj):
    _type_value = StreamingType.OPEN_URL_START.value

    documents: list[SavedSearchDoc]


# Image generation starting, needs to allocate a placeholder block for it on the UI
class ImageGenerationToolStart(BaseObj):
    _type_value = StreamingType.IMAGE_GENERATION_START.value


# Since image generation can take a while
# we send a heartbeat to the frontend to keep the UI/connection alive
class ImageGenerationToolHeartbeat(BaseObj):
    _type_value = StreamingType.IMAGE_GENERATION_HEARTBEAT.value


# The final generated images all at once at the end of image generation
class ImageGenerationFinal(BaseObj):
    _type_value = StreamingType.IMAGE_GENERATION_FINAL.value

    images: list[GeneratedImage]


# Custom tool being called, first allocate a placeholder block for it on the UI
class CustomToolStart(BaseObj):
    _type_value = StreamingType.CUSTOM_TOOL_START.value

    tool_name: str


# The allowed streamed packets for a custom tool
class CustomToolDelta(BaseObj):
    _type_value = StreamingType.CUSTOM_TOOL_DELTA.value

    tool_name: str
    response_type: str
    # For non-file responses
    data: dict | list | str | int | float | bool | None = None
    # For file-based responses like image/csv
    file_ids: list[str] | None = None


"""Reasoning Packets"""


# Tells the frontend to display the reasoning block
class ReasoningStart(BaseObj):
    _type_value = StreamingType.REASONING_START.value


# The stream of tokens for the reasoning
class ReasoningDelta(BaseObj):
    _type_value = StreamingType.REASONING_DELTA.value

    reasoning: str


"""Citation Packets"""


# Citation info for the sidebar and inline citations
class CitationInfo(BaseObj):
    _type_value = StreamingType.CITATION_INFO.value

    # The numerical number of the citation as provided by the LLM
    citation_number: int
    # The document id of the SearchDoc (same as the field stored in the DB)
    # This is the actual document id from the connector, not the int id
    document_id: str


"""Packet"""

# Discriminated union of all possible packet object types
PacketObj = Annotated[
    Union[
        # Agent Response Packets
        AgentResponseStart,
        AgentResponseDelta,
        # Control Packets
        OverallStop,
        SectionEnd,
        # Error Packets
        PacketException,
        # Tool Packets
        SearchToolStart,
        SearchToolQueriesDelta,
        SearchToolDocumentsDelta,
        ImageGenerationToolStart,
        ImageGenerationToolHeartbeat,
        ImageGenerationFinal,
        OpenUrl,
        CustomToolStart,
        CustomToolDelta,
        # Reasoning Packets
        ReasoningStart,
        ReasoningDelta,
        # Citation Packets
        CitationInfo,
    ],
    Field(discriminator="type"),
]


class Packet(BaseModel):
    turn_index: int
    depth_index: int
    obj: PacketObj


# This is for replaying it back from the DB to the frontend
class EndStepPacketList(BaseModel):
    turn_index: int
    depth_index: int
    packet_list: list[Packet]
