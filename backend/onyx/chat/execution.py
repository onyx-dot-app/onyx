"""Run chat turns independently of browser connections."""

import threading
import time
from concurrent.futures import Future, wait

from onyx.agents.coordination import AgentCoordinator
from onyx.agents.runtime import Run
from onyx.agents.transcript import RunStatus
from onyx.chat.agent import ChatAgent
from onyx.chat.cancellation import clear_stop, is_stop_requested
from onyx.chat.chat_processing_checker import (
    PROCESSING_REFRESH_INTERVAL_S,
    set_processing_status,
)
from onyx.chat.emitter import Emitter
from onyx.chat.errors import chat_error
from onyx.chat.models import (
    PERSISTENCE_ERROR_MESSAGES,
    ChatResponseOutcome,
    ChatResponseSnapshot,
    ChatTurnSetup,
    PersistenceStatus,
    StreamingError,
)
from onyx.chat.prepare import create_chat_agent
from onyx.chat.presentation import ResponsePresenter, project_response
from onyx.chat.stream_buffer import ChatDelivery, ChatStream, StreamBufferWriter
from onyx.chat.subagents import create_chat_agent_coordinator
from onyx.configs.chat_configs import (
    CHAT_RESPONSE_WAIT_TIMEOUT_S,
)
from onyx.db.chat_response import save_chat_response
from onyx.db.enums import record_mode_persists_content
from onyx.db.models import User
from onyx.deep_research.agent import DeepResearchAgent
from onyx.deep_research.tool_definitions import RESEARCH_AGENT_TOOL_NAME
from onyx.error_handling.exceptions import OnyxError
from onyx.llm.cancellation import AgentCancelled, CancellationSignal
from onyx.server.query_and_chat.streaming_models import OverallStop, Packet
from onyx.server.settings.store import load_settings
from onyx.tracing.framework.create import ChatTraceMetadata, trace
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import start_thread_future

logger = setup_logger()
_CANCEL_POLL_INTERVAL_S = 0.25
_PERSISTENCE_WAIT_SECONDS = 30.0


def _log_late_save(future: Future[None]) -> None:
    try:
        future.result()
    except Exception:
        logger.exception("Response save failed after its wait bound")
    else:
        logger.debug("Response save completed after its wait bound")


