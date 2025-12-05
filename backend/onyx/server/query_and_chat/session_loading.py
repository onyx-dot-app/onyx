from __future__ import annotations

from typing import cast

from sqlalchemy.orm import Session

from onyx.configs.constants import MessageType
from onyx.context.search.models import SavedSearchDoc
from onyx.context.search.models import SearchDoc
from onyx.db.chat import get_db_search_doc_by_id
from onyx.db.chat import translate_db_search_doc_to_saved_search_doc
from onyx.db.models import ChatMessage
from onyx.db.models import ToolCall
from onyx.db.tools import get_tool_by_id
from onyx.server.query_and_chat.streaming_models import AgentResponseDelta
from onyx.server.query_and_chat.streaming_models import AgentResponseStart
from onyx.server.query_and_chat.streaming_models import AgentToolFinal
from onyx.server.query_and_chat.streaming_models import AgentToolStart
from onyx.server.query_and_chat.streaming_models import CitationInfo
from onyx.server.query_and_chat.streaming_models import CustomToolDelta
from onyx.server.query_and_chat.streaming_models import CustomToolStart
from onyx.server.query_and_chat.streaming_models import GeneratedImage
from onyx.server.query_and_chat.streaming_models import ImageGenerationFinal
from onyx.server.query_and_chat.streaming_models import ImageGenerationToolStart
from onyx.server.query_and_chat.streaming_models import OpenUrlDocuments
from onyx.server.query_and_chat.streaming_models import OpenUrlStart
from onyx.server.query_and_chat.streaming_models import OpenUrlUrls
from onyx.server.query_and_chat.streaming_models import OverallStop
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.server.query_and_chat.streaming_models import ReasoningDelta
from onyx.server.query_and_chat.streaming_models import ReasoningStart
from onyx.server.query_and_chat.streaming_models import SearchToolDocumentsDelta
from onyx.server.query_and_chat.streaming_models import SearchToolQueriesDelta
from onyx.server.query_and_chat.streaming_models import SearchToolStart
from onyx.server.query_and_chat.streaming_models import SectionEnd
from onyx.tools.tool_implementations.images.image_generation_tool import (
    ImageGenerationTool,
)
from onyx.tools.tool_implementations.open_url.open_url_tool import OpenURLTool
from onyx.tools.tool_implementations.search.search_tool import SearchTool
from onyx.tools.tool_implementations.web_search.web_search_tool import WebSearchTool
from onyx.utils.logger import setup_logger

logger = setup_logger()


def create_message_packets(
    message_text: str,
    final_documents: list[SearchDoc] | None,
    turn_index: int,
) -> list[Packet]:
    packets: list[Packet] = []

    final_search_docs: list[SearchDoc] | None = None
    if final_documents:
        sorted_final_documents = sorted(
            final_documents, key=lambda x: (x.score or 0.0), reverse=True
        )
        final_search_docs = [
            SearchDoc(**doc.model_dump()) for doc in sorted_final_documents
        ]

    packets.append(
        Packet(
            turn_index=turn_index,
            obj=AgentResponseStart(
                final_documents=final_search_docs,
            ),
        )
    )

    packets.append(
        Packet(
            turn_index=turn_index,
            obj=AgentResponseDelta(
                content=message_text,
            ),
        ),
    )

    packets.append(
        Packet(
            turn_index=turn_index,
            obj=SectionEnd(),
        )
    )

    return packets


def create_citation_packets(
    citation_info_list: list[CitationInfo], turn_index: int
) -> list[Packet]:
    packets: list[Packet] = []

    # Emit each citation as a separate CitationInfo packet
    for citation_info in citation_info_list:
        packets.append(
            Packet(
                turn_index=turn_index,
                obj=citation_info,
            )
        )

    packets.append(Packet(turn_index=turn_index, obj=SectionEnd()))

    return packets


def create_reasoning_packets(reasoning_text: str, turn_index: int) -> list[Packet]:
    packets: list[Packet] = []

    packets.append(Packet(turn_index=turn_index, obj=ReasoningStart()))

    packets.append(
        Packet(
            turn_index=turn_index,
            obj=ReasoningDelta(
                reasoning=reasoning_text,
            ),
        ),
    )

    packets.append(Packet(turn_index=turn_index, obj=SectionEnd()))

    return packets


def create_image_generation_packets(
    images: list[GeneratedImage], turn_index: int
) -> list[Packet]:
    packets: list[Packet] = []

    packets.append(
        Packet(
            turn_index=turn_index,
            obj=ImageGenerationToolStart(),
        )
    )

    packets.append(
        Packet(
            turn_index=turn_index,
            obj=ImageGenerationFinal(images=images),
        ),
    )

    packets.append(Packet(turn_index=turn_index, obj=SectionEnd()))

    return packets


