"""Run chat turns independently of browser connections."""

import threading
import time
from collections.abc import Callable
from concurrent.futures import Future
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from functools import partial
from typing import Protocol
from uuid import UUID

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
from onyx.agents.runtime import Agent, Run
from onyx.cache.factory import get_cache_backend
from onyx.cache.interface import CacheLockLostError
from onyx.chat.agent import (
    ChatFeature,
    build_chat_agent,
    chat_max_steps,
    chat_subagent_factory,
)
from onyx.chat.chat_processing_checker import (
    PROCESSING_REFRESH_INTERVAL_S,
    ChatTurnAdmission,
)
from onyx.chat.emitter import Emitter
from onyx.chat.errors import chat_error
from onyx.chat.history_store import get_chat_history_store
from onyx.chat.incognito import incognito_llm_request_policy
from onyx.chat.incognito_context import incognito_session_ended
from onyx.chat.models import (
    ChatResponseOutcome,
    ChatSessionNameInfo,
    ChatTurnSetup,
    CreateChatSessionID,
)
from onyx.chat.persistence import ChatResponsePersistence
from onyx.chat.presentation import ResponsePresenter, overall_stop
from onyx.chat.prompt_utils import build_language_section
from onyx.chat.restoration import restore_chat_agent, restore_subagent
from onyx.chat.run_store import (
    RESUME_FAILED_MESSAGE,
    RETRYABLE_START_ERRORS,
    ChatRunStore,
    fail_suspended_response,
)
from onyx.chat.session_naming import name_new_chat_session
from onyx.chat.stop_signal_checker import clear_stop, is_stop_requested
from onyx.chat.stream_buffer import ChatDelivery, ChatStream, StreamBufferWriter
from onyx.configs.chat_configs import (
    CHAT_EXECUTION_TIMEOUT_S,
    CODE_MODE_ENABLED,
    SKIP_DEEP_RESEARCH_CLARIFICATION,
)
from onyx.configs.constants import DEFAULT_PERSONA_ID, DocumentSource
from onyx.db.chat_checkpoint import chat_has_checkpoint, resumable_parked_runs
from onyx.db.chat_inputs import pause_chat_queue__no_commit
from onyx.db.chat_response import read_suspended_response_replay
from onyx.db.chat_subagents import load_chat_branch
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import record_mode_persists_content
from onyx.db.models import User
from onyx.deep_research.agent import DeepResearchFeature
from onyx.deep_research.tool_definitions import RESEARCH_AGENT_TOOL_NAME
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.models import ExtractedContextFiles
from onyx.integrations.models import ApprovalMode
from onyx.llm.cancellation import CancellationSignal, cancellation_scope
from onyx.llm.factory import get_llm_token_counter, get_search_selection_llm
from onyx.llm.interfaces import LLM
from onyx.server.query_and_chat.models import (
    ModelResponseSlot,
    response_id_info,
)
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import (
    OverallStop,
    Packet,
    ReplayEnd,
    StreamingError,
    ToolApprovalResolved,
    ToolQuestionResolved,
)
from onyx.server.settings.store import load_settings
from onyx.tools.interface import Tool
from onyx.tools.models import ToolOptions
from onyx.tools.tool_constructor import (
    CustomToolConfig,
    FileReaderToolConfig,
    SearchToolConfig,
    construct_tools,
)
from onyx.tools.tool_implementations.question.question_tool import QuestionTool
from onyx.tools.tool_implementations.sandbox.sandbox_tools import (
    SANDBOX_TOOLS,
    LoadSkillTool,
)
from onyx.tools.tool_implementations.sandbox.turn import SandboxTurn
from onyx.tools.tool_implementations.skills.skill_tools import (
    SKILL_READ_SHAPES,
    SkillsListTool,
    SkillsReadTool,
)
from onyx.tracing.framework.create import ChatTraceMetadata, trace
from onyx.utils.fleet_query_telemetry import CURRENT_QUERY_OBSERVATION, QueryObservation
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import (
    start_thread_future,
    start_thread_with_context,
)
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


class DispatchPendingMessages(Protocol):
    """Start the chat's queued work (`dispatch_pending_chat_messages`), with
    the admission that an ending turn hands over, if any. With `retry_resume`,
    a resume failed to start for a moment, and the dispatch runs after a
    backoff."""

    def __call__(
        self,
        *,
        admission: ChatTurnAdmission | None = None,
        retry_resume: bool = False,
    ) -> None: ...


