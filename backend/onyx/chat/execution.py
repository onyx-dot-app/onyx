"""Run chat turns independently of browser connections."""

import threading
import time
from collections.abc import Callable
from concurrent.futures import Future
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from functools import partial

from onyx.agents.agent_coordination import AgentCoordinator, RunStore
from onyx.agents.concurrency import WorkTracker
from onyx.agents.models import (
    AgentInfo,
    AgentState,
    RunFailure,
    RunFailureKind,
    RunState,
    RunStatus,
)
from onyx.agents.runtime import Run
from onyx.cache.factory import get_cache_backend
from onyx.cache.interface import CacheLockLostError
from onyx.chat.agent import ChatAgent, build_chat_agent, chat_subagent_factory
from onyx.chat.chat_processing_checker import PROCESSING_REFRESH_INTERVAL_S
from onyx.chat.emitter import Emitter
from onyx.chat.errors import chat_error
from onyx.chat.history_store import get_chat_history_store
from onyx.chat.incognito import incognito_llm_request_policy
from onyx.chat.incognito_context import incognito_session_ended
from onyx.chat.models import ChatResponseOutcome, ChatTurnSetup, CreateChatSessionID
from onyx.chat.persistence import ChatResponsePersistence
from onyx.chat.presentation import ResponsePresenter, overall_stop
from onyx.chat.prompt_utils import build_language_section
from onyx.chat.restoration import restore_chat_agent, restore_subagent
from onyx.chat.run_store import ChatRunStore
from onyx.chat.stop_signal_checker import clear_stop, is_stop_requested
from onyx.chat.stream_buffer import ChatDelivery, ChatStream, StreamBufferWriter
from onyx.configs.chat_configs import (
    CHAT_EXECUTION_TIMEOUT_S,
    SKIP_DEEP_RESEARCH_CLARIFICATION,
)
from onyx.configs.constants import DEFAULT_PERSONA_ID, DocumentSource
from onyx.db.chat_inputs import pause_chat_queue__no_commit
from onyx.db.chat_subagents import load_chat_branch
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import record_mode_persists_content
from onyx.db.models import User
from onyx.deep_research.agent import DeepResearchAgent
from onyx.deep_research.tool_definitions import RESEARCH_AGENT_TOOL_NAME
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.models import ExtractedContextFiles
from onyx.llm.cancellation import CancellationSignal, cancellation_scope
from onyx.llm.factory import get_llm_token_counter, get_search_selection_llm
from onyx.llm.interfaces import LLM
from onyx.server.query_and_chat.models import (
    MessageResponseIDInfo,
    ModelResponseSlot,
    MultiModelMessageResponseIDInfo,
)
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import (
    OverallStop,
    Packet,
    StreamingError,
)
from onyx.server.settings.store import load_settings
from onyx.tools.constants import CODING_AGENT_TOOL_ID
from onyx.tools.interface import Tool
from onyx.tools.tool_constructor import (
    CustomToolConfig,
    FileReaderToolConfig,
    SearchToolConfig,
    construct_tools,
)
from onyx.tracing.framework.create import ChatTraceMetadata, trace
from onyx.utils.fleet_query_telemetry import CURRENT_QUERY_OBSERVATION, QueryObservation
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import start_thread_future
from shared_configs.contextvars import (
    CURRENT_CONTENT_FREE_SESSION_ID_CONTEXTVAR,
    CURRENT_INCOGNITO_RECORD_MODE_CONTEXTVAR,
    get_current_tenant_id,
)

logger = setup_logger()
_CANCEL_POLL_INTERVAL_S = 0.25
# Each response run ends itself at the turn deadline. The turn cancels later only
# when work outlives that, e.g. preparation that never started a run.
_DEADLINE_BACKSTOP = timedelta(seconds=30)
# Count work across tenants without retaining their turns or request data.
chat_turn_work = WorkTracker()