def create_custom_tool_packets(
    tool_name: str,
    response_type: str,
    turn_index: int,
    data: dict | list | str | int | float | bool | None = None,
    file_ids: list[str] | None = None,
) -> list[Packet]:
    packets: list[Packet] = []

    packets.append(
        Packet(
            turn_index=turn_index,
            obj=CustomToolStart(tool_name=tool_name),
        )
    )

    packets.append(
        Packet(
            turn_index=turn_index,
            obj=CustomToolDelta(
                tool_name=tool_name,
                response_type=response_type,
                data=data,
                file_ids=file_ids,
            ),
        ),
    )

    packets.append(Packet(turn_index=turn_index, obj=SectionEnd()))

    return packets


def create_fetch_packets(
    fetch_docs: list[SavedSearchDoc],
    urls: list[str],
    turn_index: int,
) -> list[Packet]:
    packets: list[Packet] = []
    # Emit start packet
    packets.append(
        Packet(
            turn_index=turn_index,
            obj=OpenUrlStart(),
        )
    )
    # Emit URLs packet
    packets.append(
        Packet(
            turn_index=turn_index,
            obj=OpenUrlUrls(urls=urls),
        )
    )
    # Emit documents packet
    packets.append(
        Packet(
            turn_index=turn_index,
            obj=OpenUrlDocuments(
                documents=[SearchDoc(**doc.model_dump()) for doc in fetch_docs]
            ),
        )
    )
    packets.append(Packet(turn_index=turn_index, obj=SectionEnd()))
    return packets


def create_search_packets(
    search_queries: list[str],
    search_docs: list[SavedSearchDoc],
    is_internet_search: bool,
    turn_index: int,
) -> list[Packet]:
    packets: list[Packet] = []

    packets.append(
        Packet(
            turn_index=turn_index,
            obj=SearchToolStart(
                is_internet_search=is_internet_search,
            ),
        )
    )

    # Emit queries if present
    if search_queries:
        packets.append(
            Packet(
                turn_index=turn_index,
                obj=SearchToolQueriesDelta(queries=search_queries),
            ),
        )

    # Emit documents if present
    if search_docs:
        sorted_search_docs = sorted(
            search_docs, key=lambda x: (x.score or 0.0), reverse=True
        )
        packets.append(
            Packet(
                turn_index=turn_index,
                obj=SearchToolDocumentsDelta(
                    documents=[
                        SearchDoc(**doc.model_dump()) for doc in sorted_search_docs
                    ]
                ),
            ),
        )

    packets.append(Packet(turn_index=turn_index, obj=SectionEnd()))

    return packets


def collect_nested_search_data(
    tool_call: "ToolCall",
    db_session: Session,
    include_children: bool = True,
) -> tuple[list[str], list[SavedSearchDoc]]:
    queries: list[str] = []
    docs: list[SavedSearchDoc] = []

    if "_agent_search_queries" in tool_call.tool_call_arguments:
        queries.extend(
            cast(list[str], tool_call.tool_call_arguments["_agent_search_queries"])
        )

    if tool_call.search_docs:
        docs.extend(
            [
                translate_db_search_doc_to_saved_search_doc(doc)
                for doc in tool_call.search_docs
            ]
        )

    if include_children:
        for child_tool_call in tool_call.tool_call_children:
            if child_tool_call.invoked_persona_id is not None:
                child_queries, child_docs = collect_nested_search_data(
                    child_tool_call, db_session, include_children=True
                )
                queries.extend(child_queries)
                docs.extend(child_docs)
            else:
                if child_tool_call.tool_call_arguments.get("queries"):
                    child_queries = cast(
                        list[str], child_tool_call.tool_call_arguments["queries"]
                    )
                    queries.extend(child_queries)
                if child_tool_call.search_docs:
                    docs.extend(
                        [
                            translate_db_search_doc_to_saved_search_doc(doc)
                            for doc in child_tool_call.search_docs
                        ]
                    )

    unique_queries = list(dict.fromkeys(queries))

    seen_doc_ids: set[str] = set()
    unique_docs: list[SavedSearchDoc] = []
    for doc in docs:
        if doc.document_id not in seen_doc_ids:
            seen_doc_ids.add(doc.document_id)
            unique_docs.append(doc)

    return unique_queries, unique_docs