class ActiveChatTurns:
    """Retain active turns until execution, storage, and delivery finish."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pending: dict[Future[None], ChatTurnExecution] = {}
        self._closing = False

    def start(
        self, turn: "ChatTurnExecution", *, startup_error: Exception | None = None
    ) -> None:
        with self._lock:
            closing = self._closing
            if not closing:
                self._pending[turn.finished] = turn
        if closing:
            error = RuntimeError("The API server is shutting down")
            turn.reject(error)
            raise error
        turn.finished.add_done_callback(self._finished)
        try:
            start_thread_future(
                lambda: turn.run(startup_error=startup_error), name="chat-control"
            )
        except Exception as error:
            turn.reject(error)
            raise

    def _finished(self, future: Future[None]) -> None:
        with self._lock:
            del self._pending[future]

    def close(self) -> bool:
        """Reject new turns and wait for active work to finish."""
        with self._lock:
            self._closing = True
            pending = dict(self._pending)
        for turn in pending.values():
            turn.cancellation.cancel()
        if not pending:
            return True
        _, unfinished = wait(pending, timeout=_PERSISTENCE_WAIT_SECONDS)
        if unfinished:
            logger.error(
                "API shutdown has %d chat turns still draining", len(unfinished)
            )
        return not unfinished


def start_chat_turn(
    setup: ChatTurnSetup,
    user: User,
    response_future: Future[ChatResponseOutcome] | None = None,
    stream_buffer: StreamBufferWriter | None = None,
    *,
    active_chat_turns: ActiveChatTurns | None = None,
) -> ChatStream:
    turn = ChatTurnExecution(setup, user, response_future, stream_buffer)
    startup_error: Exception | None = None
    try:
        turn.begin()
    except Exception as error:
        startup_error = error
    (active_chat_turns or ActiveChatTurns()).start(turn, startup_error=startup_error)
    return turn.delivery.reader


class ChatTurnExecution:
    """Own response execution, Stop control, and delivery for one user message."""

    def __init__(
        self,
        setup: ChatTurnSetup,
        user: User,
        response_future: Future[ChatResponseOutcome] | None = None,
        stream_buffer: StreamBufferWriter | None = None,
    ) -> None:
        self.setup = setup
        self.user = user
        self.delivery = ChatDelivery(stream_buffer)
        self.cancellation = CancellationSignal()
        self.finished: Future[None] = Future()
        self._response_futures = [
            response_future
            if index == 0 and response_future is not None
            else Future[ChatResponseOutcome]()
            for index in range(len(setup.responses))
        ]
        self._lock = threading.Lock()
        self._unfinished = set(range(len(setup.responses)))
        self._execution_drained: set[int] = set()
        self._delivery_finished = False
        self._changed = threading.Event()
        self._auto_filters = False
        self._stopped_by_user = False
        self._last_refresh = self._last_stop_check = time.monotonic()

    def begin(self) -> None:
        """Publish the processing key before the caller can expose response IDs."""
        self._auto_filters = load_settings().auto_detect_search_filters is not False
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

    def reject(self, error: Exception) -> None:
        for index, response_future in enumerate(self._response_futures):
            response_future.set_exception(error)
            self._finish_response(index)
        self._close_delivery()

    def _publish(self, packet: Packet) -> None:
        if not self.cancellation.cancelled:
            self.delivery.publish(packet)

    def run(self, *, startup_error: BaseException | None = None) -> None:
        try:
            self.delivery.start()
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
        for index, response_future in enumerate(self._response_futures):
            emitter = Emitter(
                self._publish, self.setup.responses[index].message_id, index
            )
            try:
                start_thread_future(
                    lambda index=index, response_future=response_future, emitter=emitter: (
                        self._run_response(
                            index,
                            response_future,
                            emitter,
                            self._auto_filters,
                            startup_error=startup_error,
                        )
                    ),
                    name="chat-response",
                )
            except Exception as error:
                self._run_response(
                    index,
                    response_future,
                    emitter,
                    self._auto_filters,
                    startup_error=error,
                )
        deadline = (
            time.monotonic()
            + CHAT_RESPONSE_WAIT_TIMEOUT_S
            + 2 * _PERSISTENCE_WAIT_SECONDS
        )
        try:
            while time.monotonic() < deadline:
                self._poll_control()
                with self._lock:
                    drained = len(self._execution_drained) == len(
                        self._response_futures
                    )
                if all(future.done() for future in self._response_futures) and (
                    drained or self.cancellation.cancelled
                ):
                    break
                self._changed.wait(
                    timeout=min(
                        _CANCEL_POLL_INTERVAL_S, max(0.0, deadline - time.monotonic())
                    )
                )
                self._changed.clear()
            else:
                logger.error("Chat turn exceeded its response wait bound")
                self.cancellation.cancel()
            if self._stopped_by_user:
                self.delivery.publish(
                    Packet(
                        obj=OverallStop(stop_reason="user_cancelled"),
                    )
                )
        except Exception:
            self.cancellation.cancel()
            logger.exception("Chat turn control failed")
        finally:
            self._close_delivery()

    def _close_delivery(self) -> None:
        def drained(_future: Future[None]) -> None:
            with self._lock:
                self._delivery_finished = True
                finished = not self._unfinished
            if finished:
                self.finished.set_result(None)

        try:
            self._finish_delivery()
        finally:
            self.delivery.finished.add_done_callback(drained)

    def _finish_response(self, index: int) -> None:
        with self._lock:
            self._unfinished.remove(index)
            finished = not self._unfinished and self._delivery_finished
        if finished:
            self.finished.set_result(None)

    def _retain_resources(
        self, index: int, run: Run | None, save: Future[None] | None
    ) -> None:
        def drained() -> None:
            if run is not None and run.delivery_failed:
                self.delivery.report_gap()
            with self._lock:
                self._execution_drained.add(index)
            self._changed.set()
            if save is None:
                self._finish_response(index)
            else:
                save.add_done_callback(lambda _: self._finish_response(index))

        if run is None:
            drained()
        else:
            run.add_idle_callback(drained)

    def _run_response(
        self,
        index: int,
        response_future: Future[ChatResponseOutcome],
        emitter: Emitter,
        auto_filters: bool,
        *,
        startup_error: BaseException | None = None,
    ) -> None:
        cancellation = CancellationSignal()
        run: Run | None = None
        chat_agent: ChatAgent | DeepResearchAgent | None = None
        coordinator: AgentCoordinator | None = None
        error: BaseException | None = None
        save: Future[None] | None = None
        with self.cancellation.on_cancel(cancellation.cancel):
            try:
                if startup_error is not None:
                    raise startup_error
                cancellation.check()
                chat_agent = create_chat_agent(
                    self.setup, self.user, index, cancellation, auto_filters
                )
                coordinator = create_chat_agent_coordinator(
                    chat_agent.agent,
                    message_id=self.setup.responses[index].message_id,
                    previous_run_id=self.setup.previous_run_id,
                    chat_session_id=self.setup.chat_session_id,
                    persist_content=record_mode_persists_content(
                        self.setup.incognito_record_mode
                    ),
                    llm=self.setup.responses[index].llm,
                    tools=chat_agent.tools,
                    user_identity=self.setup.user_identity,
                )
                cancellation.check()
                research = (
                    len(self.setup.responses) == 1
                    and self.setup.new_msg_req.deep_research
                )
                with trace(
                    "run_deep_research" if research else "chat",
                    group_id=str(self.setup.chat_session_id),
                    metadata=ChatTraceMetadata(
                        chat_session_id=str(self.setup.chat_session_id),
                        user_id=self.setup.user_identity.user_id,
                    ).model_dump(),
                ):
                    run = chat_agent.agent.start(
                        messages=self.setup.input_messages,
                        max_steps=chat_agent.max_steps,
                        cancellation=cancellation,
                        coordinator=coordinator,
                        on_event=ResponsePresenter(
                            emitter,
                            coordinator,
                            tool_ids={tool.name: tool.id for tool in chat_agent.tools},
                        ).consume,
                    )
                    run.result(timeout=CHAT_RESPONSE_WAIT_TIMEOUT_S)
            except BaseException as failure:
                error = failure
                if run is not None and run.status == RunStatus.RUNNING:
                    if isinstance(failure, TimeoutError):
                        logger.error(
                            "Response %s exceeded its execution wait bound", run.id
                        )
                    run.cancel()
                    try:
                        run.result(timeout=_PERSISTENCE_WAIT_SECONDS)
                    except TimeoutError:
                        logger.error(
                            "Response %s did not settle after cancellation", run.id
                        )
                    except AgentCancelled:
                        logger.debug("Response cancelled")
                    except Exception:
                        logger.exception("Response failed during cancellation")
            try:
                snapshot = self._project_response(
                    index, run, chat_agent, coordinator, error
                )
                if error is not None and not isinstance(error, AgentCancelled):
                    failure = (
                        error
                        if isinstance(error, Exception)
                        else RuntimeError("Agent task failed")
                    )
                    packet = chat_error(failure, self.setup.responses[index].llm, index)
                    self.delivery.publish(packet)
                    snapshot = snapshot.model_copy(update={"error": packet.error})
                save = start_thread_future(
                    lambda: save_chat_response(
                        message_id=self.setup.responses[index].message_id,
                        response=snapshot,
                    ),
                    name="chat-storage",
                )
                self._save_response(index, response_future, snapshot, save)
            except Exception as failure:
                logger.exception("Failed to finalize response for model %d", index)
                response_future.set_exception(failure)
                self.delivery.publish(
                    StreamingError(
                        error=PERSISTENCE_ERROR_MESSAGES[PersistenceStatus.FAILED],
                        error_code="RESPONSE_SAVE_ERROR",
                        is_retryable=True,
                        details={"model_index": index},
                    )
                )
            finally:
                self._retain_resources(index, run, save)
                self._changed.set()

    def _save_response(
        self,
        index: int,
        response_future: Future[ChatResponseOutcome],
        snapshot: ChatResponseSnapshot,
        save: Future[None],
    ) -> None:
        status = PersistenceStatus.SAVED
        done, _ = wait({save}, timeout=_PERSISTENCE_WAIT_SECONDS)
        if done:
            try:
                save.result()
            except Exception:
                logger.exception("Failed to save response for model %d", index)
                status = PersistenceStatus.FAILED
        else:
            logger.error(
                "Response persistence exceeded its wait bound for model %d", index
            )
            status = PersistenceStatus.UNCONFIRMED
            save.add_done_callback(_log_late_save)
        response_future.set_result(
            ChatResponseOutcome(response=snapshot, persistence_status=status)
        )
        if message := PERSISTENCE_ERROR_MESSAGES.get(status):
            self.delivery.publish(
                StreamingError(
                    error=message,
                    error_code="RESPONSE_SAVE_ERROR",
                    is_retryable=True,
                    details={"model_index": index},
                )
            )

    def _project_response(
        self,
        index: int,
        run: Run | None,
        chat_agent: ChatAgent | DeepResearchAgent | None,
        coordinator: AgentCoordinator | None,
        error: BaseException | None,
    ) -> ChatResponseSnapshot:
        if run is not None and chat_agent is not None:
            tool_ids = {tool.name: tool.id for tool in chat_agent.tools}
            if isinstance(chat_agent, DeepResearchAgent):
                if self.setup.research_tool_id is None:
                    raise ValueError("Deep research tool configuration is missing")
                tool_ids[RESEARCH_AGENT_TOOL_NAME] = self.setup.research_tool_id
            snapshot = project_response(
                run.snapshot(),
                response_id=self.setup.responses[index].message_id,
                tool_ids=tool_ids,
                initial_citations=chat_agent.artifacts.initial_citations
                if isinstance(chat_agent, ChatAgent)
                else {},
                registrations=coordinator.registrations() if coordinator else (),
            ).model_copy(update={"delivery_failed": run.delivery_failed})
        else:
            snapshot = ChatResponseSnapshot(
                answer=None,
                reasoning=None,
                request_params=None,
                citation_to_doc={},
                tool_calls=[],
                is_clarification=False,
                all_search_docs={},
                pre_answer_processing_time=None,
                response=None,
                cancelled=isinstance(error, AgentCancelled),
            )
        return snapshot

    def _poll_control(self) -> bool:
        now = time.monotonic()
        if (
            not self.cancellation.cancelled
            and now - self._last_stop_check >= _CANCEL_POLL_INTERVAL_S
        ):
            self._last_stop_check = now
            if is_stop_requested(
                self.setup.chat_session_id,
                self.setup.cache,
                processing_key=self.setup.processing_key,
            ):
                self._stopped_by_user = True
                self.cancellation.cancel()
        if now - self._last_refresh >= PROCESSING_REFRESH_INTERVAL_S:
            self._last_refresh = now
            try:
                set_processing_status(
                    chat_session_id=self.setup.chat_session_id,
                    cache=self.setup.cache,
                    value=True,
                    processing_key=self.setup.processing_key,
                )
            except Exception:
                self.cancellation.cancel()
                logger.exception("Failed to refresh chat processing status")
        return self.cancellation.cancelled

    def _finish_delivery(self) -> None:
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
