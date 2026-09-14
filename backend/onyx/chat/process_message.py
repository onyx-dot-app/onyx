"""Prepare chat requests and coordinate agent execution, persistence, and streaming."""

import queue
import re
import threading
import time
from collections.abc import Callable, Iterator
from concurrent.futures import Future, wait
from contextvars import Token
from enum import Enum
from functools import partial
from uuid import UUID

from onyx.chat.agent import ChatAgent
from onyx.chat.cancellation import clear_stop, is_stop_requested
from onyx.chat.chat_processing_checker import set_processing_status
from onyx.chat.chat_state import ChatResponseSnapshot, ChatStateContainer, ChatTurnSetup
from onyx.chat.compression import compress_chat_if_needed
from onyx.chat.emitter import Emitter, ModelStreamStatus
from onyx.chat.errors import chat_error
from onyx.chat.incognito_context import incognito_session_ended
from onyx.chat.models import (
    AnswerStream,
    ChatBasicResponse,
    ChatFullResponse,
    CreateChatSessionID,
    StreamingError,
    ToolCallResponse,
)
from onyx.chat.prepare import prepare_chat_turn
from onyx.chat.stream_buffer import StreamBufferWriter
from onyx.configs.app_configs import INTEGRATION_TESTS_MODE
from onyx.configs.chat_configs import CHAT_HEARTBEAT_INTERVAL_S, MAX_LLM_CYCLES
from onyx.configs.constants import DEFAULT_PERSONA_ID, DocumentSource
from onyx.context.search.models import BaseFilters, SearchDoc
from onyx.db.agent_transcript import save_chat_error
from onyx.db.chat_response import save_chat_response
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import record_mode_persists_content
from onyx.db.models import User
from onyx.deep_research.agent import run_deep_research
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError, log_onyx_error
from onyx.llm.cancellation import AgentCancelled, CancellationSignal, cancellation_scope
from onyx.llm.factory import get_llm_token_counter
from onyx.llm.override_models import LLMOverride
from onyx.llm.request_context import reset_llm_mock_response, set_llm_mock_response
from onyx.natural_language_processing.utils import get_tokenizer
from onyx.onyxbot.slack.models import SlackContext
from onyx.server.query_and_chat.models import MessageResponseIDInfo, SendMessageRequest
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import (
    AgentResponseDelta,
    AgentResponseStart,
    CitationInfo,
    OverallStop,
    Packet,
    heartbeat_packet,
)
from onyx.server.settings.store import load_settings
from onyx.server.utils import get_json_line
from onyx.tools.tool_constructor import (
    CustomToolConfig,
    FileReaderToolConfig,
    SearchToolConfig,
    construct_tools,
)
from onyx.tracing.framework.create import ChatTraceMetadata, trace
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import (
    ContextThreadPoolExecutor,
    start_thread_with_context,
)
from onyx.utils.timing import log_function_time
from shared_configs.contextvars import (
    CURRENT_CONTENT_FREE_SESSION_ID_CONTEXTVAR,
    CURRENT_INCOGNITO_RECORD_MODE_CONTEXTVAR,
)

logger = setup_logger()
ERROR_TYPE_CANCELLED = "cancelled"
APPROX_CHARS_PER_TOKEN = 4


class _ChatStreamStatus(str, Enum):
    DONE = "done"


_CANCEL_POLL_INTERVAL_S = 0.05
_FENCE_REFRESH_INTERVAL_S = 60.0


class _ChatStream(Iterator[Packet | StreamingError]):
    """A detachable reader; closing it does not cancel agent execution."""

    def __init__(self) -> None:
        self._queue: queue.Queue[Packet | StreamingError | _ChatStreamStatus] = (
            queue.Queue()
        )
        self._lock = threading.Lock()
        self._closed = False

    def publish(self, item: Packet | StreamingError | _ChatStreamStatus) -> None:
        with self._lock:
            if not self._closed:
                self._queue.put(item)

    def __next__(self) -> Packet | StreamingError:
        try:
            item = self._queue.get(timeout=CHAT_HEARTBEAT_INTERVAL_S)
        except queue.Empty:
            return heartbeat_packet()
        if item is _ChatStreamStatus.DONE:
            self.close()
            raise StopIteration
        return item

    def close(self) -> None:
        with self._lock:
            self._closed = True
            while True:
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    break
            self._queue.put(_ChatStreamStatus.DONE)


