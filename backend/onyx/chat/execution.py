"""Run chat turns independently of browser connections."""

import threading
import time
from concurrent.futures import Future, wait
from contextlib import ExitStack

from onyx.agents.coordination import AgentCoordinator
from onyx.agents.models import RunState
from onyx.agents.runtime import Run
from onyx.chat.agent import ChatAgent
from onyx.chat.chat_processing_checker import (
    PROCESSING_REFRESH_INTERVAL_S,
    set_processing_status,
)
from onyx.chat.emitter import Emitter
from onyx.chat.errors import chat_error
from onyx.chat.models import (
    ChatResponseOutcome,
    ChatTurnSetup,
    StreamingError,
)
from onyx.chat.persistence import ChatResponsePersistence
from onyx.chat.prepare import create_chat_agent
from onyx.chat.presentation import ResponsePresenter
from onyx.chat.run_store import ChatRunStore
from onyx.chat.stop_signal_checker import clear_stop, is_stop_requested
from onyx.chat.stream_buffer import ChatDelivery, ChatStream, StreamBufferWriter
from onyx.chat.subagents import create_chat_agent_coordinator
from onyx.configs.chat_configs import (
    CHAT_RESPONSE_WAIT_TIMEOUT_S,
)
from onyx.db.enums import record_mode_persists_content
from onyx.db.models import User
from onyx.deep_research.agent import DeepResearchAgent
from onyx.deep_research.tool_definitions import RESEARCH_AGENT_TOOL_NAME
from onyx.error_handling.exceptions import OnyxError
from onyx.llm.cancellation import CancellationSignal
from onyx.server.query_and_chat.streaming_models import OverallStop, Packet
from onyx.server.settings.store import load_settings
from onyx.tracing.framework.create import ChatTraceMetadata, trace
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import start_thread_future

