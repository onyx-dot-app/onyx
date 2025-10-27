from __future__ import annotations

import re
from datetime import datetime
from typing import cast

from sqlalchemy.orm import Session

from onyx.agents.agent_search.dr.enums import ResearchType
from onyx.agents.agent_search.dr.sub_agents.image_generation.models import (
    GeneratedImage,
)
from onyx.configs.constants import MessageType
from onyx.context.search.models import SavedSearchDoc
from onyx.db.chat import get_db_search_doc_by_document_id
from onyx.db.chat import get_db_search_doc_by_id
from onyx.db.chat import translate_db_search_doc_to_server_search_doc
from onyx.db.models import ChatMessage
from onyx.db.tools import get_tool_by_id
from onyx.feature_flags.factory import get_default_feature_flag_provider
from onyx.feature_flags.feature_flags_keys import SIMPLE_AGENT_FRAMEWORK
from onyx.server.query_and_chat.streaming_models import CitationDelta
from onyx.server.query_and_chat.streaming_models import CitationInfo
from onyx.server.query_and_chat.streaming_models import CitationStart
from onyx.server.query_and_chat.streaming_models import CustomToolDelta
from onyx.server.query_and_chat.streaming_models import CustomToolStart
from onyx.server.query_and_chat.streaming_models import EndStepPacketList
from onyx.server.query_and_chat.streaming_models import FetchToolStart
from onyx.server.query_and_chat.streaming_models import ImageGenerationToolDelta
from onyx.server.query_and_chat.streaming_models import ImageGenerationToolStart
from onyx.server.query_and_chat.streaming_models import MessageDelta
from onyx.server.query_and_chat.streaming_models import MessageStart
from onyx.server.query_and_chat.streaming_models import OverallStop
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.server.query_and_chat.streaming_models import ReasoningDelta
from onyx.server.query_and_chat.streaming_models import ReasoningStart
from onyx.server.query_and_chat.streaming_models import SearchToolDelta
from onyx.server.query_and_chat.streaming_models import SearchToolStart
from onyx.server.query_and_chat.streaming_models import SectionEnd
from onyx.tools.tool_implementations.images.image_generation_tool import (
    ImageGenerationTool,
)
from onyx.tools.tool_implementations.knowledge_graph.knowledge_graph_tool import (
    KnowledgeGraphTool,
)
from onyx.tools.tool_implementations.okta_profile.okta_profile_tool import (
    OktaProfileTool,
)
from onyx.tools.tool_implementations.search.search_tool import SearchTool
from onyx.tools.tool_implementations.web_search.web_search_tool import WebSearchTool
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
    step_nr: int,
    is_legacy_agentic: bool = False,
) -> list[Packet]:
    packets: list[Packet] = []

    packets.append(
        Packet(
            ind=step_nr,
            obj=MessageStart(
                content="",
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
            ind=step_nr,
            obj=MessageDelta(
                content=adjusted_message_text,
            ),
        ),
    )

    packets.append(
        Packet(
            ind=step_nr,
            obj=SectionEnd(
                type="section_end",
            ),
        )
    )

    return packets


def create_citation_packets(
    citation_info_list: list[CitationInfo], step_nr: int
) -> list[Packet]:
    packets: list[Packet] = []

    packets.append(Packet(ind=step_nr, obj=CitationStart()))

    packets.append(
        Packet(
            ind=step_nr,
            obj=CitationDelta(
                citations=citation_info_list,
            ),
        ),
    )

    packets.append(Packet(ind=step_nr, obj=SectionEnd(type="section_end")))

    return packets


def create_reasoning_packets(reasoning_text: str, step_nr: int) -> list[Packet]:
    packets: list[Packet] = []

    packets.append(Packet(ind=step_nr, obj=ReasoningStart()))

    packets.append(
        Packet(
            ind=step_nr,
            obj=ReasoningDelta(
                reasoning=reasoning_text,
            ),
        ),
    )

    packets.append(Packet(ind=step_nr, obj=SectionEnd(type="section_end")))

    return packets


def create_image_generation_packets(
    images: list[GeneratedImage], step_nr: int
) -> list[Packet]:
    packets: list[Packet] = []

    packets.append(Packet(ind=step_nr, obj=ImageGenerationToolStart()))

    packets.append(
        Packet(
            ind=step_nr,
            obj=ImageGenerationToolDelta(images=images),
        ),
    )

    packets.append(Packet(ind=step_nr, obj=SectionEnd(type="section_end")))

    return packets


def create_custom_tool_packets(
    tool_name: str,
    response_type: str,
    step_nr: int,
    data: dict | list | str | int | float | bool | None = None,
    file_ids: list[str] | None = None,
) -> list[Packet]:
    packets: list[Packet] = []

    packets.append(Packet(ind=step_nr, obj=CustomToolStart(tool_name=tool_name)))

    packets.append(
        Packet(
            ind=step_nr,
            obj=CustomToolDelta(
                tool_name=tool_name,
                response_type=response_type,
                data=data,
                file_ids=file_ids,
            ),
        ),
    )

    packets.append(Packet(ind=step_nr, obj=SectionEnd(type="section_end")))

    return packets


def create_fetch_packets(
    fetches: list[list[SavedSearchDoc]], step_nr: int
) -> list[Packet]:
    packets: list[Packet] = []
    for fetch in fetches:
        packets.append(Packet(ind=step_nr, obj=FetchToolStart(documents=fetch)))
        packets.append(Packet(ind=step_nr, obj=SectionEnd(type="section_end")))
        step_nr += 1
    return packets


def create_search_packets(
    search_queries: list[str],
    saved_search_docs: list[SavedSearchDoc],
    is_internet_search: bool,
    step_nr: int,
) -> list[Packet]:
    packets: list[Packet] = []

    packets.append(
        Packet(
            ind=step_nr,
            obj=SearchToolStart(
                is_internet_search=is_internet_search,
            ),
        )
    )

    packets.append(
        Packet(
            ind=step_nr,
            obj=SearchToolDelta(
                queries=search_queries,
                documents=saved_search_docs,
            ),
        ),
    )

    packets.append(Packet(ind=step_nr, obj=SectionEnd()))

    return packets


def translate_db_message_to_packets_simple(
    chat_message: ChatMessage,
    db_session: Session,
    remove_doc_content: bool = False,
    start_step_nr: int = 1,
) -> EndStepPacketList:
    """
    Translation function for simple agent framework (ResearchType.FAST).
    Includes support for FetchToolStart packets for web fetch operations.
    """
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
                            citation_num=citation_num,
                            document_id=search_doc.document_id,
                        )
                    )
        elif chat_message.search_docs:
            for i, search_doc in enumerate(chat_message.search_docs):
                citation_info_list.append(
                    CitationInfo(
                        citation_num=i,
                        document_id=search_doc.document_id,
                    )
                )

        research_iterations = []
        if chat_message.research_type in [
            ResearchType.THOUGHTFUL,
            ResearchType.DEEP,
            ResearchType.LEGACY_AGENTIC,
            ResearchType.FAST,
        ]:
            research_iterations = sorted(
                chat_message.research_iterations, key=lambda x: x.iteration_nr
            )
            for research_iteration in research_iterations:
                if (
                    research_iteration.iteration_nr > 1
                    and research_iteration.reasoning
                    and chat_message.research_type == ResearchType.DEEP
                ):
                    packet_list.extend(
                        create_reasoning_packets(research_iteration.reasoning, step_nr)
                    )
                    step_nr += 1

                if (
                    research_iteration.purpose
                    and chat_message.research_type == ResearchType.DEEP
                ):
                    packet_list.extend(
                        create_reasoning_packets(research_iteration.purpose, step_nr)
                    )
                    step_nr += 1

                sub_steps = research_iteration.sub_steps
                tasks: list[str] = []
                tool_call_ids: list[int | None] = []
                cited_docs: list[SavedSearchDoc] = []
                fetches: list[list[SavedSearchDoc]] = []
                is_web_fetch: bool = False

                for sub_step in sub_steps:
                    # For v2 tools, use the queries field if available, otherwise fall back to sub_step_instructions
                    if sub_step.queries:
                        tasks.extend(sub_step.queries)
                    else:
                        tasks.append(sub_step.sub_step_instructions or "")
                    tool_call_ids.append(sub_step.sub_step_tool_id)

                    sub_step_cited_docs = sub_step.cited_doc_results
                    sub_step_saved_search_docs: list[SavedSearchDoc] = []
                    if isinstance(sub_step_cited_docs, list):
                        for doc_data in sub_step_cited_docs:
                            doc_data["db_doc_id"] = 1
                            doc_data["boost"] = 1
                            doc_data["hidden"] = False
                            doc_data["chunk_ind"] = 0

                            if (
                                doc_data["updated_at"] is None
                                or doc_data["updated_at"] == "None"
                            ):
                                doc_data["updated_at"] = datetime.now()

                            sub_step_saved_search_docs.append(
                                SavedSearchDoc.from_dict(doc_data)
                                if isinstance(doc_data, dict)
                                else doc_data
                            )

                        cited_docs.extend(sub_step_saved_search_docs)
                    else:
                        if chat_message.research_type == ResearchType.DEEP:
                            packet_list.extend(
                                create_reasoning_packets(
                                    _CANNOT_SHOW_STEP_RESULTS_STR, step_nr
                                )
                            )
                    step_nr += 1

                    if sub_step.is_web_fetch and len(sub_step_saved_search_docs) > 0:
                        is_web_fetch = True
                        fetches.append(sub_step_saved_search_docs)

                if len(set(tool_call_ids)) > 1:
                    if chat_message.research_type == ResearchType.DEEP:
                        packet_list.extend(
                            create_reasoning_packets(
                                _CANNOT_SHOW_STEP_RESULTS_STR, step_nr
                            )
                        )
                    step_nr += 1

                elif len(sub_steps) == 0:
                    # no sub steps, no tool calls. But iteration can have reasoning or purpose
                    continue

                else:
                    tool_id = tool_call_ids[0]
                    if not tool_id:
                        raise ValueError("Tool ID is required")
                    tool = get_tool_by_id(tool_id, db_session)
                    tool_name = tool.name

                    if tool_name in [SearchTool.__name__, KnowledgeGraphTool.__name__]:
                        cited_docs = cast(list[SavedSearchDoc], cited_docs)
                        packet_list.extend(
                            create_search_packets(tasks, cited_docs, False, step_nr)
                        )
                        step_nr += 1

                    elif tool_name == WebSearchTool.__name__:
                        cited_docs = cast(list[SavedSearchDoc], cited_docs)
                        if is_web_fetch:
                            packet_list.extend(create_fetch_packets(fetches, step_nr))
                        else:
                            packet_list.extend(
                                create_search_packets(tasks, cited_docs, True, step_nr)
                            )

                        step_nr += 1

                    elif tool_name == ImageGenerationTool.__name__:
                        if sub_step.generated_images:
                            packet_list.extend(
                                create_image_generation_packets(
                                    sub_step.generated_images.images, step_nr
                                )
                            )
                        step_nr += 1

                    elif tool_name == OktaProfileTool.__name__:
                        packet_list.extend(
                            create_custom_tool_packets(
                                tool_name=tool_name,
                                response_type="text",
                                step_nr=step_nr,
                                data=sub_step.sub_answer,
                            )
                        )
                        step_nr += 1

                    else:
                        packet_list.extend(
                            create_custom_tool_packets(
                                tool_name=tool_name,
                                response_type="text",
                                step_nr=step_nr,
                                data=sub_step.sub_answer,
                            )
                        )
                        step_nr += 1

        if chat_message.message:
            packet_list.extend(
                create_message_packets(
                    message_text=chat_message.message,
                    final_documents=[
                        translate_db_search_doc_to_server_search_doc(doc)
                        for doc in chat_message.search_docs
                    ],
                    step_nr=step_nr,
                    is_legacy_agentic=chat_message.research_type
                    == ResearchType.LEGACY_AGENTIC,
                )
            )
            step_nr += 1

        if len(citation_info_list) > 0 and len(research_iterations) == 0:
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
                create_search_packets([], saved_search_docs, False, step_nr)
            )

            step_nr += 1

    return EndStepPacketList(packet_list=packet_list, end_step_nr=step_nr)