def _should_enable_slack_search(persona_id: int, filters: BaseFilters | None) -> bool:
    source_types = filters.source_type if filters else None
    return (source_types is not None and DocumentSource.SLACK in source_types) or (
        persona_id == DEFAULT_PERSONA_ID and source_types is None
    )


def _execute_model(
    setup: ChatTurnSetup,
    user: User,
    model_idx: int,
    state: ChatStateContainer,
    emitter: Emitter,
    cancellation: CancellationSignal,
    auto_detect_search_filters: bool,
) -> None:
    model_emitter = emitter
    sc = state
    model_llm = setup.models[model_idx].llm
    n_models = len(setup.models)
    with cancellation_scope(cancellation):
        cancellation.check()
        # Tools open DB sessions on demand, so model I/O cannot retain a connection.
        thread_tool_dict = construct_tools(
            persona=setup.persona_id,
            emitter=model_emitter,
            user=user,
            llm=model_llm,
            search_tool_config=SearchToolConfig(
                user_selected_filters=setup.new_msg_req.internal_search_filters,
                project_id_filter=setup.search_params.project_id_filter,
                persona_id_filter=setup.search_params.persona_id_filter,
                bypass_acl=setup.bypass_acl,
                slack_context=setup.slack_context,
                enable_slack_search=_should_enable_slack_search(
                    setup.persona_id, setup.new_msg_req.internal_search_filters
                ),
                auto_detect_filters=auto_detect_search_filters,
            ),
            custom_tool_config=CustomToolConfig(
                chat_session_id=setup.chat_session_id,
                message_id=setup.user_message_id,
                additional_headers=setup.custom_tool_additional_headers,
                mcp_headers=setup.mcp_headers,
            ),
            file_reader_tool_config=FileReaderToolConfig(
                user_file_ids=setup.available_files.user_file_ids,
                chat_file_ids=setup.available_files.chat_file_ids,
            ),
            allowed_tool_ids=setup.new_msg_req.allowed_tool_ids,
            search_usage_forcing_setting=setup.search_params.search_usage,
        )
        model_tools = [
            tool for tool_list in thread_tool_dict.values() for tool in tool_list
        ]

        if setup.forced_tool_id and setup.forced_tool_id not in {
            tool.id for tool in model_tools
        }:
            raise ValueError(f"Forced tool {setup.forced_tool_id} not found in tools")

        if n_models == 1 and setup.new_msg_req.deep_research:
            if setup.chat_session_project_id:
                raise RuntimeError("Deep research is not supported for projects")
            run_deep_research(
                emitter=model_emitter,
                state_container=sc,
                messages=list(setup.messages),
                tools=model_tools,
                custom_agent_prompt=setup.custom_agent_prompt,
                llm=model_llm,
                token_counter=get_llm_token_counter(model_llm),
                reasoning_effort=setup.reasoning_effort,
                skip_clarification=setup.skip_clarification,
                user_identity=setup.user_identity,
                chat_session_id=str(setup.chat_session_id),
                all_injected_file_metadata=setup.all_injected_file_metadata,
                user_language=setup.user_memory_context.user_info.language,
            )
        else:
            with trace(
                "chat",
                group_id=str(setup.chat_session_id),
                metadata=ChatTraceMetadata(
                    user_id=setup.user_identity.user_id
                ).model_dump(),
            ):
                ChatAgent(
                    emitter=model_emitter,
                    state_container=sc,
                    messages=list(setup.messages),
                    tools=model_tools,
                    custom_agent_prompt=setup.custom_agent_prompt,
                    context_files=setup.extracted_context_files,
                    persona=setup.persona,
                    user_memory_context=setup.user_memory_context,
                    llm=model_llm,
                    token_counter=get_llm_token_counter(model_llm),
                    forced_tool_id=setup.forced_tool_id,
                    user_identity=setup.user_identity,
                    chat_files=setup.chat_files_for_tools,
                    reasoning_effort=setup.reasoning_effort,
                    include_citations=setup.new_msg_req.include_citations,
                    all_injected_file_metadata=setup.all_injected_file_metadata,
                    inject_memories_in_prompt=user.use_memories,
                ).run(max_turns=MAX_LLM_CYCLES, cancellation=cancellation)


