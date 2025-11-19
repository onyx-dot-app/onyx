"""
Legacy v0 API endpoints for chat functionality.
Provides backwards compatibility with older response formats.
"""

import json
from collections.abc import Callable
from collections.abc import Generator
from typing import Any

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Request
from fastapi.responses import StreamingResponse

from onyx.auth.users import current_chat_accessible_user
from onyx.chat.chat_utils import extract_headers
from onyx.chat.models import LLMRelevanceFilterResponse
from onyx.chat.models import MessageResponseIDInfo
from onyx.chat.models import QADocsResponse
from onyx.chat.models import StreamingError
from onyx.chat.models import StreamStopInfo
from onyx.chat.process_message import stream_chat_message_objects
from onyx.configs.model_configs import LITELLM_PASS_THROUGH_HEADERS
from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.models import User
from onyx.server.query_and_chat.chat_backend import is_connected
from onyx.server.query_and_chat.models import CreateChatMessageRequest
from onyx.server.query_and_chat.streaming_models import CitationDelta
from onyx.server.query_and_chat.streaming_models import CitationStart
from onyx.server.query_and_chat.streaming_models import CustomToolDelta
from onyx.server.query_and_chat.streaming_models import CustomToolStart
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
from onyx.server.query_and_chat.token_limit import check_token_rate_limits
from onyx.utils.headers import get_custom_tool_additional_request_headers
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()

router = APIRouter(prefix="/v0/chat")


def transform_packet_to_v0_format(packet: Any) -> dict[str, Any] | None:
    """
    Transform modern packet format to v0 API format.
    Returns None if the packet should not be included in v0 output.
    """
    # Handle MessageResponseIDInfo
    if isinstance(packet, MessageResponseIDInfo):
        return {
            "user_message_id": packet.user_message_id,
            "reserved_assistant_message_id": packet.reserved_assistant_message_id,
        }

    # Handle QADocsResponse
    if isinstance(packet, QADocsResponse):
        response = {
            "level": packet.level,
            "level_question_num": packet.level_question_num,
            "top_documents": [doc.model_dump() for doc in packet.top_documents],
            "rephrased_query": packet.rephrased_query,
            "predicted_flow": packet.predicted_flow,
            "predicted_search": packet.predicted_search,
            "applied_source_filters": packet.applied_source_filters,
            "applied_time_cutoff": (
                packet.applied_time_cutoff.isoformat()
                if packet.applied_time_cutoff
                else None
            ),
            "recency_bias_multiplier": packet.recency_bias_multiplier,
        }
        return response

    # Handle LLM Relevance Filter Response
    if isinstance(packet, LLMRelevanceFilterResponse):
        return {"llm_selected_doc_indices": packet.llm_selected_doc_indices}

    # Handle StreamingError
    if isinstance(packet, StreamingError):
        return {
            "error": packet.error,
            "stack_trace": packet.stack_trace,
        }

    # Handle StreamStopInfo
    if isinstance(packet, StreamStopInfo):
        # This appears at the end - we might want to include message_id and other final info
        return {
            "agentic_message_ids": [],  # This would be populated with actual data if available
        }

    # Handle Packet objects containing various sub-objects
    if isinstance(packet, Packet):
        obj = packet.obj

        # Handle MessageStart
        if isinstance(obj, MessageStart):
            # First message piece
            result = {}
            if obj.content:
                result["answer_piece"] = obj.content
            if obj.final_documents:
                # Return final context docs separately
                return {
                    "final_context_docs": [
                        doc.model_dump() for doc in obj.final_documents
                    ]
                }
            return result if result else None

        # Handle MessageDelta
        if isinstance(obj, MessageDelta):
            return {"answer_piece": obj.content}

        # Handle SearchToolStart
        if isinstance(obj, SearchToolStart):
            # We'll capture the tool info in the delta
            return None

        # Handle SearchToolDelta
        if isinstance(obj, SearchToolDelta):
            tool_response = {
                "tool_name": "run_search",
                "tool_args": {},
            }

            # Add query if present
            if obj.queries:
                query = obj.queries[0]
                tool_response["tool_args"] = {"query": query}

            # If documents are returned, we need to format them
            if obj.documents:
                # Return the tool call first
                return tool_response

            return tool_response

        # Handle CustomToolStart
        if isinstance(obj, CustomToolStart):
            return {
                "tool_name": obj.tool_name,
                "tool_args": {},
            }

        # Handle CustomToolDelta
        if isinstance(obj, CustomToolDelta):
            tool_delta_result: dict[str, Any] = {
                "tool_name": obj.tool_name,
            }
            if obj.data:
                tool_delta_result["tool_result"] = obj.data
            if obj.file_ids:
                tool_delta_result["tool_file_ids"] = obj.file_ids
            return tool_delta_result

        # Handle ImageGenerationToolStart
        if isinstance(obj, ImageGenerationToolStart):
            return {
                "tool_name": "generate_image",
                "tool_args": {},
            }

        # Handle ImageGenerationToolDelta
        if isinstance(obj, ImageGenerationToolDelta):
            return {
                "tool_name": "generate_image",
                "tool_result": [img.model_dump() for img in obj.images],
            }

        # Handle CitationStart
        if isinstance(obj, CitationStart):
            return None

        # Handle CitationDelta
        if isinstance(obj, CitationDelta):
            if obj.citations:
                citations_data = []
                for citation in obj.citations:
                    citations_data.append(
                        {
                            "level": citation.level,
                            "level_question_num": citation.level_question_num,
                            "citation_num": citation.citation_num,
                            "document_id": citation.document_id,
                        }
                    )
                return {"citations": citations_data}
            return None

        # Handle ReasoningStart
        if isinstance(obj, ReasoningStart):
            return None

        # Handle ReasoningDelta
        if isinstance(obj, ReasoningDelta):
            return {"reasoning_piece": obj.reasoning}

        # Handle OverallStop
        if isinstance(obj, OverallStop):
            # This signals the end of streaming
            return None

        # Handle SectionEnd
        if isinstance(obj, SectionEnd):
            return None

    # Unknown packet type - log and skip
    logger.debug(f"Unknown packet type in v0 transformation: {type(packet)}")
    return None


