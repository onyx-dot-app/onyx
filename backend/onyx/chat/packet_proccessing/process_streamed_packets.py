from collections.abc import Generator
from typing import cast

from onyx.chat.models import AnswerStream
from onyx.chat.models import AnswerStreamPart
from onyx.server.query_and_chat.streaming_models import OverallStop
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.utils.logger import setup_logger

logger = setup_logger()


def process_streamed_packets(
    answer_processed_output: AnswerStream,
) -> Generator[AnswerStreamPart, None, None]:
    """Process the streamed output from the answer and yield chat packets."""

    last_index = 0

    for packet in answer_processed_output:
        if isinstance(packet, Packet):
            if packet.ind > last_index:
                last_index = packet.ind
        yield cast(AnswerStreamPart, packet)

    # Yield STOP packet to indicate streaming is complete
    yield Packet(ind=last_index, obj=OverallStop())