def _run_models(
    setup: ChatTurnSetup,
    user: User,
    external_state_container: ChatStateContainer | None = None,
    stream_buffer: StreamBufferWriter | None = None,
) -> _ChatStream:
    """Start agent tasks and return a reader independent of their lifetime."""
    queue_out: queue.Queue[tuple[int, Packet | ModelStreamStatus]] = queue.Queue()
    reader = _ChatStream()
    output_closed = threading.Event()
    cancellation = CancellationSignal()
    states = [
        external_state_container
        if index == 0 and external_state_container is not None
        else ChatStateContainer()
        for index in range(len(setup.models))
    ]
    executor: ContextThreadPoolExecutor | None = None
    futures: dict[int, Future[None]] = {}

    buffer_executor: ContextThreadPoolExecutor | None = None
    buffer_work: Future[None] | None = None
    saves: dict[int, Future[bool]] = {}

    def store_stream(callback: Callable[[], None]) -> Future[None]:
        nonlocal buffer_work
        if buffer_executor is None:
            raise RuntimeError("Stream storage executor has not started")

        def store() -> None:
            try:
                callback()
            except Exception:
                logger.exception("Failed to store chat stream")

        future = buffer_executor.submit(store)
        buffer_work = future
        return future

    def publish(item: Packet | StreamingError) -> None:
        if stream_buffer is not None:
            store_stream(
                partial(stream_buffer.append_line, get_json_line(item.model_dump()))
            )
        reader.publish(item)

    def start_save(index: int) -> None:
        """Choose one immutable outcome; storage workers never make completion decisions."""
        future = futures[index]
        error = future.exception() if future.done() else AgentCancelled()
        try:
            response = states[index].snapshot(
                cancelled=isinstance(error, AgentCancelled)
            )
            success = error is None or isinstance(error, AgentCancelled)
            if not success:
                failure = (
                    error
                    if isinstance(error, Exception)
                    else RuntimeError("Agent task failed")
                )
                error_packet = chat_error(failure, setup.models[index].llm, index)
                publish(error_packet)
                save = partial(
                    save_failed_chat_response, setup, index, response, error_packet
                )
            else:
                save = partial(
                    save_chat_response,
                    message_id=setup.models[index].message_id,
                    response=response,
                )

            def persist() -> bool:
                save()
                return success

            if executor is None:
                raise RuntimeError("Chat executor has not started")
            saves[index] = executor.submit(persist)
        except Exception as error:
            failed: Future[bool] = Future()
            failed.set_exception(error)
            saves[index] = failed

    def finish_save(index: int) -> bool:
        try:
            return saves.pop(index).result()
        except Exception:
            logger.exception("Failed to save response for model %d", index)
            publish(
                StreamingError(
                    error="The response could not be saved. Please try again.",
                    error_code="RESPONSE_SAVE_ERROR",
                    is_retryable=True,
                    details={"model_index": index},
                )
            )
            return False

    def coordinate(startup_error: Exception | None = None) -> None:
        nonlocal executor, buffer_executor
        if executor is None:
            executor = ContextThreadPoolExecutor(
                max_workers=len(states) + 1, thread_name_prefix="chat-agent"
            )
        if stream_buffer is not None:
            buffer_executor = ContextThreadPoolExecutor(
                max_workers=1, thread_name_prefix="chat-stream-storage"
            )
        pending = set(futures)
        compression_model: int | None = None
        last_refresh = last_stop_check = time.monotonic()
        stopped_by_user = False

        def poll_control() -> bool:
            nonlocal last_refresh, last_stop_check, stopped_by_user
            now = time.monotonic()
            if (
                not cancellation.cancelled
                and now - last_stop_check >= _CANCEL_POLL_INTERVAL_S
            ):
                last_stop_check = now
                if is_stop_requested(setup.chat_session_id, setup.cache):
                    stopped_by_user = True
                    cancellation.cancel()
                    output_closed.set()
            if now - last_refresh >= _FENCE_REFRESH_INTERVAL_S:
                last_refresh = now
                try:
                    set_processing_status(
                        chat_session_id=setup.chat_session_id,
                        cache=setup.cache,
                        value=True,
                        run_id=setup.processing_run_id,
                    )
                except Exception:
                    logger.exception("Failed to refresh chat processing status")
            return cancellation.cancelled

        try:
            if startup_error is not None:
                publish(
                    StreamingError(
                        error="The response could not be started. Please try again.",
                        error_code="CHAT_STARTUP_ERROR",
                        is_retryable=True,
                    )
                )
            while (pending or saves) and startup_error is None:
                if poll_control():
                    break
                for index, save in list(saves.items()):
                    if save.done() and finish_save(index) and compression_model is None:
                        compression_model = index
                if not pending and not saves:
                    break
                try:
                    index, event = queue_out.get(timeout=_CANCEL_POLL_INTERVAL_S)
                except queue.Empty:
                    if stream_buffer is not None and (
                        buffer_work is None or buffer_work.done()
                    ):
                        store_stream(stream_buffer.flush)
                    continue
                if event is ModelStreamStatus.DONE:
                    pending.remove(index)
                    start_save(index)
                elif isinstance(event, Packet):
                    publish(event)
        except Exception:
            cancellation.cancel()
            output_closed.set()
            logger.exception("Chat coordinator failed")
            publish(
                StreamingError(
                    error="The response stream ended unexpectedly. Please try again.",
                    error_code="STREAM_WRITER_ERROR",
                    is_retryable=True,
                )
            )
        finally:
            # Only this coordinator saves outcomes, including snapshots of cancelled tasks.
            for index in sorted(pending):
                start_save(index)
            while saves:
                poll_control()
                for index, save in list(saves.items()):
                    if save.done() and finish_save(index) and compression_model is None:
                        compression_model = index
                if saves:
                    wait(list(saves.values()), timeout=_CANCEL_POLL_INTERVAL_S)
            if (
                compression_model is not None
                and not cancellation.cancelled
                and record_mode_persists_content(setup.incognito_record_mode)
            ):

                def compress() -> None:
                    with cancellation_scope(cancellation):
                        cancellation.check()
                        compress_chat_if_needed(
                            setup.chat_session_id,
                            setup.models[compression_model].llm,
                            setup.reserved_token_count,
                            min(
                                model.llm.info.max_input_tokens
                                for model in setup.models
                            ),
                        )

                try:
                    compression = executor.submit(compress)
                    while not compression.done():
                        if poll_control():
                            break
                        if stream_buffer is not None and (
                            buffer_work is None or buffer_work.done()
                        ):
                            store_stream(stream_buffer.flush)
                        wait([compression], timeout=_CANCEL_POLL_INTERVAL_S)
                    if not cancellation.cancelled:
                        compression.result()
                except AgentCancelled:
                    cancellation.cancel()
                except Exception:
                    cancellation.cancel()
                    logger.exception("Chat compression failed")
            if stopped_by_user:
                publish(
                    Packet(
                        placement=Placement(turn_index=0),
                        obj=OverallStop(stop_reason="user_cancelled"),
                    )
                )
            try:
                if stream_buffer is not None:
                    final_write = store_stream(stream_buffer.mark_done)
                    while not final_write.done():
                        poll_control()
                        wait([final_write], timeout=_CANCEL_POLL_INTERVAL_S)
                    final_write.result()
            finally:
                try:
                    set_processing_status(
                        chat_session_id=setup.chat_session_id,
                        cache=setup.cache,
                        value=False,
                    )
                except Exception:
                    logger.exception("Failed to clear chat processing status")
                reader.publish(_ChatStreamStatus.DONE)
                if buffer_executor is not None:
                    buffer_executor.shutdown(wait=False)
                if executor is not None:
                    executor.shutdown(wait=False)

    def notify_done(index: int, _future: Future[None]) -> None:
        queue_out.put((index, ModelStreamStatus.DONE))

    try:
        auto_filters = load_settings().auto_detect_search_filters is not False
        clear_stop(setup.chat_session_id, setup.cache)
        set_processing_status(
            chat_session_id=setup.chat_session_id,
            cache=setup.cache,
            value=True,
            run_id=setup.processing_run_id,
        )
        executor = ContextThreadPoolExecutor(
            max_workers=len(states) + 1, thread_name_prefix="chat-agent"
        )
        for index, state in enumerate(states):
            emitter = Emitter(
                merged_queue=queue_out, model_idx=index, drain_done=output_closed
            )
            execute = partial(
                _execute_model,
                setup,
                user,
                index,
                state,
                emitter,
                cancellation,
                auto_filters,
            )
            future = executor.submit(execute)
            futures[index] = future
            future.add_done_callback(partial(notify_done, index))
        start_thread_with_context(coordinate, name="chat-coordinator")
    except Exception as error:
        cancellation.cancel()
        output_closed.set()
        for index in range(len(states)):
            if index not in futures:
                failed: Future[None] = Future()
                failed.set_exception(error)
                futures[index] = failed
        coordinate(startup_error=error)

    return reader


