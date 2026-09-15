"""Prepare chat requests and coordinate agent execution, persistence, and streaming."""

import queue
import re
import threading
import time
from concurrent.futures import Future, wait
from contextvars import Token
from functools import partial
from uuid import UUID

from onyx.chat.agent import ChatAgent
from onyx.chat.cancellation import clear_stop, is_stop_requested
from onyx.chat.chat_processing_checker import set_processing_status
from onyx.chat.emitter import Emitter, ModelStreamStatus
from onyx.chat.errors import chat_error
from onyx.chat.incognito_context import incognito_session_ended
from onyx.chat.models import (
    PERSISTENCE_ERROR_MESSAGES,
    AnswerStream,
    ChatBasicResponse,
    ChatFullResponse,
    ChatResponseOutcome,
    ChatResponseSnapshot,
    ChatTurnSetup,
    CreateChatSessionID,
    PersistenceStatus,
    StreamingError,
    ToolCallResponse,
)
from onyx.chat.prepare import prepare_chat_turn
from onyx.chat.presentation import ResponseBinding, attach_response
from onyx.chat.prompt_utils import build_language_section
from onyx.chat.stream_buffer import ChatDelivery, ChatStream, StreamBufferWriter
from onyx.configs.app_configs import INTEGRATION_TESTS_MODE
from onyx.configs.chat_configs import MAX_LLM_CYCLES, SKIP_DEEP_RESEARCH_CLARIFICATION
from onyx.configs.constants import DEFAULT_PERSONA_ID, DocumentSource
from onyx.context.search.models import BaseFilters, SearchDoc
from onyx.db.chat_response import save_chat_response
from onyx.db.enums import record_mode_persists_content
from onyx.db.models import User
from onyx.deep_research.agent import MIN_RESEARCH_CONTEXT_TOKENS, DeepResearchAgent
from onyx.deep_research.tool_definitions import RESEARCH_AGENT_TOOL_NAME
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError, log_onyx_error
from onyx.llm.cancellation import AgentCancelled, CancellationSignal, cancellation_scope
from onyx.llm.factory import get_llm_token_counter
from onyx.llm.override_models import LLMOverride
from onyx.llm.request_context import reset_llm_mock_response, set_llm_mock_response
from onyx.onyxbot.slack.models import SlackContext
from onyx.server.query_and_chat.models import MessageResponseIDInfo, SendMessageRequest
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import (
    AgentResponseDelta,
    AgentResponseStart,
    CitationInfo,
    OverallStop,
    Packet,
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


_CANCEL_POLL_INTERVAL_S = 0.05
_FENCE_REFRESH_INTERVAL_S = 60.0
_MODEL_EVENT_QUEUE_CAPACITY = 1024
_PERSISTENCE_WAIT_SECONDS = 30.0


def _should_enable_slack_search(persona_id: int, filters: BaseFilters | None) -> bool:
    source_types = filters.source_type if filters else None
    return (source_types is not None and DocumentSource.SLACK in source_types) or (
        persona_id == DEFAULT_PERSONA_ID and source_types is None
    )


def _execute_model(
    setup: ChatTurnSetup,
    user: User,
    model_idx: int,
    state: ResponseBinding,
    emitter: Emitter,
    cancellation: CancellationSignal,
    auto_detect_search_filters: bool,
) -> None:
    model_llm = setup.responses[model_idx].llm
    n_models = len(setup.responses)
    with cancellation_scope(cancellation):
        cancellation.check()
        # Tools open DB sessions on demand, so model I/O cannot retain a connection.
        thread_tool_dict = construct_tools(
            configuration=setup.tool_configuration,
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

        research = n_models == 1 and setup.new_msg_req.deep_research
        with trace(
            "run_deep_research" if research else "chat",
            group_id=str(setup.chat_session_id),
            metadata=ChatTraceMetadata(
                chat_session_id=str(setup.chat_session_id),
                user_id=setup.user_identity.user_id,
            ).model_dump(),
        ):
            feature: ChatAgent | DeepResearchAgent
            if research:
                if setup.chat_session_project_id:
                    raise RuntimeError("Deep research is not supported for projects")
                if setup.research_tool_id is None:
                    raise ValueError("Deep research tool configuration is missing")
                if model_llm.info.max_input_tokens < MIN_RESEARCH_CONTEXT_TOKENS:
                    raise ValueError(
                        "Deep research requires a model with at least 50,000 input tokens"
                    )
                feature = DeepResearchAgent(
                    messages=list(setup.messages),
                    allowed_tools=model_tools,
                    llm=model_llm,
                    token_counter=get_llm_token_counter(model_llm),
                    user_identity=setup.user_identity,
                    language_section=build_language_section(
                        setup.user_memory_context.user_info.language
                    ),
                    reasoning_effort=setup.reasoning_effort,
                    all_injected_file_metadata=setup.all_injected_file_metadata,
                    skip_clarification=SKIP_DEEP_RESEARCH_CLARIFICATION
                    or setup.skip_clarification,
                    checkpoint=setup.checkpoint,
                )
                max_steps = feature.max_steps
                tool_ids = {tool.name: tool.id for tool in feature.tools}
                tool_ids[RESEARCH_AGENT_TOOL_NAME] = setup.research_tool_id
                initial_citations = {}
            else:
                feature = ChatAgent(
                    messages=list(setup.messages),
                    tools=model_tools,
                    custom_agent_prompt=setup.custom_agent_prompt,
                    context_files=setup.extracted_context_files,
                    persona=setup.persona,
                    base_system_prompt=setup.base_system_prompt,
                    checkpoint=setup.checkpoint,
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
                )
                max_steps = MAX_LLM_CYCLES
                tool_ids = {tool.name: tool.id for tool in model_tools}
                initial_citations = feature.artifacts.initial_citations
            attach_response(
                feature.agent,
                state,
                emitter,
                response_id=setup.responses[model_idx].message_id,
                tool_ids=tool_ids,
                initial_citations=initial_citations,
            )
            feature.agent.run(
                max_steps=max_steps,
                cancellation=cancellation,
                messages=setup.input_messages,
            )


def _log_late_save(future: Future[None]) -> None:
    try:
        future.result()
    except Exception:
        logger.exception("Response save failed after its wait bound")
    else:
        logger.debug("Response save completed after its wait bound")


class _ResponseTask:
    def __init__(self, index: int, state: ResponseBinding) -> None:
        self.index = index
        self.state = state
        self.execution: Future[None] | None = None
        self.persistence: Future[None] | None = None
        self.response: ChatResponseSnapshot | None = None
        self.persistence_deadline = 0.0
        self.is_finalized = False


class ChatCoordinator:
    """Own the executions, Stop control, and terminal saves for one chat turn."""

    def __init__(
        self,
        setup: ChatTurnSetup,
        user: User,
        response_binding: ResponseBinding | None = None,
        stream_buffer: StreamBufferWriter | None = None,
    ) -> None:
        self.setup = setup
        self.user = user
        self.delivery = ChatDelivery(stream_buffer)
        self._events: queue.Queue[tuple[int, Packet | ModelStreamStatus]] = queue.Queue(
            _MODEL_EVENT_QUEUE_CAPACITY
        )
        self._output_closed = threading.Event()
        self._cancellation = CancellationSignal()
        self._tasks = [
            _ResponseTask(
                index,
                response_binding
                if index == 0 and response_binding is not None
                else ResponseBinding(),
            )
            for index in range(len(setup.responses))
        ]
        self._executor: ContextThreadPoolExecutor | None = None
        self._stopped_by_user = False
        self._last_refresh = self._last_stop_check = time.monotonic()

    def start(self) -> ChatStream:
        self.delivery.start()
        try:
            self._executor = ContextThreadPoolExecutor(
                max_workers=len(self._tasks) + 1, thread_name_prefix="chat-agent"
            )
            auto_filters = load_settings().auto_detect_search_filters is not False
            clear_stop(
                self.setup.chat_session_id,
                self.setup.cache,
                processing_key=self.setup.processing_key,
            )
            set_processing_status(
                chat_session_id=self.setup.chat_session_id,
                cache=self.setup.cache,
                value=True,
                processing_key=self.setup.processing_key,
            )
            for task in self._tasks:
                emitter = Emitter(
                    merged_queue=self._events,
                    model_idx=task.index,
                    response_id=self.setup.responses[task.index].message_id,
                    drain_done=self._output_closed,
                )
                task.execution = self._executor.submit(
                    lambda task=task, emitter=emitter: _execute_model(
                        self.setup,
                        self.user,
                        task.index,
                        task.state,
                        emitter,
                        self._cancellation,
                        auto_filters,
                    )
                )
                task.execution.add_done_callback(partial(self._notify_done, task.index))
            start_thread_with_context(self._coordinate, name="chat-coordinator")
        except Exception as error:
            self._cancellation.cancel()
            self._output_closed.set()
            for task in self._tasks:
                if task.execution is None:
                    failed: Future[None] = Future()
                    failed.set_exception(error)
                    task.execution = failed
            self._coordinate(startup_error=error)
        return self.delivery.reader

    def _notify_done(self, index: int, _future: Future[None]) -> None:
        try:
            self._events.put_nowait((index, ModelStreamStatus.DONE))
        except queue.Full:
            logger.debug(
                "Chat coordinator will observe the completed response directly"
            )

    def _start_save(self, task: _ResponseTask) -> None:
        if task.is_finalized or task.persistence is not None:
            return
        try:
            execution = task.execution
            if execution is None:
                raise RuntimeError("Response execution was not initialized")
            error = execution.exception() if execution.done() else AgentCancelled()
            response_error: str | None = None
            if error is not None and not isinstance(error, AgentCancelled):
                failure = (
                    error
                    if isinstance(error, Exception)
                    else RuntimeError("Agent task failed")
                )
                packet = chat_error(
                    failure, self.setup.responses[task.index].llm, task.index
                )
                self.delivery.publish(packet)
                response_error = packet.error
            response = task.state.snapshot(
                cancelled=isinstance(error, AgentCancelled)
            ).model_copy(update={"error": response_error})
            task.response = response
            if response.delivery_failed:
                self.delivery.report_gap()
            executor = self._executor
            if executor is None:
                raise RuntimeError("Chat persistence executor was not initialized")
            task.persistence_deadline = time.monotonic() + _PERSISTENCE_WAIT_SECONDS
            task.persistence = executor.submit(
                lambda: save_chat_response(
                    message_id=self.setup.responses[task.index].message_id,
                    response=response,
                )
            )
        except Exception as error:
            failed: Future[None] = Future()
            failed.set_exception(error)
            task.persistence = failed

    def _finish_saves(self) -> None:
        for task in self._tasks:
            persistence = task.persistence
            if task.is_finalized or persistence is None:
                continue
            status = PersistenceStatus.SAVED
            if persistence.done():
                try:
                    persistence.result()
                except Exception as error:
                    logger.exception("Failed to save response for model %d", task.index)
                    status = PersistenceStatus.FAILED
                    if task.response is None:
                        task.state.fail(error)
            elif time.monotonic() >= task.persistence_deadline:
                logger.error(
                    "Response persistence exceeded its wait bound for model %d",
                    task.index,
                )
                status = PersistenceStatus.UNCONFIRMED
                persistence.add_done_callback(_log_late_save)
            else:
                continue
            if task.response is not None:
                task.state.finish(
                    ChatResponseOutcome(
                        response=task.response, persistence_status=status
                    )
                )
            if message := PERSISTENCE_ERROR_MESSAGES.get(status):
                self.delivery.publish(
                    StreamingError(
                        error=message,
                        error_code="RESPONSE_SAVE_ERROR",
                        is_retryable=True,
                        details={"model_index": task.index},
                    )
                )
            task.persistence = None
            task.is_finalized = True

    def _poll_control(self) -> bool:
        now = time.monotonic()
        if self._output_closed.is_set() and not self._cancellation.cancelled:
            self.delivery.report_gap()
        if (
            not self._cancellation.cancelled
            and now - self._last_stop_check >= _CANCEL_POLL_INTERVAL_S
        ):
            self._last_stop_check = now
            if is_stop_requested(
                self.setup.chat_session_id,
                self.setup.cache,
                processing_key=self.setup.processing_key,
            ):
                self._stopped_by_user = True
                self._cancellation.cancel()
                self._output_closed.set()
        if now - self._last_refresh >= _FENCE_REFRESH_INTERVAL_S:
            self._last_refresh = now
            try:
                set_processing_status(
                    chat_session_id=self.setup.chat_session_id,
                    cache=self.setup.cache,
                    value=True,
                    processing_key=self.setup.processing_key,
                )
            except Exception:
                logger.exception("Failed to refresh chat processing status")
        return self._cancellation.cancelled

    def _coordinate(self, startup_error: Exception | None = None) -> None:
        try:
            if startup_error is not None:
                self.delivery.publish(
                    StreamingError(
                        error="The response could not be started. Please try again.",
                        error_code="CHAT_STARTUP_ERROR",
                        is_retryable=True,
                    )
                )
                return
            while not all(task.is_finalized for task in self._tasks):
                if self._poll_control():
                    break
                self._finish_saves()
                try:
                    index, event = self._events.get(timeout=_CANCEL_POLL_INTERVAL_S)
                except queue.Empty:
                    for task in self._tasks:
                        if task.execution is not None and task.execution.done():
                            self._start_save(task)
                    continue
                if event is ModelStreamStatus.DONE:
                    self._start_save(self._tasks[index])
                else:
                    self.delivery.publish(event)
        except Exception:
            self._cancellation.cancel()
            self._output_closed.set()
            logger.exception("Chat coordinator failed")
            self.delivery.publish(
                StreamingError(
                    error="The response stream ended unexpectedly. Please try again.",
                    error_code="STREAM_WRITER_ERROR",
                    is_retryable=True,
                )
            )
        finally:
            self._finalize()

    def _finalize(self) -> None:
        try:
            if self._executor is None:
                self._executor = ContextThreadPoolExecutor(
                    max_workers=1, thread_name_prefix="chat-save"
                )
            for task in self._tasks:
                self._start_save(task)
            while not all(task.is_finalized for task in self._tasks):
                self._finish_saves()
                pending = [
                    task.persistence
                    for task in self._tasks
                    if task.persistence is not None
                ]
                if not pending:
                    break
                self._poll_control()
                wait(pending, timeout=_CANCEL_POLL_INTERVAL_S)
            if self._stopped_by_user:
                self.delivery.publish(
                    Packet(
                        placement=Placement(turn_index=0),
                        obj=OverallStop(stop_reason="user_cancelled"),
                    )
                )
        finally:
            self._output_closed.set()
            try:
                self.delivery.finish()
            finally:
                try:
                    set_processing_status(
                        chat_session_id=self.setup.chat_session_id,
                        cache=self.setup.cache,
                        value=False,
                    )
                except Exception:
                    logger.exception("Failed to clear chat processing status")
                if self._executor is not None:
                    self._executor.shutdown(wait=False)


def _stream_chat_turn(
    new_msg_req: SendMessageRequest,
    user: User,
    llm_overrides: list[LLMOverride] | None = None,
    litellm_additional_headers: dict[str, str] | None = None,
    custom_tool_additional_headers: dict[str, str] | None = None,
    mcp_headers: dict[str, str] | None = None,
    additional_context: str | None = None,
    slack_context: SlackContext | None = None,
    response_binding: ResponseBinding | None = None,
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
            bypass_acl=bypass_acl,
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
            processing_key=setup.processing_key,
            delete_on_done=content_free,
            session_ended=(
                partial(incognito_session_ended, setup.chat_session_id)
                if content_free
                else None
            ),
        )
        for packet in setup.initial_packets:
            stream_buffer.append_line(get_json_line(packet.model_dump()))
        stream = ChatCoordinator(setup, user, response_binding, stream_buffer).start()
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
    response_binding: ResponseBinding | None = None,
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
        response_binding=response_binding,
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
    response_binding: ResponseBinding,
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

    outcome = response_binding.result()
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