def root_response_resumes(chat_session_id: UUID) -> bool:
    """Whether a parked root response of the chat waits only to continue."""
    try:
        with get_session_with_current_tenant() as session:
            # Most chats have no parked root, and one EXISTS read shows it.
            return chat_has_checkpoint(session, chat_session_id) and any(
                run.is_root for run in resumable_parked_runs(session, chat_session_id)
            )
    except Exception:
        logger.exception("Could not read the chat's parked responses")
        return False


def start_chat_turn(
    setup: ChatTurnSetup,
    user: User,
    response_future: Future[ChatResponseOutcome] | None = None,
    *,
    query_observation: QueryObservation | None = None,
    dispatch_pending_messages: DispatchPendingMessages | None = None,
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
            # A published stream ID always has a buffer that resume can serve.
            stream_buffer.open()
            # Stop must identify this response before the client receives its IDs.
            setup.admission.publish(
                setup.stream_id,
                [response.message_id for response in setup.responses],
                resumed=setup.resumed_response_id is not None,
            )
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
            response_id_info(
                setup.user_message_id,
                [
                    ModelResponseSlot(
                        message_id=response.message_id, model_name=response.display_name
                    )
                    for response in setup.responses
                ],
                setup.mentions,
            )
        )
        if setup.auto_name:
            # In parallel with the answer; a failure never touches the turn.
            start_thread_with_context(
                _name_new_chat_session,
                name="chat-naming",
                args=(setup, user, turn.delivery),
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


def _name_new_chat_session(
    setup: ChatTurnSetup, user: User, delivery: ChatDelivery
) -> None:
    """Name a new chat from its first question, and send the name on the
    turn's stream. A stream that already ended drops the packet; the saved name
    reaches the client on its next session fetch."""
    try:
        name = name_new_chat_session(
            chat_session_id=setup.chat_session_id,
            user=user,
            chat_llm=setup.responses[0].llm,
            additional_headers=setup.litellm_additional_headers,
        )
    except Exception:
        logger.exception("Could not name the new chat session")
        return
    # Only a client that asked for it reads this line.
    if name is not None and setup.new_msg_req.accepts_chat_session_name:
        delivery.publish(
            ChatSessionNameInfo(
                chat_session_id=setup.chat_session_id, chat_session_name=name
            )
        )


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
        dispatch_pending_messages: DispatchPendingMessages | None = None,
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
        # A resume that storage failed to start retries after a backoff.
        self._resume_deferred = False
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
        # A resolution reports a saved outcome, such as the rejection or
        # cancellation of a Stop, so the card shows it after the turn stops.
        if not self.cancellation.cancelled or isinstance(
            packet.obj, (ToolApprovalResolved, ToolQuestionResolved)
        ):
            self.delivery.publish(packet)
            if isinstance(packet.obj, OverallStop):
                with self._lock:
                    self._stopped_models.add(packet.placement.model_index or 0)

    def run(self, *, startup_error: BaseException | None = None) -> None:
        research = self.setup.is_deep_research
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
                    # A parked run resolved its outcome when it handed off.
                    if not run.status.is_terminal and not persistence.outcome.done():
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

    def _root_parked(self, persistence: ChatResponsePersistence, run: Run) -> None:
        """End a response whose run handed off to wait for people: the turn
        stops it with `awaiting_user`, and the decisions and answers resume it
        on any pod."""
        persistence.report_suspended(run)
        # The stream keeps naming it, so `model_index` still indexes the
        # stream's responses; its decisions continue it in a new stream.
        self._publish(
            Packet(
                placement=Placement(turn_index=0, model_index=persistence.model_index),
                obj=overall_stop(RunStatus.SUSPENDED, None),
            )
        )

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
            successor = self.setup.admission.release(
                settle=save_late_stop,
                # The resume of a parked root response takes admission over,
                # whichever turn parked it, so the chat does not show idle in
                # between. A deferred resume retries after a backoff instead.
                hand_off=partial(root_response_resumes, self.setup.chat_session_id)
                if not self._resume_deferred
                and self._dispatch_pending_messages is not None
                else None,
            )
            self._admission_released = True
        except Exception:
            logger.exception("Failed to clear chat processing status; will retry")
            return
        self._dispatch_after_release(successor)

    def _dispatch_after_release(
        self, admission: ChatTurnAdmission | None = None
    ) -> None:
        """Start queued input or a follow-up on child results once the chat is
        idle, or with the `admission` that this turn handed over."""
        if not self._admission_released or self._dispatch_pending_messages is None:
            return
        try:
            self._dispatch_pending_messages(
                admission=admission, retry_resume=self._resume_deferred
            )
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
        resumed_id = self.setup.resumed_response_id
        run: Run | None = None
        replayed = False
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
            # Agent tools need a caller that delivers follow-up responses and a
            # client that shows them. A multi-model turn has no single answer for
            # results to follow.
            with_subagents = (
                self._dispatch_pending_messages is not None
                and self.setup.new_msg_req.accepts_follow_ups
                and len(self.setup.responses) == 1
            )

            def adopt_root(feature: ChatFeature | DeepResearchFeature) -> None:
                # Persistence saves only the calls of the tools the root offers.
                persistence.tool_ids = {
                    tool.name: tool.id for tool in feature.application_tools
                }
                if isinstance(feature, DeepResearchFeature):
                    if self.setup.research_tool_id is None:
                        raise ValueError("Deep research tool configuration is missing")
                    persistence.tool_ids[RESEARCH_AGENT_TOOL_NAME] = (
                        self.setup.research_tool_id
                    )
                else:
                    persistence.initial_citations = dict(feature.initial_citations)

            new_root = (
                create_chat_agent(
                    self.setup,
                    self.user,
                    index,
                    cancellation,
                    self._auto_filters,
                    with_subagents=with_subagents,
                )
                if resumed_id is None
                else None
            )
            if new_root is not None:
                _, feature = new_root
                adopt_root(feature)
                # Restored and child agents build their own tools from these.
                # Deep research offers its tools unchanged.
                tools = (
                    feature.application_tools
                    if isinstance(feature, DeepResearchFeature)
                    else feature.configured_tools
                )
                # A new root ends its sandbox turn itself, and the run store
                # restores no root of this turn.
                on_root_drained = None
            else:
                # The run store restores the root from its checkpoint.
                tools, sandbox = construct_chat_tools(
                    self.setup, self.user, index, cancellation, self._auto_filters
                )
                on_root_drained = sandbox.end if sandbox is not None else None
            # The presenter and the run store use the configured tools for
            # display ids only.
            presenter = ResponsePresenter(
                emitter, tool_ids={tool.name: tool.id for tool in tools}
            )
            store: ChatRunStore | None = None
            if record_mode_persists_content(self.setup.incognito_record_mode):
                store, coordinator = bind_run_store(
                    self.setup,
                    self.user,
                    response_id=persistence.message_id,
                    llm=persistence.llm,
                    tools=tools,
                    coordinator=persistence.coordinator,
                    follow_up_steps=chat_max_steps(tools, CODE_MODE_ENABLED),
                    root_response=persistence,
                    on_child_released=self._dispatch_after_release,
                    on_root_drained=on_root_drained,
                    on_root_restored=adopt_root,
                    on_root_parked=partial(self._root_parked, persistence),
                )
                with self._lock:
                    self._stores.append(store)
            else:
                # Incognito chats have no child agents to find, restore, or own,
                # and no approvals.
                coordinator = persistence.coordinator.view(store=persistence)
            if new_root is not None:
                chat_agent, feature = new_root
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
                    max_steps=feature.max_steps,
                    cancellation=cancellation,
                    deadline_at=self._deadline_at,
                    coordinator=coordinator,
                    event_dispatcher=self.delivery.events,
                    on_event=presenter.consume,
                )
            elif resumed_id is not None and store is not None:
                # The saved output first, then the run with the saved decisions.
                with get_session_with_current_tenant() as db_session:
                    execution, replay = read_suspended_response_replay(
                        db_session, resumed_id
                    )
                presenter.replay(execution.response, replay, execution.presentation)
                replayed = True
                resumed = store.resume(
                    str(resumed_id),
                    context=AgentState(
                        messages=list(self.setup.messages),
                        checkpoint=self.setup.checkpoint,
                    ),
                    deadline_at=self._deadline_at,
                    on_event=presenter.consume,
                    event_dispatcher=self.delivery.events,
                )
                if resumed is None:
                    raise RuntimeError("The response no longer waits to continue")
                run = resumed
                links.enter_context(
                    cancellation.on_cancel(
                        lambda: resumed.cancel(cancellation.reason or "requested")
                    )
                )
            else:
                raise ValueError("Only a saved chat response can continue")

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
                if resumed_id is not None and run is None:
                    if not replayed:
                        emitter.emit(
                            Packet(placement=Placement(turn_index=0), obj=ReplayEnd())
                        )
                    if isinstance(failure, RETRYABLE_START_ERRORS):
                        # The response stays suspended, and this turn's
                        # release dispatches it again after a backoff.
                        self._resume_deferred = True
                    else:
                        # The response ends as failed, so no later dispatch
                        # tries it again.
                        fail_suspended_response(
                            self.setup.cache, get_current_tenant_id(), resumed_id
                        )
                    persistence.report_worker_failure(
                        failure
                        if isinstance(failure, Exception)
                        else RuntimeError(RESUME_FAILED_MESSAGE)
                    )
                else:
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
                    # Before the runs stop, so their requests end rejected
                    # and their questions cancelled.
                    for store in stores:
                        store.reject_waiting_inputs()
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
    root_response: RunStore | None,
    on_child_released: Callable[[], None] | None,
    on_root_drained: Callable[[], None] | None,
    on_root_restored: Callable[[ChatFeature | DeepResearchFeature], None] | None = None,
    on_root_parked: Callable[[Run], None] | None = None,
) -> tuple[ChatRunStore, AgentCoordinator]:
    """Bind the run store of a response's branch and register the visible
    agents. A restored root gets `on_root_drained` as its on_drained hook, and
    the question tool when its saved step declared it; `on_root_restored`
    receives its feature."""
    tenant_id = get_current_tenant_id()
    branch = load_chat_branch(response_id)
    if branch.chat_session_id != setup.chat_session_id:
        raise ValueError("Response belongs to another chat session")
    store = ChatRunStore(
        tenant_id=tenant_id,
        chat_session_id=setup.chat_session_id,
        response_id=response_id,
        visible_response_ids=branch.message_ids,
        cache=get_cache_backend(),
        follow_up_steps=follow_up_steps,
        user=user,
        restore_subagent=partial(
            restore_subagent,
            setup=setup,
            llm=llm,
            tools=tools,
            inject_memories=setup.use_memories,
        ),
        root_response=root_response,
        on_child_released=on_child_released,
        tools=tools,
        # Child-result delivery saves no user message.
        answers_agent_results=setup.user_message_id is None,
        on_root_parked=on_root_parked,
        model_configuration_id=llm.config.model_configuration_id,
        temperature=llm.config.temperature,
        # Explicit defaults: a turn that the server starts later compares
        # them with its own, and None would fall back to the chat's options.
        tool_options=setup.new_msg_req.tool_options or ToolOptions(),
    )
    view = store.bind(
        coordinator,
        build_agent=partial(
            restore_chat_agent,
            llm=llm,
            tools=tools,
            user_identity=setup.user_identity,
            on_root_drained=on_root_drained,
            on_root_restored=on_root_restored,
            question_tool=lambda response_id, shape: QuestionTool(
                shape,
                tenant_id=tenant_id,
                chat_session_id=setup.chat_session_id,
                response_id=response_id,
            ),
            subagent_factory=lambda depth: chat_subagent_factory(
                setup=setup,
                llm=llm,
                tools=tools,
                inject_memories=setup.use_memories,
                depth=depth,
            ),
        ),
    )
    for info in store.list_agents():
        view.register(info)
    return store, view


