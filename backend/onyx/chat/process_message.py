"""Prepare chat requests and return streamed or complete responses."""

import re
from concurrent.futures import Future
from contextvars import Token
from functools import partial
from uuid import UUID

from onyx.chat.errors import chat_error
from onyx.chat.execution import (
    ActiveChatTurns,
    start_chat_turn,
)
from onyx.chat.incognito_context import incognito_session_ended
from onyx.chat.models import (
    AnswerStream,
    ChatBasicResponse,
    ChatFullResponse,
    ChatResponseOutcome,
    ChatTurnSetup,
    CreateChatSessionID,
    StreamingError,
    ToolCallResponse,
)
from onyx.chat.prepare import prepare_chat_turn
from onyx.chat.stream_buffer import ChatStream, StreamBufferWriter
from onyx.configs.app_configs import INTEGRATION_TESTS_MODE
from onyx.configs.chat_configs import CHAT_RESPONSE_WAIT_TIMEOUT_S
from onyx.context.search.models import SearchDoc
from onyx.db.enums import record_mode_persists_content
from onyx.db.models import User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError, log_onyx_error
from onyx.llm.override_models import LLMOverride
from onyx.llm.request_context import reset_llm_mock_response, set_llm_mock_response
from onyx.onyxbot.slack.models import SlackContext
from onyx.server.query_and_chat.models import MessageResponseIDInfo, SendMessageRequest
from onyx.server.query_and_chat.streaming_models import (
    AgentResponseDelta,
    AgentResponseStart,
    CitationInfo,
    Packet,
)
from onyx.server.utils import get_json_line
from onyx.utils.logger import setup_logger
from onyx.utils.timing import log_function_time, log_generator_function_time
from shared_configs.contextvars import (
    CURRENT_CONTENT_FREE_SESSION_ID_CONTEXTVAR,
    CURRENT_INCOGNITO_RECORD_MODE_CONTEXTVAR,
)

logger = setup_logger()
ERROR_TYPE_CANCELLED = "cancelled"
APPROX_CHARS_PER_TOKEN = 4


def _stream_chat_turn(
    new_msg_req: SendMessageRequest,
    user: User,
    llm_overrides: list[LLMOverride] | None = None,
    litellm_additional_headers: dict[str, str] | None = None,
    custom_tool_additional_headers: dict[str, str] | None = None,
    mcp_headers: dict[str, str] | None = None,
    additional_context: str | None = None,
    slack_context: SlackContext | None = None,
    response_future: Future[ChatResponseOutcome] | None = None,
    active_chat_turns: ActiveChatTurns | None = None,
) -> AnswerStream:
    """Prepare one request, then read its independently owned agent stream."""
    if new_msg_req.mock_llm_response is not None and not INTEGRATION_TESTS_MODE:
        raise ValueError(
            "mock_llm_response can only be used when INTEGRATION_TESTS_MODE=true"
        )
    setup: ChatTurnSetup | None = None
    mock_token: Token[str | None] | None = None
    scope_started = False
    stream: ChatStream | None = None
    try:
        setup = prepare_chat_turn(
            new_msg_req=new_msg_req,
            user=user,
            llm_overrides=llm_overrides,
            litellm_additional_headers=litellm_additional_headers,
            custom_tool_additional_headers=custom_tool_additional_headers,
            mcp_headers=mcp_headers,
            slack_context=slack_context,
            additional_context=additional_context,
        )
        if new_msg_req.mock_llm_response is not None:
            mock_token = set_llm_mock_response(new_msg_req.mock_llm_response)
        mode = setup.incognito_record_mode
        content_free = not record_mode_persists_content(mode)
        CURRENT_INCOGNITO_RECORD_MODE_CONTEXTVAR.set(mode.value if mode else None)
        CURRENT_CONTENT_FREE_SESSION_ID_CONTEXTVAR.set(
            str(setup.chat_session_id) if content_free else None
        )
        scope_started = True
        stream_buffer = StreamBufferWriter(
            cache=setup.cache,
            chat_session_id=setup.chat_session_id,
            stream_id=setup.stream_id,
            delete_on_done=content_free,
            session_ended=(
                partial(incognito_session_ended, setup.chat_session_id)
                if content_free
                else None
            ),
        )
        for packet in setup.initial_packets:
            stream_buffer.append_line(get_json_line(packet.model_dump()))
        stream = start_chat_turn(
            setup,
            user,
            response_future,
            stream_buffer,
            active_chat_turns=active_chat_turns,
        )
        yield from setup.initial_packets
        yield from stream
    except Exception as error:
        if isinstance(error, OnyxError):
            if error.error_code is not OnyxErrorCode.QUERY_REJECTED:
                log_onyx_error(error)
        else:
            logger.exception("Chat request failed")
        yield chat_error(error, setup.responses[0].llm if setup else None)
    finally:
        if stream is not None:
            stream.close()
        if mock_token is not None:
            reset_llm_mock_response(mock_token)
        if scope_started:
            CURRENT_INCOGNITO_RECORD_MODE_CONTEXTVAR.set(None)
            CURRENT_CONTENT_FREE_SESSION_ID_CONTEXTVAR.set(None)