@router.post("/send-message")
def handle_new_chat_message_v0(
    chat_message_req: CreateChatMessageRequest,
    request: Request,
    user: User | None = Depends(current_chat_accessible_user),
    _rate_limit_check: None = Depends(check_token_rate_limits),
    is_connected_func: Callable[[], bool] = Depends(is_connected),
) -> StreamingResponse:
    """
    TODO: deprecate this shortly.

    V0 API endpoint for sending chat messages.
    Returns responses in the legacy format for backwards compatibility.

    The response format is newline-delimited JSON objects:
    - {"user_message_id": int, "reserved_assistant_message_id": int}
    - {"answer_piece": str}
    - {"tool_name": str, "tool_args": dict}
    - {"level": int, "level_question_num": int, "top_documents": list}
    - {"llm_selected_doc_indices": list}
    - {"final_context_docs": list}
    - {"citations": list}
    - etc.
    """
    tenant_id = get_current_tenant_id()
    logger.debug(f"V0 API - Received new chat message: {chat_message_req.message}")

    if not chat_message_req.message and not chat_message_req.use_existing_user_message:
        raise HTTPException(status_code=400, detail="Empty chat message is invalid")

    def stream_generator() -> Generator[str, None, None]:
        """Generate v0 format responses from the modern streaming objects."""
        try:
            # Track state for aggregating certain responses
            final_message_info = {}
            all_citations = []
            pending_tool_call = None

            with get_session_with_tenant(tenant_id=tenant_id) as db_session:
                # Get the stream of objects from the modern chat processor
                objects = stream_chat_message_objects(
                    new_msg_req=chat_message_req,
                    user=user,
                    db_session=db_session,
                    litellm_additional_headers=extract_headers(
                        request.headers, LITELLM_PASS_THROUGH_HEADERS
                    ),
                    custom_tool_additional_headers=get_custom_tool_additional_request_headers(
                        request.headers
                    ),
                    is_connected=is_connected_func,
                )

                # Transform and yield each packet
                for obj in objects:
                    v0_response = transform_packet_to_v0_format(obj)

                    if v0_response is not None:
                        # Special handling for certain response types
                        if "citations" in v0_response:
                            # Aggregate citations
                            all_citations.extend(v0_response["citations"])
                        elif "user_message_id" in v0_response:
                            # Store message info for potential later use
                            final_message_info.update(v0_response)
                            yield json.dumps(v0_response) + "\n"
                        elif "tool_name" in v0_response:
                            # Store tool call to emit later with result
                            pending_tool_call = v0_response
                            # Emit tool call immediately
                            yield json.dumps(v0_response) + "\n"
                        elif "top_documents" in v0_response:
                            # This is a QADocsResponse - emit it
                            yield json.dumps(v0_response) + "\n"

                            # If there was a pending search tool, emit the combined result
                            if (
                                pending_tool_call
                                and pending_tool_call.get("tool_name") == "run_search"
                            ):
                                # Emit tool result with documents
                                tool_result_response = {
                                    "tool_name": "run_search",
                                    "tool_args": pending_tool_call.get("tool_args", {}),
                                    "tool_result": v0_response.get("top_documents", []),
                                    "level": v0_response.get("level"),
                                    "level_question_num": v0_response.get(
                                        "level_question_num"
                                    ),
                                }
                                yield json.dumps(tool_result_response) + "\n"
                                pending_tool_call = None
                        else:
                            # Yield the transformed response
                            yield json.dumps(v0_response) + "\n"

                # At the end, yield aggregated citations if any
                if all_citations:
                    yield json.dumps({"citations": all_citations}) + "\n"

                # Always yield a final message with aggregated info
                final_response: dict[str, Any] = {
                    "message_id": final_message_info.get(
                        "reserved_assistant_message_id"
                    ),
                    "agentic_message_ids": [],  # Would be populated if using agents
                }

                # Only yield non-empty final response
                if final_response.get("message_id"):
                    yield json.dumps(final_response) + "\n"

        except Exception as e:
            logger.exception("Error in v0 chat message streaming")
            error_response = {
                "error": str(e),
                "stack_trace": None,
            }
            yield json.dumps(error_response) + "\n"

    return StreamingResponse(
        stream_generator(),
        media_type="application/x-ndjson",  # Newline-delimited JSON
    )