def start_chat_turn(
    setup: ChatTurnSetup,
    user: User,
    response_future: Future[ChatResponseOutcome] | None = None,
    *,
    query_observation: QueryObservation | None = None,
    dispatch_pending_messages: Callable[[], None] | None = None,
) -> ChatStream:
    """Publish response identity and launch work that outlives its stream reader."""
    mode = setup.incognito_record_mode
    content_free = not record_mode_persists_content(mode)
    mode_token = CURRENT_INCOGNITO_RECORD_MODE_CONTEXTVAR.set(
        mode.value if mode else None
    )
    session_token = CURRENT_CONTENT_FREE_SESSION_ID_CONTEXTVAR.set(
        str(setup.chat_session_id) if content_free else None
    )
    turn: ChatTurnExecution | None = None
    chat_turn_work.started()
    try:
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
        turn = ChatTurnExecution(
            setup,
            user,
            response_future,
            stream_buffer,
            query_observation=query_observation,
            dispatch_pending_messages=dispatch_pending_messages,
        )
        startup_error: Exception | None = None
        try:
            turn._auto_filters = load_settings().auto_detect_search_filters is not False
            clear_stop(setup.chat_session_id, setup.cache, stream_id=setup.stream_id)
            # Stop must identify this response before the client receives its IDs.
            setup.admission.publish(setup.stream_id)
        except Exception as error:
            startup_error = error
        if setup.new_msg_req.chat_session_id is None:
            turn.delivery.publish(
                CreateChatSessionID(
                    chat_session_id=setup.chat_session_id,
                    incognito=mode is not None,
                )
            )
        turn.delivery.publish(
            MultiModelMessageResponseIDInfo(
                user_message_id=setup.user_message_id,
                responses=[
                    ModelResponseSlot(
                        message_id=response.message_id, model_name=response.display_name
                    )
                    for response in setup.responses
                ],
            )
            if len(setup.responses) > 1
            else MessageResponseIDInfo(
                user_message_id=setup.user_message_id,
                reserved_assistant_message_id=setup.responses[0].message_id,
            )
        )
        if query_observation is not None:
            query_observation.writer_owned = True
        control = start_thread_future(
            lambda: turn.run(startup_error=startup_error),
            name="chat-control",
            daemon=False,
        )
        control.add_done_callback(lambda _future: chat_turn_work.finished())
        return turn.delivery.reader
    except BaseException as error:
        if query_observation is not None:
            query_observation.writer_owned = False
        if turn is None:
            try:
                setup.admission.release()
            finally:
                chat_turn_work.finished()
        else:
            turn.reject(error)
        raise
    finally:
        CURRENT_CONTENT_FREE_SESSION_ID_CONTEXTVAR.reset(session_token)
        CURRENT_INCOGNITO_RECORD_MODE_CONTEXTVAR.reset(mode_token)