def host_agent_work(
    setup: ChatTurnSetup,
    user: User,
    dispatch_pending_messages: DispatchPendingMessages,
) -> None:
    """Start agents' queued work on the selected branch when no chat turn hosts it.

    The host starts no root run. It holds chat admission through its first
    scan, so hosts and turns do not start the same work, then hands it to the
    resume of a parked root response that can continue. It runs on the calling
    thread until the agents it started release their leases.
    """
    # The trace makes hosted model calls count toward usage records and limits.
    with trace(
        "chat",
        group_id=str(setup.chat_session_id),
        metadata=ChatTraceMetadata(
            chat_session_id=str(setup.chat_session_id),
            user_id=setup.user_identity.user_id,
        ).model_dump(),
    ):
        try:
            response = setup.responses[0]
            if setup.is_deep_research:
                raise ValueError("Agent work requires a chat agent")
            # The host restores only child agents, so no root ends the
            # sandbox turn.
            tools, _ = construct_chat_tools(
                setup,
                user,
                0,
                CancellationSignal(),
                load_settings().auto_detect_search_filters is not False,
            )
            store, _ = bind_run_store(
                setup,
                user,
                response_id=response.message_id,
                llm=response.llm,
                tools=tools,
                coordinator=AgentCoordinator(),
                follow_up_steps=chat_max_steps(tools, CODE_MODE_ENABLED),
                root_response=None,
                on_child_released=dispatch_pending_messages,
                on_root_drained=None,
            )
            store.poll_control()
        except BaseException:
            setup.admission.release()
            raise
        successor = setup.admission.release(
            hand_off=partial(root_response_resumes, setup.chat_session_id)
        )
        # A child that finished during the first scan dispatched while the host
        # held admission, so its results wait for this dispatch.
        try:
            dispatch_pending_messages(admission=successor)
        except Exception:
            logger.exception("Could not dispatch queued chat input")
        while store.has_owned_work:
            time.sleep(_CANCEL_POLL_INTERVAL_S)
            try:
                store.poll_control()
            except Exception:
                logger.exception("Agent host control failed; will retry")


