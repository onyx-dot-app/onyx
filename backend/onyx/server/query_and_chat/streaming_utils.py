from __future__ import annotations

import re

from sqlalchemy.orm import Session

from onyx.configs.constants import MessageType
from onyx.context.search.models import SavedSearchDoc
from onyx.db.chat import get_db_search_doc_by_document_id
from onyx.db.chat import get_db_search_doc_by_id
from onyx.db.chat import translate_db_search_doc_to_server_search_doc
from onyx.db.models import ChatMessage
from onyx.db.tools import get_tool_by_id
from onyx.feature_flags.factory import get_default_feature_flag_provider
from onyx.feature_flags.feature_flags_keys import DISABLE_SIMPLE_AGENT_FRAMEWORK
from onyx.server.query_and_chat.streaming_models import AgentResponseDelta
from onyx.server.query_and_chat.streaming_models import AgentResponseStart
from onyx.server.query_and_chat.streaming_models import CitationInfo
from onyx.server.query_and_chat.streaming_models import CustomToolDelta
from onyx.server.query_and_chat.streaming_models import CustomToolStart
from onyx.server.query_and_chat.streaming_models import EndStepPacketList
from onyx.server.query_and_chat.streaming_models import GeneratedImage
from onyx.server.query_and_chat.streaming_models import ImageGenerationFinal
from onyx.server.query_and_chat.streaming_models import ImageGenerationToolStart
from onyx.server.query_and_chat.streaming_models import OpenUrl
from onyx.server.query_and_chat.streaming_models import OverallStop
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.server.query_and_chat.streaming_models import ReasoningDelta
from onyx.server.query_and_chat.streaming_models import ReasoningStart
from onyx.server.query_and_chat.streaming_models import SearchToolDocumentsDelta
from onyx.server.query_and_chat.streaming_models import SearchToolQueriesDelta
from onyx.server.query_and_chat.streaming_models import SearchToolStart
from onyx.server.query_and_chat.streaming_models import SectionEnd
from onyx.tools.tool_implementations.search.search_tool import SearchTool
from shared_configs.contextvars import get_current_tenant_id


_CANNOT_SHOW_STEP_RESULTS_STR = "[Cannot display step results]"


def _adjust_message_text_for_agent_search_results(
    adjusted_message_text: str, final_documents: list[SavedSearchDoc]
) -> str:
    # Remove all [Q<integer>] patterns (sub-question citations)
    return re.sub(r"\[Q\d+\]", "", adjusted_message_text)


def _replace_d_citations_with_links(
    message_text: str, final_documents: list[SavedSearchDoc]
) -> str:
    def replace_citation(match: re.Match[str]) -> str:
        d_number = match.group(1)
        try:
            doc_index = int(d_number) - 1
            if 0 <= doc_index < len(final_documents):
                doc = final_documents[doc_index]
                link = doc.link if doc.link else ""
                return f"[[{d_number}]]({link})"
            return match.group(0)
        except (ValueError, IndexError):
            return match.group(0)

    return re.sub(r"\[D(\d+)\]", replace_citation, message_text)