@log_generator_function_time()
def handle_stream_message_objects(
    new_msg_req: SendMessageRequest,
    user: User,
    litellm_additional_headers: dict[str, str] | None = None,
    custom_tool_additional_headers: dict[str, str] | None = None,
    mcp_headers: dict[str, str] | None = None,
    additional_context: str | None = None,
    slack_context: SlackContext | None = None,
    response_future: Future[ChatResponseOutcome] | None = None,
    active_chat_turns: ActiveChatTurns | None = None,
) -> AnswerStream:
    """Single-model streaming entrypoint. For multi-model comparison, use ``handle_multi_model_stream``.

    Emits a ``latency`` telemetry record for the whole turn once the stream is
    exhausted or closed. Callers must pass ``user`` as a keyword argument so the
    record carries the user id.
    """
    yield from _stream_chat_turn(
        new_msg_req=new_msg_req,
        user=user,
        llm_overrides=None,
        litellm_additional_headers=litellm_additional_headers,
        custom_tool_additional_headers=custom_tool_additional_headers,
        mcp_headers=mcp_headers,
        active_chat_turns=active_chat_turns,
        additional_context=additional_context,
        slack_context=slack_context,
        response_future=response_future,
    )


@log_generator_function_time()
def handle_multi_model_stream(
    new_msg_req: SendMessageRequest,
    user: User,
    llm_overrides: list[LLMOverride],
    litellm_additional_headers: dict[str, str] | None = None,
    custom_tool_additional_headers: dict[str, str] | None = None,
    mcp_headers: dict[str, str] | None = None,
    active_chat_turns: ActiveChatTurns | None = None,
) -> AnswerStream:
    """Stream independent responses from two or three selected models."""
    n_models = len(llm_overrides)
    if n_models < 2 or n_models > 3:
        yield StreamingError(
            error="Multi-model requires 2-3 overrides, got %d" % n_models,
            error_code="VALIDATION_ERROR",
            is_retryable=False,
        )
        return
    if new_msg_req.deep_research:
        yield StreamingError(
            error="Multi-model is not supported with deep research",
            error_code="VALIDATION_ERROR",
            is_retryable=False,
        )
        return
    yield from _stream_chat_turn(
        new_msg_req=new_msg_req,
        user=user,
        llm_overrides=llm_overrides,
        litellm_additional_headers=litellm_additional_headers,
        custom_tool_additional_headers=custom_tool_additional_headers,
        mcp_headers=mcp_headers,
        active_chat_turns=active_chat_turns,
    )


_CITATION_LINK_START_PATTERN = re.compile(r"\s*\[\[\d+\]\]\(")