class ChatTurnExecution:
    """Own chat response execution, Stop control, and delivery."""

    def __init__(
        self,
        setup: ChatTurnSetup,
        user: User,
        response_future: Future[ChatResponseOutcome] | None = None,
        stream_buffer: StreamBufferWriter | None = None,
        *,
        query_observation: QueryObservation | None = None,
        dispatch_pending_messages: Callable[[], None] | None = None,
    ) -> None:
        self.setup = setup
        self.user = user
        self.delivery = ChatDelivery(stream_buffer, query_observation=query_observation)
        self._query_observation = query_observation
        self._dispatch_pending_messages = dispatch_pending_messages
        self._stores: list[ChatRunStore] = []
        self.cancellation = CancellationSignal()
        self._response_future = response_future
        self._response_workers: dict[Future[Run | None], ChatResponsePersistence] = {}
        self._lock = threading.Lock()
        self._completion_changed = threading.Event()
        self.delivery.finished.add_done_callback(
            lambda _future: self._completion_changed.set()
        )
        self._auto_filters = False
        self._admission_released = False
        self._stopped_by_user = False
        # Each model gets one stop, including models still preparing at cancellation.
        self._stopped_models: set[int] = set()
        self._response_stops: dict[int, OverallStop] = {}
        self._last_refresh = self._last_stop_check = time.monotonic()
        # Each response run cancels itself at this time and records a DEADLINE failure.
        self._deadline_at = datetime.now(timezone.utc) + timedelta(
            seconds=CHAT_EXECUTION_TIMEOUT_S
        )

    def reject(self, error: BaseException) -> None:
        if self._query_observation is not None:
            self._query_observation.failed(error)
        self.cancellation.cancel()
        if self._response_future is not None:
            self._response_future.set_exception(error)

        def clear_status_then_finish() -> None:
            # The chat is released before its stream ends, so a client that sees
            # the end can send again at once.
            try:
                self._clear_processing_status()
            finally:
                try:
                    self.delivery.finish()
                finally:
                    self.delivery.finished.add_done_callback(
                        lambda _future: chat_turn_work.finished()
                    )

        # No control thread exists to observe cleanup for a rejected turn.
        try:
            start_thread_future(
                clear_status_then_finish, name="chat-status-cleanup", daemon=False
            )
        except Exception:
            logger.exception("Rejected chat processing status cleanup could not start")
            clear_status_then_finish()

    def _publish(self, packet: Packet) -> None:
        if not self.cancellation.cancelled:
            self.delivery.publish(packet)
            if isinstance(packet.obj, OverallStop):
                with self._lock:
                    self._stopped_models.add(packet.placement.model_index or 0)

    def run(self, *, startup_error: BaseException | None = None) -> None:
        research = (
            len(self.setup.responses) == 1 and self.setup.new_msg_req.deep_research
        )
        # The trace stays open while background agents still own work.
        with trace(
            "run_deep_research" if research else "chat",
            group_id=str(self.setup.chat_session_id),
            metadata=ChatTraceMetadata(
                chat_session_id=str(self.setup.chat_session_id),
                user_id=self.setup.user_identity.user_id,
            ).model_dump(),
        ):
            try:
                self.delivery.events.start()
            except Exception as error:
                startup_error = error
            if startup_error is not None:
                self.cancellation.cancel()
                self.delivery.publish(
                    chat_error(startup_error)
                    if isinstance(startup_error, OnyxError)
                    else StreamingError(
                        error="The response could not be started. Please try again.",
                        error_code="CHAT_STARTUP_ERROR",
                        is_retryable=True,
                    )
                )
            for index, response in enumerate(self.setup.responses):
                persistence = ChatResponsePersistence(
                    coordinator=AgentCoordinator(),
                    history_store=get_chat_history_store(
                        message_id=response.message_id,
                        chat_session_id=self.setup.chat_session_id,
                        admission=self.setup.admission,
                        persist_content=record_mode_persists_content(
                            self.setup.incognito_record_mode
                        ),
                    ),
                    model_index=index,
                    llm=response.llm,
                    delivery=self.delivery,
                    outcome=self._response_future
                    if index == 0 and self._response_future is not None
                    else Future[ChatResponseOutcome](),
                )
                emitter = Emitter(
                    self._publish, persistence.model_index, self._query_observation
                )
                try:
                    worker = start_thread_future(
                        lambda persistence=persistence, emitter=emitter: (
                            self._run_response(
                                persistence,
                                emitter,
                                startup_error=startup_error,
                            )
                        ),
                        name="chat-response",
                    )
                except Exception as error:
                    worker = Future[Run | None]()
                    worker.set_result(
                        self._run_response(persistence, emitter, startup_error=error)
                    )
                self._response_workers[worker] = persistence
                worker.add_done_callback(lambda _future: self._completion_changed.set())

            while True:
                # Clear before checking state so a concurrent completion cannot be lost.
                self._completion_changed.clear()
                try:
                    self._poll_control()
                except Exception:
                    self.cancellation.cancel()
                    logger.exception("Chat turn control failed; draining active work")
                try:
                    self._poll_responses()
                except Exception:
                    self.cancellation.cancel()
                    logger.exception(
                        "Chat response polling failed; draining active work"
                    )
                with self._lock:
                    stores = tuple(self._stores)
                # Saves have drained; release the chat before the stream ends,
                # so a client that sees the end can send again at once.
                if not self._response_workers and not self._admission_released:
                    self._clear_processing_status()
                if self._admission_released:
                    if not self.delivery.is_closing:
                        stop = self._turn_stop()
                        if stop is not None:
                            with self._lock:
                                pending = (
                                    set(range(len(self.setup.responses)))
                                    - self._stopped_models
                                )
                            for index in sorted(pending):
                                self.delivery.publish(
                                    Packet(
                                        placement=Placement(
                                            turn_index=0, model_index=index
                                        ),
                                        obj=self._response_stops.get(index, stop),
                                    )
                                )
                        self.delivery.finish()
                    if self.delivery.finished.done() and not any(
                        store.has_owned_work for store in stores
                    ):
                        return
                self._completion_changed.wait(_CANCEL_POLL_INTERVAL_S)

    def _poll_responses(self) -> None:
        for worker, persistence in tuple(self._response_workers.items()):
            run: Run | None = None
            worker_done = worker.done()
            try:
                if worker_done:
                    failure = worker.exception()
                    if failure is not None:
                        if isinstance(failure, Exception):
                            raise failure
                        raise RuntimeError("Chat response worker failed") from failure
                    run = worker.result()
                if not persistence.outcome.done():
                    persistence.expire_save()
                if not worker_done:
                    continue
                if run is not None:
                    if not run.status.is_terminal:
                        continue
                    try:
                        if not run.wait_for_idle(timeout=0):
                            continue
                    except Exception:
                        # An exceptional idle future reports failed cleanup after workers drain.
                        logger.exception("Chat response cleanup failed")
                        self.delivery.report_gap()
                    if run.delivery_failed:
                        self.delivery.report_gap()
                if not persistence.outcome.done():
                    raise RuntimeError(
                        "Chat response worker finished without an outcome"
                    )
            except Exception as failure:
                logger.exception("Chat response completion failed")
                self.cancellation.cancel()
                persistence.report_worker_failure(failure)
                if run is not None:
                    run.cancel()
                    continue
                if not worker_done:
                    continue
            if persistence.outcome.done() and persistence.outcome.exception() is None:
                snapshot = persistence.outcome.result().response.response
                if snapshot is not None:
                    self._response_stops[persistence.model_index] = overall_stop(
                        snapshot.status, snapshot.failure
                    )
            del self._response_workers[worker]

    def _clear_processing_status(self) -> None:
        def save_late_stop() -> None:
            # A Stop of this turn, even after its answer finished, pauses the queue.
            if not (
                self._stopped_by_user
                or is_stop_requested(
                    self.setup.chat_session_id,
                    self.setup.admission.cache,
                    stream_id=self.setup.stream_id,
                )
            ):
                return
            self._stopped_by_user = True
            with get_session_with_current_tenant() as session:
                pause_chat_queue__no_commit(session, self.setup.chat_session_id)
                session.commit()

        try:
            self.setup.admission.release(settle=save_late_stop)
            self._admission_released = True
        except Exception:
            logger.exception("Failed to clear chat processing status; will retry")
            return
        self._dispatch_after_release()

    def _dispatch_after_release(self) -> None:
        """Start queued input or a follow-up on child results once the chat is idle."""
        if not self._admission_released or self._dispatch_pending_messages is None:
            return
        try:
            self._dispatch_pending_messages()
        except Exception:
            logger.exception("Could not dispatch queued chat input")

    def _run_response(
        self,
        persistence: ChatResponsePersistence,
        emitter: Emitter,
        *,
        startup_error: BaseException | None = None,
    ) -> Run | None:
        index = persistence.model_index
        cancellation = CancellationSignal()
        links = ExitStack()
        links.enter_context(
            self.cancellation.on_cancel(
                lambda: cancellation.cancel(self.cancellation.reason or "requested")
            )
        )
        observation_token = CURRENT_QUERY_OBSERVATION.set(self._query_observation)
        try:
            if startup_error is not None:
                raise startup_error
            cancellation.check()
            # Agent tools need a caller that delivers follow-up responses.
            with_subagents = self._dispatch_pending_messages is not None
            chat_agent = create_chat_agent(
                self.setup,
                self.user,
                index,
                cancellation,
                self._auto_filters,
                with_subagents=with_subagents,
            )
            tool_ids = {tool.name: tool.id for tool in chat_agent.application_tools}
            persistence.tool_ids = dict(tool_ids)
            # Restored and child agents build their own tools from these.
            if isinstance(chat_agent, DeepResearchAgent):
                # Deep research offers its tools unchanged.
                configured_tools = chat_agent.application_tools
                if self.setup.research_tool_id is None:
                    raise ValueError("Deep research tool configuration is missing")
                persistence.tool_ids[RESEARCH_AGENT_TOOL_NAME] = (
                    self.setup.research_tool_id
                )
            else:
                configured_tools = chat_agent.configured_tools
                persistence.initial_citations = dict(chat_agent.initial_citations)
            if record_mode_persists_content(self.setup.incognito_record_mode):
                store, coordinator = bind_run_store(
                    self.setup,
                    self.user,
                    response_id=persistence.message_id,
                    llm=persistence.llm,
                    tools=configured_tools,
                    coordinator=persistence.coordinator,
                    follow_up_steps=chat_agent.max_steps,
                    with_subagents=with_subagents,
                    root_response=persistence,
                    on_child_released=self._dispatch_after_release,
                )
                with self._lock:
                    self._stores.append(store)
            else:
                # Incognito chats have no child agents to find, restore, or own.
                coordinator = persistence.coordinator.view(store=persistence)
            coordinator.register(
                AgentInfo(
                    id=chat_agent.id,
                    path="/root",
                    parent_id=None,
                    description="",
                    restoration_config=None,
                    latest_run_id=self.setup.previous_run_id,
                )
            )
            cancellation.check()
            run = chat_agent.start(
                background=False,
                messages=self.setup.input_messages,
                max_steps=chat_agent.max_steps,
                cancellation=cancellation,
                deadline_at=self._deadline_at,
                coordinator=coordinator,
                event_dispatcher=self.delivery.events,
                on_event=ResponsePresenter(emitter, tool_ids=tool_ids).consume,
            )

            def response_saved(completion: Future[RunState]) -> None:
                try:
                    if (
                        completion.exception() is not None
                        and not persistence.outcome.done()
                    ):
                        persistence.report_save_failure(run)
                finally:
                    links.close()
                    self._completion_changed.set()

            coordinator.completion(run.id).add_done_callback(response_saved)
            run.add_idle_callback(self._completion_changed.set)
            return run
        except BaseException as failure:
            try:
                persistence.save_failure(failure, cancellation.reason)
            except Exception:
                logger.exception(
                    "Response startup finalization failed for model %d", index
                )
            finally:
                links.close()
            return None
        finally:
            CURRENT_QUERY_OBSERVATION.reset(observation_token)

    def _turn_stop(self) -> OverallStop | None:
        """The stop packet the turn sends when it, not a response run, ended the work."""
        if self.cancellation.reason == "deadline":
            return overall_stop(
                RunStatus.CANCELLED,
                RunFailure(
                    kind=RunFailureKind.DEADLINE,
                    message="The chat turn reached its time limit.",
                ),
            )
        if self._stopped_by_user:
            return overall_stop(RunStatus.CANCELLED, None)
        return None

    def _poll_control(self) -> None:
        with self._lock:
            stores = tuple(self._stores)
        for store in stores:
            try:
                store.poll_control()
            except Exception:
                self.cancellation.cancel()
                logger.exception("Chat ownership control failed; will retry")

        # Background children keep their leases after this response releases the chat.
        if self._admission_released:
            return

        if (
            not self.cancellation.cancelled
            and datetime.now(timezone.utc) >= self._deadline_at + _DEADLINE_BACKSTOP
        ):
            logger.warning("Chat turn passed its deadline; cancelling remaining work")
            self.cancellation.cancel("deadline")

        now = time.monotonic()
        if (
            not self.cancellation.cancelled
            and now - self._last_stop_check >= _CANCEL_POLL_INTERVAL_S
        ):
            self._last_stop_check = now
            try:
                if is_stop_requested(
                    self.setup.chat_session_id,
                    self.setup.admission.cache,
                    stream_id=self.setup.stream_id,
                ):
                    self._stopped_by_user = True
                    self.cancellation.cancel()
            except Exception:
                logger.exception("Failed to read chat Stop request; will retry")
        if now - self._last_refresh >= PROCESSING_REFRESH_INTERVAL_S:
            self._last_refresh = now
            try:
                self.setup.admission.refresh()
            except CacheLockLostError:
                self.cancellation.cancel()
                logger.exception(
                    "Chat session admission was lost; draining active work"
                )
            except Exception:
                logger.exception("Failed to refresh chat processing status; will retry")