def save_failed_chat_response(
    setup: ChatTurnSetup,
    index: int,
    response: ChatResponseSnapshot,
    error: StreamingError,
) -> None:
    persist_content = record_mode_persists_content(setup.incognito_record_mode)
    text = (
        f"Error from {setup.models[index].display_name}: {error.error}"
        if persist_content
        else "The model encountered an error."
    )
    save_chat_error(
        message_id=setup.models[index].message_id,
        error=text,
        token_count=len(get_tokenizer(None, None).encode(response.answer_tokens or "")),
        transcript=response.transcript,
        persist_content=persist_content,
    )


def _stream_chat_turn(
    new_msg_req: SendMessageRequest,
    user: User,
    llm_overrides: list[LLMOverride] | None = None,
    litellm_additional_headers: dict[str, str] | None = None,
    custom_tool_additional_headers: dict[str, str] | None = None,
    mcp_headers: dict[str, str] | None = None,
    additional_context: str | None = None,
    slack_context: SlackContext | None = None,
    external_state_container: ChatStateContainer | None = None,
) -> AnswerStream:
    """Prepare one request, then read its independently owned agent stream."""
    if new_msg_req.mock_llm_response is not None and not INTEGRATION_TESTS_MODE:
        raise ValueError(
            "mock_llm_response can only be used when INTEGRATION_TESTS_MODE=true"
        )
    setup: ChatTurnSetup | None = None
    mock_token: Token[str | None] | None = None
    scope_started = False
    stream: _ChatStream | None = None
    try:
        with get_session_with_current_tenant() as session:
            setup = prepare_chat_turn(
                new_msg_req=new_msg_req,
                user=user,
                db_session=session,
                llm_overrides=llm_overrides,
                litellm_additional_headers=litellm_additional_headers,
                custom_tool_additional_headers=custom_tool_additional_headers,
                mcp_headers=mcp_headers,
                bypass_acl=bypass_acl,
                slack_context=slack_context,
                additional_context=additional_context,
            )
            session.expunge_all()
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
            run_id=setup.processing_run_id,
            delete_on_done=content_free,
            session_ended=(
                partial(incognito_session_ended, setup.chat_session_id)
                if content_free
                else None
            ),
        )
        for packet in setup.initial_packets:
            stream_buffer.append_line(get_json_line(packet.model_dump()))
        stream = _run_models(setup, user, external_state_container, stream_buffer)
        yield from setup.initial_packets
        yield from stream
    except Exception as error:
        if isinstance(error, OnyxError):
            if error.error_code is not OnyxErrorCode.QUERY_REJECTED:
                log_onyx_error(error)
        else:
            logger.exception("Chat request failed")
        yield chat_error(error, setup.models[0].llm if setup else None)
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
    external_state_container: ChatStateContainer | None = None,
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
        additional_context=additional_context,
        slack_context=slack_context,
        external_state_container=external_state_container,
    )