def create_agent_tool_packets(
    agent_name: str,
    agent_id: int,
    response: str,
    turn_index: int,
    search_queries: list[str] | None = None,
    search_docs: list[SavedSearchDoc] | None = None,
    nested_runs: list[dict] | None = None,
) -> list[Packet]:
    packets: list[Packet] = []

    packets.append(
        Packet(
            turn_index=turn_index,
            obj=AgentToolStart(agent_name=agent_name, agent_id=agent_id),
        )
    )

    # Emit SearchToolStart if we have search queries or docs (needed for frontend to show search section)
    if search_queries or search_docs:
        packets.append(
            Packet(
                turn_index=turn_index,
                obj=SearchToolStart(is_internet_search=False),
            )
        )

    if search_queries:
        packets.append(
            Packet(
                turn_index=turn_index,
                obj=SearchToolQueriesDelta(queries=search_queries),
            )
        )

    if search_docs:
        sorted_search_docs = sorted(
            search_docs, key=lambda x: x.score or 0.0, reverse=True
        )
        packets.append(
            Packet(
                turn_index=turn_index,
                obj=SearchToolDocumentsDelta(
                    documents=[
                        SearchDoc(**doc.model_dump()) for doc in sorted_search_docs
                    ]
                ),
            )
        )

    summary = response[:200] + "..." if len(response) > 200 else response
    packets.append(
        Packet(
            turn_index=turn_index,
            obj=AgentToolFinal(
                agent_name=agent_name,
                summary=summary,
                full_response=response,
            ),
        )
    )

    packets.append(Packet(turn_index=turn_index, obj=SectionEnd()))

    if nested_runs:
        for nested in nested_runs:
            nested_agent_name = nested.get("agent_name", "")
            nested_agent_id = nested.get("agent_id", 0)
            nested_response = nested.get("response", "")
            nested_queries = nested.get("search_queries") or []
            nested_docs_raw = nested.get("search_docs") or []
            nested_nested_runs = nested.get("nested_runs") or None

            nested_docs: list[SavedSearchDoc] = []
            for doc_dict in nested_docs_raw:
                try:
                    nested_docs.append(SavedSearchDoc(**doc_dict))
                except Exception:
                    continue

            packets.extend(
                create_agent_tool_packets(
                    agent_name=nested_agent_name,
                    agent_id=nested_agent_id,
                    response=nested_response,
                    turn_index=turn_index,
                    search_queries=nested_queries if nested_queries else None,
                    search_docs=nested_docs if nested_docs else None,
                    nested_runs=nested_nested_runs,
                )
            )

    return packets


def reconstruct_nested_agent_tool_call(
    tool_call: "ToolCall",
    base_turn_index: int,
    agent_counter: list[int],
    db_session: Session,
) -> list[Packet]:
    packets: list[Packet] = []

    if tool_call.invoked_persona_id is None:
        return packets

    invoked_persona = tool_call.invoked_persona
    if not invoked_persona:
        return packets

    # Assign this agent the next sequential turn_index
    current_turn_index = base_turn_index + agent_counter[0]
    agent_counter[0] += 1

    # Collect search queries and docs from this agent and its nested children
    nested_queries, nested_search_docs = collect_nested_search_data(
        tool_call, db_session, include_children=False
    )
    nested_runs = (
        cast(list[dict] | None, tool_call.tool_call_arguments.get("_agent_nested_runs"))
        if tool_call.tool_call_arguments
        else None
    )

    # Create packets for this agent
    packets.extend(
        create_agent_tool_packets(
            agent_name=invoked_persona.name,
            agent_id=invoked_persona.id,
            response=tool_call.tool_call_response,
            turn_index=current_turn_index,
            search_queries=nested_queries if nested_queries else None,
            search_docs=nested_search_docs if nested_search_docs else None,
            nested_runs=nested_runs,
        )
    )

    # Recursively process nested agent tool calls (they'll get the next sequential indices)
    for child_tool_call in tool_call.tool_call_children:
        if child_tool_call.invoked_persona_id is not None:
            # This is a nested agent tool call - recursively process it
            child_packets = reconstruct_nested_agent_tool_call(
                child_tool_call,
                base_turn_index,
                agent_counter,
                db_session,
            )
            packets.extend(child_packets)

    return packets