logger = setup_logger()
_CANCEL_POLL_INTERVAL_S = 0.25
_CHAT_SHUTDOWN_WAIT_SECONDS = 30.0


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
        _, unfinished = wait(pending, timeout=_CHAT_SHUTDOWN_WAIT_SECONDS)
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
        self.events = self.delivery.events
        self._stores: list[ChatRunStore] = []
        self._stream_status: Future[None] | None = None
        self._persistence: dict[int, ChatResponsePersistence] = {}
        self._delivery_closed = False
        self._completion_reported = False
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
            stream_id=self.setup.stream_id,
        )
        set_processing_status(
            chat_session_id=self.setup.chat_session_id,
            cache=self.setup.cache,
            value=True,
            stream_id=self.setup.stream_id,
        )

    def reject(self, error: Exception) -> None:
        for index, response_future in enumerate(self._response_futures):
            response_future.set_exception(error)
            self._finish_response(index)
        self._close_delivery()
        self._maybe_finish()

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
        for index in range(len(self._response_futures)):
            emitter = Emitter(
                self._publish, self.setup.responses[index].message_id, index
            )
            try:
                start_thread_future(
                    lambda index=index, emitter=emitter: self._run_response(
                        index,
                        emitter,
                        self._auto_filters,
                        startup_error=startup_error,
                    ),
                    name="chat-response",
                )
            except Exception as error:
                self._run_response(
                    index,
                    emitter,
                    self._auto_filters,
                    startup_error=error,
                )
        deadline = time.monotonic() + CHAT_RESPONSE_WAIT_TIMEOUT_S
        timed_out = False
        try:
            while True:
                self._poll_control()
                with self._lock:
                    writers = tuple(self._persistence.values())
                for writer in writers:
                    writer.expire_save()
                with self._lock:
                    drained = len(self._execution_drained) == len(
                        self._response_futures
                    )
                    pending = bool(self._unfinished)
                    save_overdue = any(writer.is_save_overdue for writer in writers)
                    stores = tuple(self._stores)
                if (
                    not self._delivery_closed
                    and not timed_out
                    and time.monotonic() >= deadline
                ):
                    timed_out = True
                    logger.error("Chat turn exceeded its response wait bound")
                    self.cancellation.cancel()
                responses_done = all(future.done() for future in self._response_futures)
                if not self._delivery_closed and (
                    (
                        responses_done
                        and (drained or self.cancellation.cancelled or save_overdue)
                    )
                    or timed_out
                ):
                    if self._stopped_by_user:
                        self.delivery.publish(
                            Packet(obj=OverallStop(stop_reason="user_cancelled"))
                        )
                    self._close_delivery()
                if not pending and not any(store.has_owned_work for store in stores):
                    break
                self._changed.wait(timeout=_CANCEL_POLL_INTERVAL_S)
                self._changed.clear()
        except Exception:
            self.cancellation.cancel()
            logger.exception("Chat turn control failed")
        finally:
            self._close_delivery()
            self._maybe_finish()

    def _register_store(self, store: ChatRunStore) -> None:
        with self._lock:
            self._stores.append(store)
        self._changed.set()

    def _maybe_finish(self) -> None:
        with self._lock:
            finished = not self._unfinished and self._delivery_finished
            stores = tuple(self._stores)
        if finished and not any(store.has_owned_work for store in stores):
            with self._lock:
                if self._completion_reported:
                    return
                self._completion_reported = True
            self.finished.set_result(None)

    def _close_delivery(self) -> None:
        if self._delivery_closed:
            return
        self._delivery_closed = True

        def clear_status() -> None:
            try:
                if self._stream_status is not None:
                    self._stream_status.result()
                set_processing_status(
                    chat_session_id=self.setup.chat_session_id,
                    cache=self.setup.cache,
                    value=False,
                )
            except Exception:
                logger.exception("Failed to clear chat processing status")
            finally:
                with self._lock:
                    self._delivery_finished = True
                self._changed.set()
                self._maybe_finish()

        def drained(_future: Future[None]) -> None:
            start_thread_future(clear_status, name="chat-status-cleanup")

        try:
            self.delivery.finish()
        finally:
            self.delivery.finished.add_done_callback(drained)

    def _finish_response(self, index: int) -> None:
        with self._lock:
            self._unfinished.remove(index)
        self._changed.set()

    def _retain_resources(self, index: int, run: Run | None) -> None:
        def drained() -> None:
            if run is not None and run.delivery_failed:
                self.delivery.report_gap()
            with self._lock:
                self._execution_drained.add(index)
            self._finish_response(index)

        if run is None:
            drained()
        else:
            run.add_idle_callback(drained)

    def _run_response(
        self,
        index: int,
        emitter: Emitter,
        auto_filters: bool,
        *,
        startup_error: BaseException | None = None,
    ) -> None:
        cancellation = CancellationSignal()
        links = ExitStack()
        links.enter_context(self.cancellation.on_cancel(cancellation.cancel))
        chat_agent: ChatAgent | DeepResearchAgent | None = None
        coordinator: AgentCoordinator | None = None
        persistence = ChatResponsePersistence(
            message_id=self.setup.responses[index].message_id,
            model_index=index,
            llm=self.setup.responses[index].llm,
            delivery=self.delivery,
            outcome=self._response_futures[index],
        )
        with self._lock:
            self._persistence[index] = persistence

        try:
            if startup_error is not None:
                raise startup_error
            cancellation.check()
            chat_agent = create_chat_agent(
                self.setup, self.user, index, cancellation, auto_filters
            )
            persistence.tool_ids = {tool.name: tool.id for tool in chat_agent.tools}
            if isinstance(chat_agent, DeepResearchAgent):
                if self.setup.research_tool_id is None:
                    raise ValueError("Deep research tool configuration is missing")
                persistence.tool_ids[RESEARCH_AGENT_TOOL_NAME] = (
                    self.setup.research_tool_id
                )
            else:
                persistence.initial_citations = dict(
                    chat_agent.artifacts.initial_citations
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
                register_store=self._register_store,
                response_store=persistence,
            )
            persistence.coordinator = coordinator
            cancellation.check()
            research = (
                len(self.setup.responses) == 1 and self.setup.new_msg_req.deep_research
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
                    background=False,
                    messages=self.setup.input_messages,
                    max_steps=chat_agent.max_steps,
                    cancellation=cancellation,
                    coordinator=coordinator,
                    event_dispatcher=self.events,
                    on_event=ResponsePresenter(
                        emitter,
                        coordinator,
                        tool_ids={tool.name: tool.id for tool in chat_agent.tools},
                    ).consume,
                )

            def finished(future: Future[RunState]) -> None:
                if future.exception() is not None:
                    persistence.report_save_failure(run)
                links.close()
                self._retain_resources(index, run)

            coordinator.completion(run.id).add_done_callback(finished)
        except BaseException as failure:
            try:
                persistence.save_failure(failure)
            except Exception:
                logger.exception(
                    "Response startup finalization failed for model %d", index
                )
            finally:
                links.close()
                self._retain_resources(index, None)

    def _poll_control(self) -> bool:
        with self._lock:
            stores = tuple(self._stores)
        for store in stores:
            store.poll_control()
        if not self._delivery_closed and (
            self._stream_status is None or self._stream_status.done()
        ):
            self._stream_status = start_thread_future(
                self._poll_stream_status, name="chat-stream-status"
            )
        return self.cancellation.cancelled

    def _poll_stream_status(self) -> None:
        # Ordinary cache waits must not delay ownership deadlines.
        now = time.monotonic()
        if (
            not self.cancellation.cancelled
            and now - self._last_stop_check >= _CANCEL_POLL_INTERVAL_S
        ):
            self._last_stop_check = now
            try:
                if is_stop_requested(
                    self.setup.chat_session_id,
                    self.setup.cache,
                    stream_id=self.setup.stream_id,
                ):
                    self._stopped_by_user = True
                    self.cancellation.cancel()
            except Exception:
                logger.exception("Failed to read chat Stop request; will retry")
        if now - self._last_refresh >= PROCESSING_REFRESH_INTERVAL_S:
            self._last_refresh = now
            try:
                set_processing_status(
                    chat_session_id=self.setup.chat_session_id,
                    cache=self.setup.cache,
                    value=True,
                    stream_id=self.setup.stream_id,
                )
            except Exception:
                logger.exception("Failed to refresh chat processing status; will retry")
