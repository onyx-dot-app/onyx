from collections.abc import Iterator
from typing import cast

from langchain_core.messages import AIMessageChunk
from langchain_core.messages import BaseMessage
from langgraph.types import StreamWriter
from pydantic import BaseModel

from onyx.agents.agent_search.shared_graph_utils.utils import write_custom_event
from onyx.chat.chat_utils import saved_search_docs_from_llm_docs
from onyx.chat.models import AgentAnswerPiece
from onyx.chat.models import CitationInfo
from onyx.chat.models import LlmDoc
from onyx.chat.models import OnyxAnswerPiece
from onyx.chat.stream_processing.answer_response_handler import AnswerResponseHandler
from onyx.chat.stream_processing.answer_response_handler import CitationResponseHandler
from onyx.chat.stream_processing.answer_response_handler import (
    PassThroughAnswerResponseHandler,
)
from onyx.chat.stream_processing.utils import map_document_id_order
from onyx.context.search.models import InferenceSection
from onyx.server.query_and_chat.streaming_models import CitationDelta
from onyx.server.query_and_chat.streaming_models import CitationStart
from onyx.server.query_and_chat.streaming_models import MessageDelta
from onyx.server.query_and_chat.streaming_models import MessageStart
from onyx.server.query_and_chat.streaming_models import SectionEnd
from onyx.utils.logger import setup_logger

logger = setup_logger()


class BasicSearchProcessedStreamResults(BaseModel):
    ai_message_chunk: AIMessageChunk = AIMessageChunk(content="")
    full_answer: str | None = None
    cited_references: list[InferenceSection] = []
    retrieved_documents: list[LlmDoc] = []


def process_llm_stream(
    messages: Iterator[BaseMessage],
    should_stream_answer: bool,
    writer: StreamWriter,
    ind: int,
    final_search_results: list[LlmDoc] | None = None,
    displayed_search_results: list[LlmDoc] | None = None,
    generate_final_answer: bool = False,
    chat_message_id: str | None = None,
) -> BasicSearchProcessedStreamResults:
    tool_call_chunk = AIMessageChunk(content="")

    if final_search_results and displayed_search_results:
        answer_handler: AnswerResponseHandler = CitationResponseHandler(
            context_docs=final_search_results,
            final_doc_id_to_rank_map=map_document_id_order(final_search_results),
            display_doc_id_to_rank_map=map_document_id_order(displayed_search_results),
        )
    else:
        answer_handler = PassThroughAnswerResponseHandler()

    full_answer = ""
    start_final_answer_streaming_set = False
    # Accumulate citation infos if handler emits them
    collected_citation_infos: list[CitationInfo] = []

    # This stream will be the llm answer if no tool is chosen. When a tool is chosen,
    # the stream will contain AIMessageChunks with tool call information.
    for message in messages:

        answer_piece = message.content
        if not isinstance(answer_piece, str):
            # this is only used for logging, so fine to
            # just add the string representation
            answer_piece = str(answer_piece)
        full_answer += answer_piece

        if isinstance(message, AIMessageChunk) and (
            message.tool_call_chunks or message.tool_calls
        ):
            tool_call_chunk += message  # type: ignore
        elif should_stream_answer:
            for response_part in answer_handler.handle_response_part(message, []):

                # only stream out answer parts
                if (
                    isinstance(response_part, (OnyxAnswerPiece, AgentAnswerPiece))
                    and generate_final_answer
                    and response_part.answer_piece
                ):
                    if chat_message_id is None:
                        raise ValueError(
                            "chat_message_id is required when generating final answer"
                        )

                    if not start_final_answer_streaming_set:
                        # Convert LlmDocs to SavedSearchDocs
                        saved_search_docs = saved_search_docs_from_llm_docs(
                            final_search_results
                        )
                        write_custom_event(
                            ind,
                            MessageStart(content="", final_documents=saved_search_docs),
                            writer,
                        )
                        start_final_answer_streaming_set = True

                    write_custom_event(
                        ind,
                        MessageDelta(content=response_part.answer_piece),
                        writer,
                    )
                # collect citation info objects
                elif isinstance(response_part, CitationInfo):
                    collected_citation_infos.append(response_part)

    if generate_final_answer and start_final_answer_streaming_set:
        # start_final_answer_streaming_set is only set if the answer is verbal and not a tool call
        write_custom_event(
            ind,
            SectionEnd(),
            writer,
        )

        # Emit citations section if any were collected
        if collected_citation_infos:
            write_custom_event(ind, CitationStart(), writer)
            write_custom_event(
                ind, CitationDelta(citations=collected_citation_infos), writer
            )
            write_custom_event(ind, SectionEnd(), writer)

    logger.debug(f"Full answer: {full_answer}")
    return BasicSearchProcessedStreamResults(
        ai_message_chunk=cast(AIMessageChunk, tool_call_chunk), full_answer=full_answer
    )