def bind_run_store(
    setup: ChatTurnSetup,
    user: User,
    *,
    response_id: int,
    llm: LLM,
    tools: list[Tool],
    coordinator: AgentCoordinator,
    follow_up_steps: int,
    with_subagents: bool,
    root_response: RunStore | None,
    on_child_released: Callable[[], None] | None,
) -> tuple[ChatRunStore, AgentCoordinator]:
    """Bind the run store of a response's branch and register the visible agents."""
    branch = load_chat_branch(response_id)
    if branch.chat_session_id != setup.chat_session_id:
        raise ValueError("Response belongs to another chat session")
    store = ChatRunStore(
        tenant_id=get_current_tenant_id(),
        chat_session_id=setup.chat_session_id,
        response_id=response_id,
        visible_response_ids=branch.message_ids,
        cache=get_cache_backend(),
        follow_up_steps=follow_up_steps,
        restore_subagent=partial(
            restore_subagent,
            setup=setup,
            llm=llm,
            tools=tools,
            inject_memories=user.use_memories,
        ),
        root_response=root_response,
        on_child_released=on_child_released,
    )
    view = store.bind(
        coordinator,
        build_agent=partial(
            restore_chat_agent,
            llm=llm,
            tools=tools,
            user_identity=setup.user_identity,
            create_subagent=chat_subagent_factory(
                setup=setup, llm=llm, tools=tools, inject_memories=user.use_memories
            )
            if with_subagents
            else None,
        ),
    )
    for info in store.list_agents():
        view.register(info)
    return store, view


