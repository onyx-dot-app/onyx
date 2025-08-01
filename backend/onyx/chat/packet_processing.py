from collections.abc import Generator
from typing import cast
from typing import Union

from sqlalchemy.orm import Session

from onyx.chat.models import AgenticMessageResponseIDInfo
from onyx.chat.models import AgentSearchPacket
from onyx.chat.models import AllCitations
from onyx.chat.models import AnswerPostInfo
from onyx.chat.models import AnswerStream
from onyx.chat.models import CitationInfo
from onyx.chat.models import CustomToolResponse
from onyx.chat.models import ExtendedToolResponse
from onyx.chat.models import FileChatDisplay
from onyx.chat.models import FinalUsedContextDocsResponse
from onyx.chat.models import LLMRelevanceFilterResponse
from onyx.chat.models import MessageResponseIDInfo
from onyx.chat.models import MessageSpecificCitations
from onyx.chat.models import OnyxAnswerPiece
from onyx.chat.models import QADocsResponse
from onyx.chat.models import RefinedAnswerImprovement
from onyx.chat.models import StreamingError
from onyx.chat.models import StreamStopInfo
from onyx.chat.models import StreamStopReason
from onyx.chat.models import SubQuestionKey
from onyx.chat.models import UserKnowledgeFilePacket
from onyx.configs.constants import BASIC_KEY
from onyx.context.search.enums import QueryFlow
from onyx.context.search.enums import SearchType
from onyx.context.search.models import RetrievalDetails
from onyx.context.search.utils import chunks_or_sections_to_search_docs
from onyx.context.search.utils import dedupe_documents
from onyx.context.search.utils import drop_llm_indices
from onyx.context.search.utils import relevant_sections_to_indices
from onyx.db.chat import create_db_search_doc
from onyx.db.chat import create_search_doc_from_user_file
from onyx.db.chat import translate_db_search_doc_to_server_search_doc
from onyx.db.models import SearchDoc as DbSearchDoc
from onyx.db.models import UserFile
from onyx.file_store.models import ChatFileType
from onyx.file_store.models import FileDescriptor
from onyx.file_store.models import InMemoryChatFile
from onyx.file_store.utils import save_files
from onyx.server.query_and_chat.models import ChatMessageDetail
from onyx.server.query_and_chat.streaming_models import MessageDelta
from onyx.server.query_and_chat.streaming_models import MessageEnd
from onyx.server.query_and_chat.streaming_models import MessageStart
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.server.query_and_chat.streaming_models import Stop
from onyx.server.query_and_chat.streaming_models import ToolDelta
from onyx.server.query_and_chat.streaming_models import ToolEnd
from onyx.server.query_and_chat.streaming_models import ToolStart
from onyx.tools.models import ToolCallKickoff
from onyx.tools.models import ToolResponse
from onyx.tools.tool_implementations.custom.custom_tool import (
    CUSTOM_TOOL_RESPONSE_ID,
)
from onyx.tools.tool_implementations.custom.custom_tool import CustomToolCallSummary
from onyx.tools.tool_implementations.images.image_generation_tool import (
    IMAGE_GENERATION_RESPONSE_ID,
)
from onyx.tools.tool_implementations.images.image_generation_tool import (
    ImageGenerationResponse,
)
from onyx.tools.tool_implementations.internet_search.internet_search_tool import (
    INTERNET_SEARCH_RESPONSE_SUMMARY_ID,
)
from onyx.tools.tool_implementations.internet_search.models import (
    InternetSearchResponseSummary,
)
from onyx.tools.tool_implementations.internet_search.utils import (
    internet_search_response_to_search_docs,
)
from onyx.tools.tool_implementations.search.search_tool import (
    FINAL_CONTEXT_DOCUMENTS_ID,
)
from onyx.tools.tool_implementations.search.search_tool import QUERY_FIELD
from onyx.tools.tool_implementations.search.search_tool import (
    SEARCH_RESPONSE_SUMMARY_ID,
)
from onyx.tools.tool_implementations.search.search_tool import SearchResponseSummary
from onyx.tools.tool_implementations.search.search_tool import (
    SECTION_RELEVANCE_LIST_ID,
)
from onyx.tools.tool_implementations.search.search_utils import section_to_llm_doc
from onyx.tools.tool_runner import ToolCallFinalResult
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