def translate_assistant_message_to_packets(
    chat_message: ChatMessage,
    db_session: Session,
) -> list[Packet]:
    """
    Translates an assistant message and tool calls to packet format.
    It needs to be a list of list of packets combined into indices for "steps".
    The final answer and citations are also a "step".
    """
    packet_list: list[Packet] = []

    if chat_message.message_type != MessageType.ASSISTANT:
        raise ValueError(f"Chat message {chat_message.id} is not an assistant message")

    if chat_message.tool_calls:
        # Filter to only top-level tool calls (parent_tool_call_id is None)
        top_level_tool_calls = [
            tc for tc in chat_message.tool_calls if tc.parent_tool_call_id is None
        ]

        # Group top-level tool calls by turn_number
        tool_calls_by_turn: dict[int, list] = {}
        for tool_call in top_level_tool_calls:
            turn_num = tool_call.turn_number
            if turn_num not in tool_calls_by_turn:
                tool_calls_by_turn[turn_num] = []
            tool_calls_by_turn[turn_num].append(tool_call)

        # Process each turn in order
        for turn_num in sorted(tool_calls_by_turn.keys()):
            tool_calls_in_turn = tool_calls_by_turn[turn_num]

            # Use a counter to assign sequential turn_index values for nested agents
            # This ensures proper ordering: parent agents get lower indices, nested agents get higher indices
            agent_counter = [0]

            # Process each tool call in this turn
            for tool_call in tool_calls_in_turn:
                try:
                    # Handle agent tools specially - they have invoked_persona_id set
                    if tool_call.invoked_persona_id is not None:
                        # Recursively reconstruct this agent and all nested agents
                        agent_packets = reconstruct_nested_agent_tool_call(
                            tool_call,
                            turn_num,
                            agent_counter,
                            db_session,
                        )
                        packet_list.extend(agent_packets)
                        continue

                    tool = get_tool_by_id(tool_call.tool_id, db_session)

                    # Handle different tool types
                    if tool.in_code_tool_id in [
                        SearchTool.__name__,
                        WebSearchTool.__name__,
                    ]:
                        queries = cast(
                            list[str], tool_call.tool_call_arguments.get("queries", [])
                        )
                        search_docs: list[SavedSearchDoc] = [
                            translate_db_search_doc_to_saved_search_doc(doc)
                            for doc in tool_call.search_docs
                        ]
                        packet_list.extend(
                            create_search_packets(
                                search_queries=queries,
                                search_docs=search_docs,
                                is_internet_search=tool.in_code_tool_id
                                == WebSearchTool.__name__,
                                turn_index=turn_num,
                            )
                        )

                    elif tool.in_code_tool_id == OpenURLTool.__name__:
                        fetch_docs: list[SavedSearchDoc] = [
                            translate_db_search_doc_to_saved_search_doc(doc)
                            for doc in tool_call.search_docs
                        ]
                        # Get URLs from tool_call_arguments
                        urls = cast(
                            list[str], tool_call.tool_call_arguments.get("urls", [])
                        )
                        packet_list.extend(
                            create_fetch_packets(fetch_docs, urls, turn_num)
                        )

                    elif tool.in_code_tool_id == ImageGenerationTool.__name__:
                        if tool_call.generated_images:
                            images = [
                                GeneratedImage(**img)
                                for img in tool_call.generated_images
                            ]
                            packet_list.extend(
                                create_image_generation_packets(images, turn_num)
                            )

                    else:
                        # Custom tool or unknown tool
                        packet_list.extend(
                            create_custom_tool_packets(
                                tool_name=tool.display_name or tool.name,
                                response_type="text",
                                turn_index=turn_num,
                                data=tool_call.tool_call_response,
                            )
                        )

                except Exception as e:
                    logger.warning(f"Error processing tool call {tool_call.id}: {e}")
                    continue

    # Determine the next turn_index for the final message
    # It should come after all tool calls
    max_tool_turn = 0
    if chat_message.tool_calls:
        max_tool_turn = max(tc.turn_number for tc in chat_message.tool_calls)

    citations = chat_message.citations
    citation_info_list: list[CitationInfo] = []

    if citations:
        for citation_num, search_doc_id in citations.items():
            search_doc = get_db_search_doc_by_id(search_doc_id, db_session)
            if search_doc:
                citation_info_list.append(
                    CitationInfo(
                        citation_number=citation_num,
                        document_id=search_doc.document_id,
                    )
                )

    # Message comes after tool calls
    message_turn_index = max_tool_turn + 1

    if chat_message.message:
        packet_list.extend(
            create_message_packets(
                message_text=chat_message.message,
                final_documents=[
                    translate_db_search_doc_to_saved_search_doc(doc)
                    for doc in chat_message.search_docs
                ],
                turn_index=message_turn_index,
            )
        )

    # Citations come after the message
    citation_turn_index = (
        message_turn_index + 1 if citation_info_list else message_turn_index
    )

    if len(citation_info_list) > 0:
        packet_list.extend(
            create_citation_packets(citation_info_list, citation_turn_index)
        )

    # Return the highest turn_index used
    final_turn_index = 0
    if chat_message.message_type == MessageType.ASSISTANT:
        # Determine the final turn based on what was added
        max_tool_turn = 0
        if chat_message.tool_calls:
            max_tool_turn = max(tc.turn_number for tc in chat_message.tool_calls)

        # Start from tool turns, then message, then citations
        final_turn_index = max_tool_turn
        if chat_message.message:
            final_turn_index = max_tool_turn + 1
        if citation_info_list:
            final_turn_index = (
                final_turn_index + 1 if chat_message.message else max_tool_turn + 1
            )

    # Add overall stop packet at the end
    packet_list.append(Packet(turn_index=final_turn_index, obj=OverallStop()))

    return packet_list
