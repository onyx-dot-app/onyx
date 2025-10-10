from collections import OrderedDict
from collections.abc import Mapping
from enum import Enum
from typing import Annotated
from typing import Literal
from typing import Union

from pydantic import BaseModel
from pydantic import Field

from onyx.agents.agent_search.dr.models import GeneratedImage
from onyx.context.search.models import SavedSearchDoc


class BaseObj(BaseModel):
    type: str = ""


"""Basic Message Packets"""


class MessageStart(BaseObj):
    type: Literal["message_start"] = "message_start"

    # Merged set of all documents considered
    final_documents: list[SavedSearchDoc] | None

    content: str


class MessageDelta(BaseObj):
    content: str
    type: Literal["message_delta"] = "message_delta"


"""Control Packets"""


class PacketException(BaseObj):
    type: Literal["error"] = "error"
    exception: Exception
    model_config = {"arbitrary_types_allowed": True}


class OverallStop(BaseObj):
    type: Literal["stop"] = "stop"


class SectionEnd(BaseObj):
    type: Literal["section_end"] = "section_end"


"""Tool Packets"""


class SearchToolStart(BaseObj):
    type: Literal["internal_search_tool_start"] = "internal_search_tool_start"

    is_internet_search: bool = False


class SearchToolDelta(BaseObj):
    type: Literal["internal_search_tool_delta"] = "internal_search_tool_delta"

    queries: list[str]
    documents: list[SavedSearchDoc]


class FetchToolStart(BaseObj):
    type: Literal["fetch_tool_start"] = "fetch_tool_start"

    documents: list[SavedSearchDoc]


class ImageGenerationToolStart(BaseObj):
    type: Literal["image_generation_tool_start"] = "image_generation_tool_start"


class ImageGenerationToolDelta(BaseObj):
    type: Literal["image_generation_tool_delta"] = "image_generation_tool_delta"

    images: list[GeneratedImage]


class ImageGenerationToolHeartbeat(BaseObj):
    type: Literal["image_generation_tool_heartbeat"] = "image_generation_tool_heartbeat"


class CustomToolStart(BaseObj):
    type: Literal["custom_tool_start"] = "custom_tool_start"

    tool_name: str


class CustomToolDelta(BaseObj):
    type: Literal["custom_tool_delta"] = "custom_tool_delta"

    tool_name: str
    response_type: str
    # For non-file responses
    data: dict | list | str | int | float | bool | None = None
    # For file-based responses like image/csv
    file_ids: list[str] | None = None


"""Reasoning Packets"""


class ReasoningStart(BaseObj):
    type: Literal["reasoning_start"] = "reasoning_start"


class ReasoningDelta(BaseObj):
    type: Literal["reasoning_delta"] = "reasoning_delta"

    reasoning: str


"""Citation Packets"""


class CitationStart(BaseObj):
    type: Literal["citation_start"] = "citation_start"


class SubQuestionIdentifier(BaseModel):
    """None represents references to objects in the original flow. To our understanding,
    these will not be None in the packets returned from agent search.
    """

    level: int | None = None
    level_question_num: int | None = None

    @staticmethod
    def make_dict_by_level(
        original_dict: Mapping[tuple[int, int], "SubQuestionIdentifier"],
    ) -> dict[int, list["SubQuestionIdentifier"]]:
        """returns a dict of level to object list (sorted by level_question_num)
        Ordering is asc for readability.
        """

        # organize by level, then sort ascending by question_index
        level_dict: dict[int, list[SubQuestionIdentifier]] = {}

        # group by level
        for k, obj in original_dict.items():
            level = k[0]
            if level not in level_dict:
                level_dict[level] = []
            level_dict[level].append(obj)

        # for each level, sort the group
        for k2, value2 in level_dict.items():
            # we need to handle the none case due to SubQuestionIdentifier typing
            # level_question_num as int | None, even though it should never be None here.
            level_dict[k2] = sorted(
                value2,
                key=lambda x: (x.level_question_num is None, x.level_question_num),
            )

        # sort by level
        sorted_dict = OrderedDict(sorted(level_dict.items()))
        return sorted_dict


class CitationInfo(SubQuestionIdentifier):
    citation_num: int
    document_id: str


class CitationDelta(BaseObj):
    type: Literal["citation_delta"] = "citation_delta"

    citations: list[CitationInfo] | None = None


"""Packet"""

# Discriminated union of all possible packet object types
PacketObj = Annotated[
    Union[
        MessageStart,
        MessageDelta,
        OverallStop,
        SectionEnd,
        SearchToolStart,
        SearchToolDelta,
        ImageGenerationToolStart,
        ImageGenerationToolDelta,
        ImageGenerationToolHeartbeat,
        CustomToolStart,
        CustomToolDelta,
        ReasoningStart,
        ReasoningDelta,
        CitationStart,
        CitationDelta,
        PacketException,
        FetchToolStart,
    ],
    Field(discriminator="type"),
]


class Packet(BaseModel):
    ind: int
    obj: PacketObj


class EndStepPacketList(BaseModel):
    end_step_nr: int
    packet_list: list[Packet]


class StreamingType(Enum):
    MESSAGE_START = "message_start"
    MESSAGE_DELTA = "message_delta"
    INTERNAL_SEARCH_TOOL_START = "internal_search_tool_start"
    INTERNAL_SEARCH_TOOL_DELTA = "internal_search_tool_delta"
    IMAGE_GENERATION_TOOL_START = "image_generation_tool_start"
    IMAGE_GENERATION_TOOL_DELTA = "image_generation_tool_delta"
    REASONING_START = "reasoning_start"
    REASONING_DELTA = "reasoning_delta"
    CITATION_START = "citation_start"
    CITATION_DELTA = "citation_delta"
    CUSTOM_TOOL_START = "custom_tool_start"
    CUSTOM_TOOL_DELTA = "custom_tool_delta"