def _find_markdown_link_end(text: str, destination_start: int) -> int | None:
    depth = 0
    i = destination_start

    while i < len(text):
        curr = text[i]
        if curr == "\\":
            i += 2
            continue

        if curr == "(":
            depth += 1
        elif curr == ")":
            if depth == 0:
                return i
            depth -= 1

        i += 1

    return None


def remove_answer_citations(answer: str) -> str:
    stripped_parts: list[str] = []
    cursor = 0

    while match := _CITATION_LINK_START_PATTERN.search(answer, cursor):
        stripped_parts.append(answer[cursor : match.start()])
        link_end = _find_markdown_link_end(answer, match.end())
        if link_end is None:
            stripped_parts.append(answer[match.start() :])
            return "".join(stripped_parts)

        cursor = link_end + 1

    stripped_parts.append(answer[cursor:])
    return "".join(stripped_parts)


@log_function_time()
def gather_stream(
    packets: AnswerStream,
) -> ChatBasicResponse:
    answer: str | None = None
    citations: list[CitationInfo] = []
    error_msg: str | None = None
    message_id: int | None = None
    top_documents: list[SearchDoc] = []

    for packet in packets:
        if isinstance(packet, Packet):
            if packet.placement.sub_turn_index is not None:
                continue
            if isinstance(packet.obj, AgentResponseStart):
                answer = ""
                citations = []
                top_documents = packet.obj.final_documents or []
            elif isinstance(packet.obj, AgentResponseDelta):
                answer = (answer or "") + packet.obj.content
            elif isinstance(packet.obj, CitationInfo):
                citations.append(packet.obj)
        elif isinstance(packet, StreamingError):
            error_msg = packet.error
        elif isinstance(packet, MessageResponseIDInfo):
            message_id = packet.reserved_assistant_message_id

    if message_id is None:
        raise ValueError("Message ID is required")

    if answer is None:
        if error_msg is not None:
            answer = ""
        else:
            # This should never be the case as these non-streamed flows do not have a stop-generation signal
            raise RuntimeError("Answer was not generated")

    return ChatBasicResponse(
        answer=answer,
        answer_citationless=remove_answer_citations(answer),
        citation_info=citations,
        message_id=message_id,
        error_msg=error_msg,
        top_documents=top_documents,
    )


@log_function_time()
def gather_stream_full(
    packets: AnswerStream,
    response_future: Future[ChatResponseOutcome],
) -> ChatFullResponse:
    """Read delivery metadata and project accepted execution content."""
    error_msg: str | None = None
    message_id: int | None = None
    chat_session_id: UUID | None = None
    incognito = False

    for packet in packets:
        if isinstance(packet, StreamingError):
            error_msg = packet.error
        elif isinstance(packet, MessageResponseIDInfo):
            message_id = packet.reserved_assistant_message_id
        elif isinstance(packet, CreateChatSessionID):
            chat_session_id = packet.chat_session_id
            incognito = packet.incognito

    if message_id is None:
        raise ValueError("Message ID is required")

    outcome = response_future.result(timeout=CHAT_RESPONSE_WAIT_TIMEOUT_S)
    snapshot = outcome.response
    final_answer = snapshot.answer or ""

    reasoning = snapshot.reasoning

    tool_call_responses = [
        ToolCallResponse(
            tool_name=tc.tool_name,
            tool_arguments=tc.tool_call_arguments,
            tool_result=tc.tool_call_response,
            search_docs=tc.search_docs,
            generated_images=tc.generated_images,
            pre_reasoning=tc.reasoning_tokens,
        )
        for tc in snapshot.tool_calls
    ]

    return ChatFullResponse(
        answer=final_answer,
        answer_citationless=remove_answer_citations(final_answer),
        pre_answer_reasoning=reasoning,
        tool_calls=tool_call_responses,
        top_documents=snapshot.top_documents,
        citation_info=snapshot.citation_info,
        message_id=message_id,
        chat_session_id=chat_session_id,
        incognito=incognito,
        error_msg=outcome.error or error_msg,
    )