def process_tool_response(
    packet: ToolResponse,
    db_session: Session,
    selected_db_search_docs: list[DbSearchDoc] | None,
    info_by_subq: dict[SubQuestionKey, AnswerPostInfo],
    retrieval_options: RetrievalDetails | None,
    user_file_files: list[UserFile] | None,
    user_files: list[InMemoryChatFile] | None,
) -> Generator[ChatPacket, None, dict[SubQuestionKey, AnswerPostInfo]]:
    """Process tool responses and generate appropriate chat packets."""
    level, level_question_num = (
        (packet.level, packet.level_question_num)
        if isinstance(packet, ExtendedToolResponse)
        else BASIC_KEY
    )

    assert level is not None
    assert level_question_num is not None
    info = info_by_subq[SubQuestionKey(level=level, question_num=level_question_num)]

    # TODO: don't need to dedupe here when we do it in agent flow
    if packet.id == SEARCH_RESPONSE_SUMMARY_ID:
        (
            info.qa_docs_response,
            info.reference_db_search_docs,
            info.dropped_indices,
        ) = _handle_search_tool_response_summary(
            packet=packet,
            db_session=db_session,
            selected_search_docs=selected_db_search_docs,
            # Deduping happens at the last step to avoid harming quality by dropping content early on
            dedupe_docs=bool(retrieval_options and retrieval_options.dedupe_docs),
            user_files=[],
            loaded_user_files=[],
        )

        yield info.qa_docs_response
    elif packet.id == SECTION_RELEVANCE_LIST_ID:
        relevance_sections = packet.response

        if info.reference_db_search_docs is None:
            logger.warning("No reference docs found for relevance filtering")
            return info_by_subq

        llm_indices = relevant_sections_to_indices(
            relevance_sections=relevance_sections,
            items=[
                translate_db_search_doc_to_server_search_doc(doc)
                for doc in info.reference_db_search_docs
            ],
        )

        if info.dropped_indices:
            llm_indices = drop_llm_indices(
                llm_indices=llm_indices,
                search_docs=info.reference_db_search_docs,
                dropped_indices=info.dropped_indices,
            )

        yield LLMRelevanceFilterResponse(llm_selected_doc_indices=llm_indices)
    elif packet.id == FINAL_CONTEXT_DOCUMENTS_ID:
        yield FinalUsedContextDocsResponse(final_context_docs=packet.response)

    elif packet.id == IMAGE_GENERATION_RESPONSE_ID:
        img_generation_response = cast(list[ImageGenerationResponse], packet.response)

        file_ids = save_files(
            urls=[img.url for img in img_generation_response if img.url],
            base64_files=[
                img.image_data for img in img_generation_response if img.image_data
            ],
        )
        info.ai_message_files.extend(
            [
                FileDescriptor(id=str(file_id), type=ChatFileType.IMAGE)
                for file_id in file_ids
            ]
        )
        yield FileChatDisplay(file_ids=[str(file_id) for file_id in file_ids])
    elif packet.id == INTERNET_SEARCH_RESPONSE_SUMMARY_ID:
        (
            info.qa_docs_response,
            info.reference_db_search_docs,
        ) = _handle_internet_search_tool_response_summary(
            packet=packet,
            db_session=db_session,
        )
        yield info.qa_docs_response
    elif packet.id == CUSTOM_TOOL_RESPONSE_ID:
        custom_tool_response = cast(CustomToolCallSummary, packet.response)
        response_type = custom_tool_response.response_type
        if response_type in COMMON_TOOL_RESPONSE_TYPES:
            file_ids = custom_tool_response.tool_result.file_ids
            file_type = COMMON_TOOL_RESPONSE_TYPES[response_type]
            info.ai_message_files.extend(
                [
                    FileDescriptor(id=str(file_id), type=file_type)
                    for file_id in file_ids
                ]
            )
            yield FileChatDisplay(file_ids=[str(file_id) for file_id in file_ids])
        else:
            yield CustomToolResponse(
                response=custom_tool_response.tool_result,
                tool_name=custom_tool_response.tool_name,
            )

    return info_by_subq


