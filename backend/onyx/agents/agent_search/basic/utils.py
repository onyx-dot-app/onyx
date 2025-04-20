from collections.abc import Iterator
from typing import cast

from langchain_core.messages import AIMessageChunk
from langchain_core.messages import BaseMessage
from langgraph.types import StreamWriter

from onyx.agents.agent_search.shared_graph_utils.utils import write_custom_event
from onyx.chat.models import LlmDoc
from onyx.chat.stream_processing.answer_response_handler import AnswerResponseHandler
from onyx.chat.stream_processing.answer_response_handler import CitationResponseHandler
from onyx.chat.stream_processing.answer_response_handler import (
    PassThroughAnswerResponseHandler,
)
from onyx.chat.stream_processing.utils import map_document_id_order
from onyx.utils.logger import setup_logger

logger = setup_logger()


def process_llm_stream(
    messages: Iterator[BaseMessage],
    should_stream_answer: bool,
    writer: StreamWriter,
    final_search_results: list[LlmDoc] | None = None,
    displayed_search_results: list[LlmDoc] | None = None,
) -> AIMessageChunk:
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
                write_custom_event(
                    "basic_response",
                    response_part,
                    writer,
                )

    logger.debug(f"Full answer: {full_answer}")
    return cast(AIMessageChunk, tool_call_chunk)
