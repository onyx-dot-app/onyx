from collections.abc import Generator
from typing import cast
from typing import Union

from onyx.chat.models import AgenticMessageResponseIDInfo
from onyx.chat.models import AgentSearchPacket
from onyx.chat.models import AllCitations
from onyx.chat.models import AnswerStream
from onyx.chat.models import CustomToolResponse
from onyx.chat.models import FileChatDisplay
from onyx.chat.models import FinalUsedContextDocsResponse
from onyx.chat.models import LLMRelevanceFilterResponse
from onyx.chat.models import MessageResponseIDInfo
from onyx.chat.models import MessageSpecificCitations
from onyx.chat.models import QADocsResponse
from onyx.chat.models import StreamingError
from onyx.chat.models import StreamStopInfo
from onyx.chat.models import UserKnowledgeFilePacket
from onyx.file_store.models import ChatFileType
from onyx.server.query_and_chat.models import ChatMessageDetail
from onyx.server.query_and_chat.streaming_models import CitationInfo
from onyx.server.query_and_chat.streaming_models import OverallStop
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.utils.logger import setup_logger

logger = setup_logger()

COMMON_TOOL_RESPONSE_TYPES = {
    "image": ChatFileType.IMAGE,
    "csv": ChatFileType.CSV,
}

# Type definitions for packet processing
ChatPacket = Union[
    StreamingError,
    QADocsResponse,
    LLMRelevanceFilterResponse,
    FinalUsedContextDocsResponse,
    ChatMessageDetail,
    AllCitations,
    CitationInfo,
    FileChatDisplay,
    CustomToolResponse,
    MessageResponseIDInfo,
    MessageSpecificCitations,
    AgenticMessageResponseIDInfo,
    StreamStopInfo,
    AgentSearchPacket,
    UserKnowledgeFilePacket,
    Packet,
]


def process_streamed_packets(
    answer_processed_output: AnswerStream,
) -> Generator[ChatPacket, None, None]:
    """Process the streamed output from the answer and yield chat packets."""

    last_index = 0

    for packet in answer_processed_output:
        if isinstance(packet, Packet):
            if packet.ind > last_index:
                last_index = packet.ind
        yield cast(ChatPacket, packet)

    # Yield STOP packet to indicate streaming is complete
    yield Packet(ind=last_index, obj=OverallStop())