def _handle_search_tool_response_summary(
    packet: ToolResponse,
    db_session: Session,
    selected_search_docs: list[DbSearchDoc] | None,
    dedupe_docs: bool = False,
    user_files: list[UserFile] | None = None,
    loaded_user_files: list[InMemoryChatFile] | None = None,
) -> tuple[QADocsResponse, list[DbSearchDoc], list[int] | None]:
    """Handle search tool response and create QA docs response."""
    response_summary = cast(SearchResponseSummary, packet.response)

    is_extended = isinstance(packet, ExtendedToolResponse)
    dropped_inds = None

    if not selected_search_docs:
        top_docs = chunks_or_sections_to_search_docs(response_summary.top_sections)

        deduped_docs = top_docs
        if (
            dedupe_docs and not is_extended
        ):  # Extended tool responses are already deduped
            deduped_docs, dropped_inds = dedupe_documents(top_docs)

        reference_db_search_docs = [
            create_db_search_doc(server_search_doc=doc, db_session=db_session)
            for doc in deduped_docs
        ]

    else:
        reference_db_search_docs = selected_search_docs

    doc_ids = {doc.id for doc in reference_db_search_docs}
    if user_files is not None and loaded_user_files is not None:
        for user_file in user_files:
            if user_file.id in doc_ids:
                continue

            associated_chat_file = next(
                (
                    file
                    for file in loaded_user_files
                    if file.file_id == str(user_file.file_id)
                ),
                None,
            )
            # Use create_search_doc_from_user_file to properly add the document to the database
            if associated_chat_file is not None:
                db_doc = create_search_doc_from_user_file(
                    user_file, associated_chat_file, db_session
                )
                reference_db_search_docs.append(db_doc)

    response_docs = [
        translate_db_search_doc_to_server_search_doc(db_search_doc)
        for db_search_doc in reference_db_search_docs
    ]

    level, question_num = None, None
    if isinstance(packet, ExtendedToolResponse):
        level, question_num = packet.level, packet.level_question_num
    return (
        QADocsResponse(
            rephrased_query=response_summary.rephrased_query,
            top_documents=response_docs,
            predicted_flow=response_summary.predicted_flow,
            predicted_search=response_summary.predicted_search,
            applied_source_filters=response_summary.final_filters.source_type,
            applied_time_cutoff=response_summary.final_filters.time_cutoff,
            recency_bias_multiplier=response_summary.recency_bias_multiplier,
            level=level,
            level_question_num=question_num,
        ),
        reference_db_search_docs,
        dropped_inds,
    )


def _handle_internet_search_tool_response_summary(
    packet: ToolResponse,
    db_session: Session,
) -> tuple[QADocsResponse, list[DbSearchDoc]]:
    """Handle internet search tool response and create QA docs response."""
    internet_search_response = cast(InternetSearchResponseSummary, packet.response)
    server_search_docs = internet_search_response_to_search_docs(
        internet_search_response
    )

    reference_db_search_docs = [
        create_db_search_doc(server_search_doc=doc, db_session=db_session)
        for doc in server_search_docs
    ]
    response_docs = [
        translate_db_search_doc_to_server_search_doc(db_search_doc)
        for db_search_doc in reference_db_search_docs
    ]
    return (
        QADocsResponse(
            rephrased_query=internet_search_response.query,
            top_documents=response_docs,
            predicted_flow=QueryFlow.QUESTION_ANSWER,
            predicted_search=SearchType.INTERNET,
            applied_source_filters=[],
            applied_time_cutoff=None,
            recency_bias_multiplier=1.0,
        ),
        reference_db_search_docs,
    )