def create_message_packets(
    message_text: str,
    final_documents: list[SavedSearchDoc] | None,
    turn_index: int,
    is_legacy_agentic: bool = False,
) -> list[Packet]:
    packets: list[Packet] = []

    packets.append(
        Packet(
            turn_index=turn_index,
            obj=AgentResponseStart(
                final_documents=final_documents,
            ),
        )
    )

    adjusted_message_text = message_text
    if is_legacy_agentic:
        if final_documents is not None:
            adjusted_message_text = _adjust_message_text_for_agent_search_results(
                message_text, final_documents
            )
            adjusted_message_text = _replace_d_citations_with_links(
                adjusted_message_text, final_documents
            )
        else:
            adjusted_message_text = re.sub(r"\[Q\d+\]", "", message_text)

    packets.append(
        Packet(
            turn_index=turn_index,
            obj=AgentResponseDelta(
                content=adjusted_message_text,
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
    fetches: list[list[SavedSearchDoc]], turn_index: int
) -> list[Packet]:
    packets: list[Packet] = []
    for fetch in fetches:
        packets.append(
            Packet(
                turn_index=turn_index,
                obj=OpenUrl(documents=fetch),
            )
        )
        packets.append(Packet(turn_index=turn_index, obj=SectionEnd()))
    return packets


def create_search_packets(
    search_queries: list[str],
    saved_search_docs: list[SavedSearchDoc],
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
    if saved_search_docs:
        packets.append(
            Packet(
                turn_index=turn_index,
                obj=SearchToolDocumentsDelta(documents=saved_search_docs),
            ),
        )

    packets.append(Packet(turn_index=turn_index, obj=SectionEnd()))

    return packets


def translate_db_message_to_packets_simple(
    chat_message: ChatMessage,
    db_session: Session,
) -> EndStepPacketList:
    """
    Translation function for simple agent framework.
    Translates ChatMessage with tool_calls to packet format.
    """
    packet_list: list[Packet] = []

    if chat_message.message_type == MessageType.ASSISTANT:
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

        # Process tool calls if they exist
        if chat_message.tool_calls:
            # Group tool calls by turn_number
            tool_calls_by_turn: dict[int, list] = {}
            for tool_call in chat_message.tool_calls:
                turn_num = tool_call.turn_number
                if turn_num not in tool_calls_by_turn:
                    tool_calls_by_turn[turn_num] = []
                tool_calls_by_turn[turn_num].append(tool_call)

            # Process each turn in order
            for turn_num in sorted(tool_calls_by_turn.keys()):
                tool_calls_in_turn = tool_calls_by_turn[turn_num]

                # Process each tool call in this turn
                for tool_call in tool_calls_in_turn:
                    try:
                        tool = get_tool_by_id(tool_call.tool_id, db_session)
                        tool_name = tool.in_code_tool_id or tool.name

                        # Convert search_docs to SavedSearchDoc format
                        saved_search_docs: list[SavedSearchDoc] = []
                        if tool_call.search_docs:
                            for doc in tool_call.search_docs:
                                saved_search_docs.append(
                                    translate_db_search_doc_to_server_search_doc(doc)
                                )

                        # Handle different tool types
                        if tool_name == SearchTool.NAME:
                            # Extract queries from tool_call_arguments
                            queries = tool_call.tool_call_arguments.get("queries", [])
                            if isinstance(queries, str):
                                queries = [queries]

                            packet_list.extend(
                                create_search_packets(
                                    queries, saved_search_docs, False, turn_num
                                )
                            )

                        elif tool_name == "WebSearchTool":
                            # Extract queries from tool_call_arguments
                            queries = tool_call.tool_call_arguments.get("queries", [])
                            if isinstance(queries, str):
                                queries = [queries]

                            # Check if this is a fetch operation (has URLs in response)
                            if saved_search_docs and any(
                                doc.link for doc in saved_search_docs
                            ):
                                packet_list.extend(
                                    create_fetch_packets([saved_search_docs], turn_num)
                                )
                            else:
                                packet_list.extend(
                                    create_search_packets(
                                        queries, saved_search_docs, True, turn_num
                                    )
                                )

                        elif tool_name == "ImageGenerationTool":
                            # Extract images from tool_call_response or arguments
                            # For now, skip if we can't parse images properly
                            pass

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
                        # Log error but continue processing
                        import logging

                        logger = logging.getLogger(__name__)
                        logger.warning(
                            f"Error processing tool call {tool_call.id}: {e}"
                        )
                        continue

        # Determine the next turn_index for the final message
        # It should come after all tool calls
        max_tool_turn = 0
        if chat_message.tool_calls:
            max_tool_turn = max(tc.turn_number for tc in chat_message.tool_calls)

        # Message comes after tool calls
        message_turn_index = max_tool_turn + 1

        if chat_message.message:
            packet_list.extend(
                create_message_packets(
                    message_text=chat_message.message,
                    final_documents=[
                        translate_db_search_doc_to_server_search_doc(doc)
                        for doc in chat_message.search_docs
                    ],
                    turn_index=message_turn_index,
                    is_legacy_agentic=False,
                )
            )

        # Citations come after the message
        citation_turn_index = (
            message_turn_index + 1 if citation_info_list else message_turn_index
        )

        if len(citation_info_list) > 0:
            saved_search_docs: list[SavedSearchDoc] = []
            for citation_info in citation_info_list:
                cited_doc = get_db_search_doc_by_document_id(
                    citation_info.document_id, db_session
                )
                if cited_doc:
                    saved_search_docs.append(
                        translate_db_search_doc_to_server_search_doc(cited_doc)
                    )

            packet_list.extend(
                create_search_packets([], saved_search_docs, False, citation_turn_index)
            )

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

    return EndStepPacketList(
        turn_index=final_turn_index,
        packet_list=packet_list,
    )


def translate_db_message_to_packets(
    chat_message: ChatMessage,
    db_session: Session,
    start_step_nr: int = 1,
) -> EndStepPacketList:
    feature_flag_provider = get_default_feature_flag_provider()
    tenant_id = get_current_tenant_id()
    user = chat_message.chat_session.user
    use_simple_translation = not feature_flag_provider.feature_enabled_for_user_tenant(
        flag_key=DISABLE_SIMPLE_AGENT_FRAMEWORK,
        user=user,
        tenant_id=tenant_id,
    )

    if use_simple_translation:
        return translate_db_message_to_packets_simple(
            chat_message=chat_message,
            db_session=db_session,
            start_step_nr=start_step_nr,
        )

    step_nr = start_step_nr
    packet_list: list[Packet] = []

    if chat_message.message_type == MessageType.ASSISTANT:
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
        elif chat_message.search_docs:
            for i, search_doc in enumerate(chat_message.search_docs):
                citation_info_list.append(
                    CitationInfo(
                        citation_number=i,
                        document_id=search_doc.document_id,
                    )
                )

        # research_iterations = []
        # if chat_message.research_iterations:
        #     research_iterations = sorted(
        #         chat_message.research_iterations, key=lambda x: x.iteration_nr
        #     )
        #     for research_iteration in research_iterations:
        #         if research_iteration.iteration_nr > 1 and research_iteration.reasoning:
        #             packet_list.extend(
        #                 create_reasoning_packets(research_iteration.reasoning, step_nr)
        #             )
        #             step_nr += 1

        #         if research_iteration.purpose:
        #             packet_list.extend(
        #                 create_reasoning_packets(research_iteration.purpose, step_nr)
        #             )
        #             step_nr += 1

        #         sub_steps = research_iteration.sub_steps
        #         tasks: list[str] = []
        #         tool_call_ids: list[int | None] = []
        #         cited_docs: list[SavedSearchDoc] = []

        #         for sub_step in sub_steps:
        #             # For v2 tools, use the queries field if available, otherwise fall back to sub_step_instructions
        #             if sub_step.queries:
        #                 tasks.extend(sub_step.queries)
        #             else:
        #                 tasks.append(sub_step.sub_step_instructions or "")
        #             tool_call_ids.append(sub_step.sub_step_tool_id)

        #             sub_step_cited_docs = sub_step.cited_doc_results
        #             if isinstance(sub_step_cited_docs, list):
        #                 sub_step_saved_search_docs: list[SavedSearchDoc] = []
        #                 for doc_data in sub_step_cited_docs:
        #                     doc_data["db_doc_id"] = 1
        #                     doc_data["boost"] = 1
        #                     doc_data["hidden"] = False
        #                     doc_data["chunk_ind"] = 0

        #                     if (
        #                         doc_data["updated_at"] is None
        #                         or doc_data["updated_at"] == "None"
        #                     ):
        #                         doc_data["updated_at"] = datetime.now()

        #                     sub_step_saved_search_docs.append(
        #                         SavedSearchDoc.from_dict(doc_data)
        #                         if isinstance(doc_data, dict)
        #                         else doc_data
        #                     )

        #                 cited_docs.extend(sub_step_saved_search_docs)
        #             else:
        #                 packet_list.extend(
        #                     create_reasoning_packets(
        #                         _CANNOT_SHOW_STEP_RESULTS_STR, step_nr
        #                     )
        #                 )
        #             step_nr += 1

        #         if len(set(tool_call_ids)) > 1:
        #             packet_list.extend(
        #                 create_reasoning_packets(_CANNOT_SHOW_STEP_RESULTS_STR, step_nr)
        #             )
        #             step_nr += 1

        #         elif len(sub_steps) == 0:
        #             # no sub steps, no tool calls. But iteration can have reasoning or purpose
        #             continue

        #         else:
        #             tool_id = tool_call_ids[0]
        #             if not tool_id:
        #                 raise ValueError("Tool ID is required")
        #             tool = get_tool_by_id(tool_id, db_session)
        #             tool_name = tool.name

        #             if tool_name in [SearchTool.__name__, KnowledgeGraphTool.__name__]:
        #                 cited_docs = cast(list[SavedSearchDoc], cited_docs)
        #                 packet_list.extend(
        #                     create_search_packets(tasks, cited_docs, False, step_nr)
        #                 )
        #                 step_nr += 1

        #             elif tool_name == WebSearchTool.__name__:
        #                 cited_docs = cast(list[SavedSearchDoc], cited_docs)
        #                 packet_list.extend(
        #                     create_search_packets(tasks, cited_docs, True, step_nr)
        #                 )
        #                 step_nr += 1

        #             elif tool_name == ImageGenerationTool.__name__:
        #                 if sub_step.generated_images is None:
        #                     raise ValueError("No generated images found")

        #                 packet_list.extend(
        #                     create_image_generation_packets(
        #                         sub_step.generated_images.images, step_nr
        #                     )
        #                 )
        #                 step_nr += 1

        #             else:
        #                 packet_list.extend(
        #                     create_custom_tool_packets(
        #                         tool_name=tool_name,
        #                         response_type="text",
        #                         step_nr=step_nr,
        #                         data=sub_step.sub_answer,
        #                     )
        #                 )
        #                 step_nr += 1

        turn_index = getattr(chat_message, "turn_index", 0)

        if chat_message.message:
            packet_list.extend(
                create_message_packets(
                    message_text=chat_message.message,
                    final_documents=[
                        translate_db_search_doc_to_server_search_doc(doc)
                        for doc in chat_message.search_docs
                    ],
                    turn_index=turn_index,
                    is_legacy_agentic=False,
                )
            )
            step_nr += 1

        if len(citation_info_list) > 0:
            saved_search_docs: list[SavedSearchDoc] = []
            for citation_info in citation_info_list:
                cited_doc = get_db_search_doc_by_document_id(
                    citation_info.document_id, db_session
                )
                if cited_doc:
                    saved_search_docs.append(
                        translate_db_search_doc_to_server_search_doc(cited_doc)
                    )

            packet_list.extend(
                create_search_packets([], saved_search_docs, False, turn_index)
            )

            step_nr += 1

        packet_list.extend(create_citation_packets(citation_info_list, turn_index))

        step_nr += 1

    turn_index = getattr(chat_message, "turn_index", 0)
    packet_list.append(Packet(turn_index=turn_index, obj=OverallStop()))

    return EndStepPacketList(
        turn_index=getattr(chat_message, "turn_index", 0),
        packet_list=packet_list,
    )