def host_agent_work(
    setup: ChatTurnSetup, user: User, dispatch_pending_messages: Callable[[], None]
) -> None:
    """Start agents' queued work on the selected branch when no chat turn hosts it.

    The host starts no root run. It holds chat admission through its first
    scan, so hosts and turns do not start the same work. It runs on the calling
    thread until the agents it started release their leases.
    """
    try:
        response = setup.responses[0]
        chat_agent = create_chat_agent(
            setup,
            user,
            0,
            CancellationSignal(),
            load_settings().auto_detect_search_filters is not False,
            with_subagents=True,
        )
        if not isinstance(chat_agent, ChatAgent):
            raise ValueError("Agent work requires a chat agent")
        store, _ = bind_run_store(
            setup,
            user,
            response_id=response.message_id,
            llm=response.llm,
            tools=chat_agent.configured_tools,
            coordinator=AgentCoordinator(),
            follow_up_steps=chat_agent.max_steps,
            with_subagents=True,
            root_response=None,
            on_child_released=dispatch_pending_messages,
        )
        store.poll_control()
    finally:
        setup.admission.release()
    while store.has_owned_work:
        time.sleep(_CANCEL_POLL_INTERVAL_S)
        try:
            store.poll_control()
        except Exception:
            logger.exception("Agent host control failed; will retry")


