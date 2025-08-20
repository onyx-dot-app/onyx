from onyx.configs.constants import MessageType
from onyx.file_store.models import ChatFileType
from onyx.server.query_and_chat.models import ChatMessageDetail
from onyx.server.query_and_chat.streaming_models import CitationDelta
from onyx.server.query_and_chat.streaming_models import CitationInfo
from onyx.server.query_and_chat.streaming_models import CitationStart
from onyx.server.query_and_chat.streaming_models import CustomToolDelta
from onyx.server.query_and_chat.streaming_models import CustomToolStart
from onyx.server.query_and_chat.streaming_models import ImageGenerationToolDelta
from onyx.server.query_and_chat.streaming_models import ImageGenerationToolStart
from onyx.server.query_and_chat.streaming_models import MessageDelta
from onyx.server.query_and_chat.streaming_models import MessageStart
from onyx.server.query_and_chat.streaming_models import OverallStop
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.server.query_and_chat.streaming_models import SearchToolDelta
from onyx.server.query_and_chat.streaming_models import SearchToolStart
from onyx.server.query_and_chat.streaming_models import SectionEnd


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

    # Handle all tool-related packets in one unified block
    # Check for tool calls first, then fall back to inferred tools from context/files
    if message.tool_call:
        tool_call = message.tool_call

        # Handle different tool types based on tool name
        if tool_call.tool_name == "run_search":
            # Handle search tools - create search tool packets
            # Use context docs if available, otherwise use tool result
            if message.context_docs and message.context_docs.top_documents:
                search_docs = message.context_docs.top_documents

                # Start search tool
                packets.append(
                    Packet(
                        ind=current_index,
                        obj=SearchToolStart(),
                    )
                )

                # Include queries and documents in the delta
                if message.rephrased_query and message.rephrased_query.strip():
                    queries = [str(message.rephrased_query)]
                else:
                    queries = [message.message]

                packets.append(
                    Packet(
                        ind=current_index,
                        obj=SearchToolDelta(
                            queries=queries,
                            documents=search_docs,
                        ),
                    )
                )

                # End search tool
                packets.append(
                    Packet(
                        ind=current_index,
                        obj=SectionEnd(),
                    )
                )
                current_index += 1

        elif tool_call.tool_name == "run_image_generation":
            # Handle image generation tools - create image generation packets
            # Use files if available, otherwise create from tool result
            if message.files:
                image_files = [
                    f for f in message.files if f["type"] == ChatFileType.IMAGE
                ]
                if image_files:
                    # Start image tool
                    image_tool_start = ImageGenerationToolStart()
                    packets.append(Packet(ind=current_index, obj=image_tool_start))

                    # Send images via tool delta
                    images = []
                    for file in image_files:
                        images.append(
                            {
                                "id": file["id"],
                                "url": "",  # URL will be constructed by frontend
                                "prompt": file.get("name") or "Generated image",
                            }
                        )

                    image_tool_delta = ImageGenerationToolDelta(images=images)
                    packets.append(Packet(ind=current_index, obj=image_tool_delta))

                    # End image tool
                    image_tool_end = SectionEnd()
                    packets.append(Packet(ind=current_index, obj=image_tool_end))
                    current_index += 1

        elif tool_call.tool_name == "run_internet_search":
            # Internet search tools return document data, but should be treated as custom tools
            # for packet purposes since they have a different data structure
            # Start custom tool
            custom_tool_start = CustomToolStart(tool_name=tool_call.tool_name)
            packets.append(Packet(ind=current_index, obj=custom_tool_start))

            # Send internet search results as custom tool data
            custom_tool_delta = CustomToolDelta(
                tool_name=tool_call.tool_name,
                response_type="json",
                data=tool_call.tool_result,
                file_ids=None,
            )
            packets.append(Packet(ind=current_index, obj=custom_tool_delta))

            # End custom tool
            custom_tool_end = SectionEnd()
            packets.append(Packet(ind=current_index, obj=custom_tool_end))
            current_index += 1

        else:
            # Handle custom tools and any other tool types
            # Start custom tool
            custom_tool_start = CustomToolStart(tool_name=tool_call.tool_name)
            packets.append(Packet(ind=current_index, obj=custom_tool_start))

            # Determine response type and data from tool result
            response_type = "json"  # default
            data = None
            file_ids = None

            if tool_call.tool_result:
                # Check if it's a custom tool call summary (most common case)
                if isinstance(tool_call.tool_result, dict):
                    # Try to extract response_type if it's structured like CustomToolCallSummary
                    if "response_type" in tool_call.tool_result:
                        response_type = tool_call.tool_result["response_type"]
                        tool_result = tool_call.tool_result.get("tool_result")

                        # Handle file-based responses
                        if isinstance(tool_result, dict) and "file_ids" in tool_result:
                            file_ids = tool_result["file_ids"]
                        else:
                            data = tool_result
                    else:
                        # Plain dict response
                        data = tool_call.tool_result
                else:
                    # Non-dict response (string, number, etc.)
                    data = tool_call.tool_result

            # Send tool response via tool delta
            custom_tool_delta = CustomToolDelta(
                tool_name=tool_call.tool_name,
                response_type=response_type,
                data=data,
                file_ids=file_ids,
            )
            packets.append(Packet(ind=current_index, obj=custom_tool_delta))

            # End custom tool
            custom_tool_end = SectionEnd()
            packets.append(Packet(ind=current_index, obj=custom_tool_end))
            current_index += 1

    # Fallback handling for when there's no explicit tool_call but we have tool-related data
    elif message.context_docs and message.context_docs.top_documents:
        # Handle search results without explicit tool call (legacy support)
        search_docs = message.context_docs.top_documents

        # Start search tool
        packets.append(
            Packet(
                ind=current_index,
                obj=SearchToolStart(),
            )
        )

        # Include queries and documents in the delta
        if message.rephrased_query and message.rephrased_query.strip():
            queries = [str(message.rephrased_query)]
        else:
            queries = [message.message]
        packets.append(
            Packet(
                ind=current_index,
                obj=SearchToolDelta(
                    queries=queries,
                    documents=search_docs,
                ),
            )
        )

        # End search tool
        packets.append(
            Packet(
                ind=current_index,
                obj=SectionEnd(),
            )
        )
        current_index += 1

    # Handle image files without explicit tool call (legacy support)
    if message.files:
        image_files = [f for f in message.files if f["type"] == ChatFileType.IMAGE]
        if image_files and not message.tool_call:
            # Only create image packets if there's no tool call that might have handled them
            # Start image tool
            image_tool_start = ImageGenerationToolStart()
            packets.append(Packet(ind=current_index, obj=image_tool_start))

            # Send images via tool delta
            images = []
            for file in image_files:
                images.append(
                    {
                        "id": file["id"],
                        "url": "",  # URL will be constructed by frontend
                        "prompt": file.get("name") or "Generated image",
                    }
                )

            image_tool_delta = ImageGenerationToolDelta(images=images)
            packets.append(Packet(ind=current_index, obj=image_tool_delta))

            # End image tool
            image_tool_end = SectionEnd()
            packets.append(Packet(ind=current_index, obj=image_tool_end))
            current_index += 1

    # Create Citation packets if there are citations
    if message.citations:
        # Start citation flow
        citation_start = CitationStart()
        packets.append(Packet(ind=current_index, obj=citation_start))

        # Create citation data
        # Convert dict[int, int] to list[StreamingCitation] format
        citations_list: list[CitationInfo] = []
        for citation_num, doc_id in message.citations.items():
            citation = CitationInfo(citation_num=citation_num, document_id=str(doc_id))
            citations_list.append(citation)

        # Send citations via citation delta
        citation_delta = CitationDelta(citations=citations_list)
        packets.append(Packet(ind=current_index, obj=citation_delta))

        # End citation flow
        citation_end = SectionEnd()
        packets.append(Packet(ind=current_index, obj=citation_end))
        current_index += 1

    # Create MESSAGE_START packet
    message_start = MessageStart(
        content="",
        final_documents=(
            message.context_docs.top_documents if message.context_docs else None
        ),
    )
    packets.append(Packet(ind=current_index, obj=message_start))

    # Create MESSAGE_DELTA packet with the full message content
    # In a real streaming scenario, this would be broken into multiple deltas
    if message.message:
        message_delta = MessageDelta(content=message.message)
        packets.append(Packet(ind=current_index, obj=message_delta))

    # Create MESSAGE_END packet
    message_end = SectionEnd()
    packets.append(Packet(ind=current_index, obj=message_end))
    current_index += 1

    # Create STOP packet
    stop = OverallStop()
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