def construct_chat_tools(
    setup: ChatTurnSetup,
    user: User,
    response_index: int,
    cancellation: CancellationSignal,
    auto_detect_search_filters: bool,
) -> tuple[list[Tool], SandboxTurn | None]:
    """The configured tools of one response, and the sandbox turn that its
    root agent's runs end (its on_drained hook) when the turn offers the
    sandbox tools. Restored and child agents receive the same tools."""
    llm = setup.responses[response_index].llm
    with cancellation_scope(cancellation):
        cancellation.check()
        filters = setup.new_msg_req.internal_search_filters
        source_types = filters.source_type if filters else None
        # Tools open DB sessions on demand, so model I/O cannot retain a connection.
        tools = construct_tools(
            configuration=setup.tool_configuration,
            user=user,
            llm=llm,
            enable_memory_tool=setup.enable_memory_tool,
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
            tool_options=setup.new_msg_req.tool_options,
            search_usage_forcing_setting=setup.search_params.search_usage,
            approval_mode=setup.approval_mode,
        )
        # Every user with a chat skill when the turn starts gets the skill
        # tools, whatever the agent's tool selection; each call reads the
        # user's current skills.
        if setup.has_chat_skills:
            tools += [
                SkillsListTool(
                    user,
                    SKILL_READ_SHAPES[llm.config.tool_family],
                    with_sandbox=setup.sandbox_tools,
                ),
                SkillsReadTool(
                    user,
                    SKILL_READ_SHAPES[llm.config.tool_family],
                    with_sandbox=setup.sandbox_tools,
                ),
            ]
        # The chat agent and its subagents share one sandbox turn. Deep
        # research turns never offer the sandbox tools.
        if not setup.sandbox_tools:
            return tools, None
        sandbox = SANDBOX_TOOLS[llm.config.tool_family]
        turn = SandboxTurn(
            tenant_id=get_current_tenant_id(),
            user_id=user.id,
            chat_session_id=setup.chat_session_id,
            vm_chat_files=setup.vm_chat_files,
            copy_vm_chat_files=setup.copy_vm_chat_files,
            shell=sandbox.shell,
        )
        sandbox_tools = [tool(turn) for tool in sandbox.tools]
        # A turn that runs without asking (evals) gates no built-in action,
        # as integration policies allow its Ask actions.
        if setup.approval_mode is ApprovalMode.RUN_WITHOUT_ASKING:
            for tool in sandbox_tools:
                tool.approval = None
        tools += sandbox_tools
        if setup.has_chat_skills:
            tools.append(LoadSkillTool(turn))
        return tools, turn