def create_chat_agent(
    setup: ChatTurnSetup,
    user: User,
    response_index: int,
    cancellation: CancellationSignal,
    auto_detect_search_filters: bool,
    *,
    with_subagents: bool,
) -> ChatAgent | DeepResearchAgent:
    llm = setup.responses[response_index].llm
    with cancellation_scope(cancellation):
        cancellation.check()
        tool_configuration = setup.tool_configuration
        if setup.incognito_record_mode is not None:
            # Incognito chats have no child agents, and these features run as children.
            tool_configuration = tool_configuration.model_copy(
                update={
                    "tools": [
                        tool
                        for tool in tool_configuration.tools
                        if tool.in_code_tool_id != CODING_AGENT_TOOL_ID
                    ]
                }
            )
        filters = setup.new_msg_req.internal_search_filters
        source_types = filters.source_type if filters else None
        # Tools open DB sessions on demand, so model I/O cannot retain a connection.
        tools_by_type = construct_tools(
            configuration=tool_configuration,
            user=user,
            llm=llm,
            selection_llm_factory=partial(
                get_search_selection_llm,
                fallback=llm,
                additional_headers=setup.litellm_additional_headers,
                policy_fn=partial(
                    incognito_llm_request_policy, setup.incognito_record_mode
                ),
            ),
            search_tool_config=SearchToolConfig(
                user_selected_filters=setup.new_msg_req.internal_search_filters,
                project_id_filter=setup.search_params.project_id_filter,
                persona_id_filter=setup.search_params.persona_id_filter,
                slack_context=setup.slack_context,
                enable_slack_search=(
                    source_types is not None and DocumentSource.SLACK in source_types
                )
                or (setup.persona_id == DEFAULT_PERSONA_ID and source_types is None),
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
        tools = [tool for tool_list in tools_by_type.values() for tool in tool_list]

        preferred_tool_id = setup.preferred_tool_id
        if preferred_tool_id is not None and preferred_tool_id not in {
            tool.id for tool in tools
        }:
            if not setup.preferred_tool_saved:
                raise OnyxError(
                    OnyxErrorCode.BAD_REQUEST,
                    f"Preferred tool {preferred_tool_id} not found in tools",
                )
            preferred_tool_id = None

        agent_id = str(setup.chat_session_id)

        if len(setup.responses) == 1 and setup.new_msg_req.deep_research:
            return DeepResearchAgent(
                agent_id=agent_id,
                messages=list(setup.messages),
                allowed_tools=tools,
                additional_context=setup.additional_context,
                context_files=ExtractedContextFiles(
                    file_texts=[],
                    image_files=setup.extracted_context_files.image_files,
                    use_as_search_filter=False,
                    total_token_count=sum(
                        image.token_count
                        for image in setup.extracted_context_files.image_files
                    ),
                    file_metadata=[],
                    uncapped_token_count=None,
                ),
                llm=llm,
                token_counter=get_llm_token_counter(llm),
                user_identity=setup.user_identity,
                language_section=build_language_section(
                    setup.user_memory_context.user_info.language
                ),
                reasoning_effort=setup.reasoning_effort,
                all_injected_file_metadata=setup.all_injected_file_metadata,
                skip_clarification=SKIP_DEEP_RESEARCH_CLARIFICATION
                or setup.skip_clarification,
                checkpoint=setup.checkpoint,
                previous_run_id=setup.previous_run_id,
            )
        return build_chat_agent(
            AgentState(messages=list(setup.messages), checkpoint=setup.checkpoint),
            agent_id,
            setup.previous_run_id,
            setup=setup,
            llm=llm,
            tools=tools,
            inject_memories=user.use_memories,
            with_subagents=with_subagents,
            additional_context=setup.additional_context,
            preferred_tool_id=preferred_tool_id,
        )
