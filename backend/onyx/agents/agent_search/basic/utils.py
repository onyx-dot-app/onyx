from collections.abc import Iterator
from typing import cast

from langchain_core.callbacks.manager import dispatch_custom_event
from langchain_core.messages import AIMessageChunk
from langchain_core.messages import BaseMessage

from onyx.chat.models import LlmDoc
from onyx.chat.models import OnyxAnswerPiece
from onyx.utils.logger import setup_logger

logger = setup_logger()

# TODO: handle citations here; below is what was previously passed in
# see basic_use_tool_response.py for where these variables come from
# answer_handler = CitationResponseHandler(
#     context_docs=final_search_results,
#     final_doc_id_to_rank_map=map_document_id_order(final_search_results),
#     display_doc_id_to_rank_map=map_document_id_order(displayed_search_results),
# )


def process_llm_stream(
    stream: Iterator[BaseMessage],
    should_stream_answer: bool,
    final_search_results: list[LlmDoc] | None = None,
    displayed_search_results: list[LlmDoc] | None = None,
) -> AIMessageChunk:
    tool_call_chunk = AIMessageChunk(content="")
    # for response in response_handler_manager.handle_llm_response(stream):

    # This stream will be the llm answer if no tool is chosen. When a tool is chosen,
    # the stream will contain AIMessageChunks with tool call information.
    for response in stream:
        answer_piece = response.content
        if not isinstance(answer_piece, str):
            # TODO: handle non-string content
            logger.warning(f"Received non-string content: {type(answer_piece)}")
            answer_piece = str(answer_piece)

        if isinstance(response, AIMessageChunk) and (
            response.tool_call_chunks or response.tool_calls
        ):
            tool_call_chunk += response  # type: ignore
        elif should_stream_answer:
            # TODO: handle emitting of CitationInfo
            dispatch_custom_event(
                "basic_response",
                OnyxAnswerPiece(answer_piece=answer_piece),
            )

    return cast(AIMessageChunk, tool_call_chunk)