def handle_multi_model_stream(
    new_msg_req: SendMessageRequest,
    user: User,
    llm_overrides: list[LLMOverride],
    litellm_additional_headers: dict[str, str] | None = None,
    custom_tool_additional_headers: dict[str, str] | None = None,
    mcp_headers: dict[str, str] | None = None,
) -> AnswerStream:
    """Thin wrapper for side-by-side multi-model comparison (2–3 models).

    Validates the override list and delegates to ``_stream_chat_turn``,
    which handles both single-model and multi-model execution via the same path.

    Args:
        new_msg_req: The incoming chat request. ``deep_research`` must be ``False``.
        user: Authenticated user making the request.
        llm_overrides: Exactly 2 or 3 ``LLMOverride`` objects — one per model to run.
        litellm_additional_headers: Extra headers forwarded to each LLM provider.
        custom_tool_additional_headers: Extra headers for custom tool HTTP calls.
        mcp_headers: Extra headers for MCP tool calls.

    Returns:
        Generator yielding interleaved ``Packet`` objects from all models, each tagged
        with ``model_index`` in its placement.
    """
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
            if isinstance(packet.obj, AgentResponseStart):
                if packet.obj.final_documents:
                    top_documents = packet.obj.final_documents
            elif isinstance(packet.obj, AgentResponseDelta):
                if answer is None:
                    answer = ""
                if packet.obj.content:
                    answer += packet.obj.content
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
    state_container: ChatStateContainer,
) -> ChatFullResponse:
    """
    Aggregate streaming packets and state container into a complete ChatFullResponse.

    This function consumes all packets from the stream and combines them with
    the accumulated state from the ChatStateContainer to build a complete response
    including answer, reasoning, citations, and tool calls.

    Args:
        packets: The stream of packets from handle_stream_message_objects
        state_container: The state container that accumulates tool calls, reasoning, etc.

    Returns:
        ChatFullResponse with all available data
    """
    answer: str | None = None
    citations: list[CitationInfo] = []
    error_msg: str | None = None
    message_id: int | None = None
    top_documents: list[SearchDoc] = []
    chat_session_id: UUID | None = None
    incognito = False

    for packet in packets:
        if isinstance(packet, Packet):
            if isinstance(packet.obj, AgentResponseStart):
                if packet.obj.final_documents:
                    top_documents = packet.obj.final_documents
            elif isinstance(packet.obj, AgentResponseDelta):
                if answer is None:
                    answer = ""
                if packet.obj.content:
                    answer += packet.obj.content
            elif isinstance(packet.obj, CitationInfo):
                citations.append(packet.obj)
        elif isinstance(packet, StreamingError):
            error_msg = packet.error
        elif isinstance(packet, MessageResponseIDInfo):
            message_id = packet.reserved_assistant_message_id
        elif isinstance(packet, CreateChatSessionID):
            chat_session_id = packet.chat_session_id
            incognito = packet.incognito

    if message_id is None:
        raise ValueError("Message ID is required")

    final_answer = state_container.get_answer_tokens() or answer or ""

    reasoning = state_container.get_reasoning_tokens()

    tool_call_responses = [
        ToolCallResponse(
            tool_name=tc.tool_name,
            tool_arguments=tc.tool_call_arguments,
            tool_result=tc.tool_call_response,
            search_docs=tc.search_docs,
            generated_images=tc.generated_images,
            pre_reasoning=tc.reasoning_tokens,
        )
        for tc in state_container.get_tool_calls()
    ]

    return ChatFullResponse(
        answer=final_answer,
        answer_citationless=remove_answer_citations(final_answer),
        pre_answer_reasoning=reasoning,
        tool_calls=tool_call_responses,
        top_documents=top_documents,
        citation_info=citations,
        message_id=message_id,
        chat_session_id=chat_session_id,
        incognito=incognito,
        error_msg=error_msg,
    )
