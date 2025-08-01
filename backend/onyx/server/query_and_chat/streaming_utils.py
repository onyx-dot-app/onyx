from onyx.chat.models import LlmDoc
from onyx.configs.constants import MessageType
from onyx.server.query_and_chat.models import ChatMessageDetail
from onyx.server.query_and_chat.streaming_models import MessageDelta
from onyx.server.query_and_chat.streaming_models import MessageEnd
from onyx.server.query_and_chat.streaming_models import MessageStart
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.server.query_and_chat.streaming_models import Stop
from onyx.server.query_and_chat.streaming_models import ToolDelta
from onyx.server.query_and_chat.streaming_models import ToolEnd
from onyx.server.query_and_chat.streaming_models import ToolStart


def create_simplified_packets_for_message(
    message: ChatMessageDetail, packet_index_start: int = 0
) -> list[Packet]:
    """
    Convert a ChatMessageDetail into simplified streaming packets that represent
    what would have been sent during the original streaming response.

    Args:
        message: The chat message to convert to packets
        packet_index_start: Starting index for packet numbering

    Returns:
        List of simplified packets representing the message
    """
    packets: list[Packet] = []
    current_index = packet_index_start

    # Only create packets for assistant messages
    if message.message_type != MessageType.ASSISTANT:
        return packets

    # Create SearchTool packets if there are context docs
    if message.context_docs and message.context_docs.top_documents:
        llm_docs = []
        for doc in message.context_docs.top_documents:
            llm_doc = LlmDoc(
                document_id=doc.document_id,
                content=doc.blurb,  # Use blurb as content since SavedSearchDoc doesn't have content
                blurb=doc.blurb,
                semantic_identifier=doc.semantic_identifier,
                source_type=doc.source_type,
                metadata=doc.metadata,
                updated_at=doc.updated_at,
                link=doc.link,
                source_links=None,  # SavedSearchDoc doesn't have source_links
                match_highlights=doc.match_highlights,
            )
            llm_docs.append(llm_doc)

        # TODO: remove
        for _ in range(7):
            # Start search tool
            search_tool_start = ToolStart(
                tool_name="search",
                tool_icon="search",
                tool_main_description=f"{message.rephrased_query or ''}",
            )
            packets.append(Packet(ind=current_index, obj=search_tool_start))

            # Send search results via tool delta
            search_tool_delta = ToolDelta(documents=llm_docs)
            packets.append(Packet(ind=current_index, obj=search_tool_delta))

            # End search tool
            search_tool_end = ToolEnd()
            packets.append(Packet(ind=current_index, obj=search_tool_end))
            current_index += 1

    # Create ImageTool packets if there are image files
    if message.files:
        from onyx.file_store.models import ChatFileType

        image_files = [f for f in message.files if f["type"] == ChatFileType.IMAGE]
        if image_files:
            # Start image tool
            image_tool_start = ToolStart(
                tool_name="image_generation",
                tool_icon="image",
                tool_main_description="Generated images",
            )
            packets.append(Packet(ind=current_index, obj=image_tool_start))

            # Send images via tool delta
            images = []
            for file in image_files:
                images.append(
                    {
                        "id": file["id"],
                        "url": "",  # URL will be constructed by frontend
                        "prompt": file.get("name", "Generated image")
                        or "Generated image",
                    }
                )

            image_tool_delta = ToolDelta(images=images)
            packets.append(Packet(ind=current_index, obj=image_tool_delta))

            # End image tool
            image_tool_end = ToolEnd()
            packets.append(Packet(ind=current_index, obj=image_tool_end))
            current_index += 1

    # Create MESSAGE_START packet
    message_start = MessageStart(id=str(message.message_id), content="")
    packets.append(Packet(ind=current_index, obj=message_start))

    # Create MESSAGE_DELTA packet with the full message content
    # In a real streaming scenario, this would be broken into multiple deltas
    if message.message:
        message_delta = MessageDelta(content=message.message)
        packets.append(Packet(ind=current_index, obj=message_delta))

    # Create MESSAGE_END packet
    message_end = MessageEnd()
    packets.append(Packet(ind=current_index, obj=message_end))
    current_index += 1

    # Create STOP packet
    stop = Stop()
    packets.append(Packet(ind=current_index, obj=stop))

    return packets


def create_simplified_packets_for_session(
    messages: list[ChatMessageDetail],
) -> list[list[Packet]]:
    """
    Convert a list of chat messages into simplified streaming packets organized by message.
    Each inner list contains packets for a single assistant message.

    Args:
        messages: List of chat messages from the session

    Returns:
        List of lists of simplified packets, where each inner list represents one assistant message
    """
    packets_by_message: list[list[Packet]] = []

    for message in messages:
        if message.message_type == MessageType.ASSISTANT:
            message_packets = create_simplified_packets_for_message(message, 0)
            if message_packets:  # Only add if there are actual packets
                packets_by_message.append(message_packets)

    return packets_by_message