def process_streamed_packets(
    answer_processed_output: AnswerStream,
    selected_db_search_docs: list[DbSearchDoc] | None,
    info_by_subq: dict[SubQuestionKey, AnswerPostInfo],
    retrieval_options: RetrievalDetails | None,
    user_file_models: list[UserFile] | None,
    in_memory_user_files: list[InMemoryChatFile] | None,
    reserved_message_id: int,
    db_session: Session,
) -> Generator[ChatPacket, None, tuple[dict[SubQuestionKey, AnswerPostInfo], bool]]:
    """Process the streamed output from the answer and yield chat packets."""
    has_transmitted_answer_piece = False
    packet_index = 0
    refined_answer_improvement = True
    current_message_index: int | None = None

    # Track ongoing tool operations to prevent concurrent operations of the same type
    ongoing_search = False
    ongoing_image_generation = False

    for packet in answer_processed_output:
        if isinstance(packet, ToolCallKickoff):
            # Handle image generation tool start
            if (
                packet.tool_name == "run_image_generation"
                and not ongoing_image_generation
            ):
                ongoing_image_generation = True
                yield Packet(
                    ind=packet_index,
                    obj=ToolStart(
                        tool_name="image_generation",
                        tool_icon="🖼️",
                    ),
                )
                packet_index += 1

            if packet.tool_name == "run_search" and not ongoing_search:
                ongoing_search = True
                yield Packet(
                    ind=packet_index,
                    obj=ToolStart(
                        tool_name="search",
                        tool_icon="🔍",
                        tool_main_description=packet.tool_args[QUERY_FIELD],
                    ),
                )
                packet_index += 1

        elif isinstance(packet, ToolResponse):
            if packet.id == SEARCH_RESPONSE_SUMMARY_ID:
                search_response = cast(SearchResponseSummary, packet.response)

                yield Packet(
                    ind=packet_index,
                    obj=ToolDelta(
                        documents=[
                            section_to_llm_doc(s) for s in search_response.top_sections
                        ],
                    ),
                )
                packet_index += 1

                yield Packet(
                    ind=packet_index,
                    obj=ToolEnd(),
                )
                packet_index += 1
                ongoing_search = False  # Reset search state when tool ends

                # Add dummy search tool for simulation purposes
                # TODO: remove
                yield Packet(
                    ind=packet_index,
                    obj=ToolStart(
                        tool_name="search",
                        tool_icon="🔍",
                        tool_main_description="Dummy search for simulation",
                    ),
                )
                packet_index += 1

                yield Packet(
                    ind=packet_index,
                    obj=ToolDelta(
                        documents=[],  # Empty documents for dummy search
                    ),
                )
                packet_index += 1

                yield Packet(
                    ind=packet_index,
                    obj=ToolEnd(),
                )
                packet_index += 1
                # END DUMMY SECTION

            elif packet.id == IMAGE_GENERATION_RESPONSE_ID:
                img_generation_response = cast(
                    list[ImageGenerationResponse], packet.response
                )

                # Save files and get file IDs
                file_ids = save_files(
                    urls=[img.url for img in img_generation_response if img.url],
                    base64_files=[
                        img.image_data
                        for img in img_generation_response
                        if img.image_data
                    ],
                )

                yield Packet(
                    ind=packet_index,
                    obj=ToolDelta(
                        images=[
                            {
                                "id": str(file_id),
                                "url": "",  # URL will be constructed by frontend
                                "prompt": img.revised_prompt,
                            }
                            for file_id, img in zip(file_ids, img_generation_response)
                        ]
                    ),
                )
                packet_index += 1

                # Emit ImageToolEnd packet with file information
                yield Packet(
                    ind=packet_index,
                    obj=ToolEnd(),
                )
                packet_index += 1
                ongoing_image_generation = (
                    False  # Reset image generation state when tool ends
                )

            # Process other tool responses
            info_by_subq = yield from process_tool_response(
                packet=packet,
                db_session=db_session,
                selected_db_search_docs=selected_db_search_docs,
                info_by_subq=info_by_subq,
                retrieval_options=retrieval_options,
                user_file_files=user_file_models,
                user_files=in_memory_user_files,
            )

        elif isinstance(packet, StreamStopInfo):
            if packet.stop_reason == StreamStopReason.FINISHED:
                yield packet
        elif isinstance(packet, RefinedAnswerImprovement):
            refined_answer_improvement = packet.refined_answer_improvement
            yield packet
        elif isinstance(packet, OnyxAnswerPiece):
            if has_transmitted_answer_piece:
                if packet.answer_piece is None:
                    # Message is ending, use current message index
                    if current_message_index is not None:
                        yield Packet(
                            ind=current_message_index,
                            obj=MessageEnd(),
                        )
                    # Reset for next message
                    current_message_index = None
                    has_transmitted_answer_piece = False
                else:
                    # Continue with same index for message delta
                    if current_message_index is not None:
                        yield Packet(
                            ind=current_message_index,
                            obj=MessageDelta(
                                content=packet.answer_piece or "",
                            ),
                        )

            elif packet.answer_piece:
                # New message starting, allocate new index
                current_message_index = packet_index
                packet_index += 1
                yield Packet(
                    ind=current_message_index,
                    obj=MessageStart(
                        id=str(reserved_message_id),
                        content=packet.answer_piece,
                    ),
                )
                has_transmitted_answer_piece = True
        else:
            if isinstance(packet, ToolCallFinalResult):
                level, level_question_num = (
                    (packet.level, packet.level_question_num)
                    if packet.level is not None
                    and packet.level_question_num is not None
                    else BASIC_KEY
                )
                info = info_by_subq[
                    SubQuestionKey(level=level, question_num=level_question_num)
                ]
                info.tool_result = packet

            yield cast(ChatPacket, packet)

    # Yield STOP packet to indicate streaming is complete
    yield Packet(ind=packet_index, obj=Stop())
    return info_by_subq, refined_answer_improvement