def create_chat_agent(
    setup: ChatTurnSetup,
    user: User,
    response_index: int,
    cancellation: CancellationSignal,
    auto_detect_search_filters: bool,
    *,
    with_subagents: bool,
) -> tuple[Agent, ChatFeature | DeepResearchFeature]:
    """The root agent of a new response, and its feature."""
    tools, turn = construct_chat_tools(
        setup, user, response_index, cancellation, auto_detect_search_filters
    )
    llm = setup.responses[response_index].llm
    preferred_tool = setup.preferred_tool
    if preferred_tool is not None and not any(
        tool.matches(preferred_tool) for tool in tools
    ):
        if not setup.preferred_tool_saved:
            raise OnyxError(
                OnyxErrorCode.BAD_REQUEST,
                f"Preferred {preferred_tool} not found in tools",
            )
        preferred_tool = None

    agent_id = str(setup.chat_session_id)

    if setup.is_deep_research:
        feature = DeepResearchFeature(
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
        )
        return (
            feature.agent(
                AgentState(messages=list(setup.messages), checkpoint=setup.checkpoint),
                agent_id=agent_id,
                previous_run_id=setup.previous_run_id,
            ),
            feature,
        )
    return build_chat_agent(
        AgentState(messages=list(setup.messages), checkpoint=setup.checkpoint),
        agent_id,
        setup.previous_run_id,
        setup=setup,
        llm=llm,
        tools=tools,
        on_drained=turn.end if turn is not None else None,
        inject_memories=setup.use_memories,
        with_subagents=with_subagents,
        additional_context=setup.additional_context,
        question_tool=partial(
            QuestionTool,
            tenant_id=get_current_tenant_id(),
            chat_session_id=setup.chat_session_id,
            response_id=setup.responses[response_index].message_id,
        )
        if setup.question_tool
        else None,
        preferred_tool=preferred_tool,
    )