def translate_db_message_to_packets(
    chat_message: ChatMessage,
    db_session: Session,
    remove_doc_content: bool = False,
    start_step_nr: int = 1,
) -> EndStepPacketList:
    use_simple_translation = False
    if chat_message.research_type and chat_message.research_type != ResearchType.DEEP:
        feature_flag_provider = get_default_feature_flag_provider()
        tenant_id = get_current_tenant_id()
        user = chat_message.chat_session.user
        use_simple_translation = feature_flag_provider.feature_enabled_for_user_tenant(
            flag_key=SIMPLE_AGENT_FRAMEWORK,
            user=user,
            tenant_id=tenant_id,
        )

    if use_simple_translation:
        return translate_db_message_to_packets_simple(
            chat_message=chat_message,
            db_session=db_session,
            remove_doc_content=remove_doc_content,
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
                            citation_num=citation_num,
                            document_id=search_doc.document_id,
                        )
                    )
        elif chat_message.search_docs:
            for i, search_doc in enumerate(chat_message.search_docs):
                citation_info_list.append(
                    CitationInfo(
                        citation_num=i,
                        document_id=search_doc.document_id,
                    )
                )

        research_iterations = []
        if chat_message.research_type in [
            ResearchType.THOUGHTFUL,
            ResearchType.DEEP,
            ResearchType.LEGACY_AGENTIC,
        ]:
            research_iterations = sorted(
                chat_message.research_iterations, key=lambda x: x.iteration_nr
            )
            for research_iteration in research_iterations:
                if research_iteration.iteration_nr > 1 and research_iteration.reasoning:
                    packet_list.extend(
                        create_reasoning_packets(research_iteration.reasoning, step_nr)
                    )
                    step_nr += 1

                if research_iteration.purpose:
                    packet_list.extend(
                        create_reasoning_packets(research_iteration.purpose, step_nr)
                    )
                    step_nr += 1

                sub_steps = research_iteration.sub_steps
                tasks: list[str] = []
                tool_call_ids: list[int | None] = []
                cited_docs: list[SavedSearchDoc] = []

                for sub_step in sub_steps:
                    # For v2 tools, use the queries field if available, otherwise fall back to sub_step_instructions
                    if sub_step.queries:
                        tasks.extend(sub_step.queries)
                    else:
                        tasks.append(sub_step.sub_step_instructions or "")
                    tool_call_ids.append(sub_step.sub_step_tool_id)

                    sub_step_cited_docs = sub_step.cited_doc_results
                    if isinstance(sub_step_cited_docs, list):
                        sub_step_saved_search_docs: list[SavedSearchDoc] = []
                        for doc_data in sub_step_cited_docs:
                            doc_data["db_doc_id"] = 1
                            doc_data["boost"] = 1
                            doc_data["hidden"] = False
                            doc_data["chunk_ind"] = 0

                            if (
                                doc_data["updated_at"] is None
                                or doc_data["updated_at"] == "None"
                            ):
                                doc_data["updated_at"] = datetime.now()

                            sub_step_saved_search_docs.append(
                                SavedSearchDoc.from_dict(doc_data)
                                if isinstance(doc_data, dict)
                                else doc_data
                            )

                        cited_docs.extend(sub_step_saved_search_docs)
                    else:
                        packet_list.extend(
                            create_reasoning_packets(
                                _CANNOT_SHOW_STEP_RESULTS_STR, step_nr
                            )
                        )
                    step_nr += 1

                if len(set(tool_call_ids)) > 1:
                    packet_list.extend(
                        create_reasoning_packets(_CANNOT_SHOW_STEP_RESULTS_STR, step_nr)
                    )
                    step_nr += 1

                elif len(sub_steps) == 0:
                    # no sub steps, no tool calls. But iteration can have reasoning or purpose
                    continue

                else:
                    tool_id = tool_call_ids[0]
                    if not tool_id:
                        raise ValueError("Tool ID is required")
                    tool = get_tool_by_id(tool_id, db_session)
                    tool_name = tool.name

                    if tool_name in [SearchTool.__name__, KnowledgeGraphTool.__name__]:
                        cited_docs = cast(list[SavedSearchDoc], cited_docs)
                        packet_list.extend(
                            create_search_packets(tasks, cited_docs, False, step_nr)
                        )
                        step_nr += 1

                    elif tool_name == WebSearchTool.__name__:
                        cited_docs = cast(list[SavedSearchDoc], cited_docs)
                        packet_list.extend(
                            create_search_packets(tasks, cited_docs, True, step_nr)
                        )
                        step_nr += 1

                    elif tool_name == ImageGenerationTool.__name__:
                        if sub_step.generated_images is None:
                            raise ValueError("No generated images found")

                        packet_list.extend(
                            create_image_generation_packets(
                                sub_step.generated_images.images, step_nr
                            )
                        )
                        step_nr += 1

                    elif tool_name == OktaProfileTool.__name__:
                        packet_list.extend(
                            create_custom_tool_packets(
                                tool_name=tool_name,
                                response_type="text",
                                step_nr=step_nr,
                                data=sub_step.sub_answer,
                            )
                        )
                        step_nr += 1

                    else:
                        packet_list.extend(
                            create_custom_tool_packets(
                                tool_name=tool_name,
                                response_type="text",
                                step_nr=step_nr,
                                data=sub_step.sub_answer,
                            )
                        )
                        step_nr += 1

        if chat_message.message:
            packet_list.extend(
                create_message_packets(
                    message_text=chat_message.message,
                    final_documents=[
                        translate_db_search_doc_to_server_search_doc(doc)
                        for doc in chat_message.search_docs
                    ],
                    step_nr=step_nr,
                    is_legacy_agentic=chat_message.research_type
                    == ResearchType.LEGACY_AGENTIC,
                )
            )
            step_nr += 1

        if len(citation_info_list) > 0 and len(research_iterations) == 0:
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
                create_search_packets([], saved_search_docs, False, step_nr)
            )

            step_nr += 1

        packet_list.extend(create_citation_packets(citation_info_list, step_nr))

        step_nr += 1

    packet_list.append(Packet(ind=step_nr, obj=OverallStop()))

    return EndStepPacketList(
        end_step_nr=step_nr,
        packet_list=packet_list,
    )
