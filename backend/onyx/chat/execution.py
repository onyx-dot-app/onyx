"""Run chat turns independently of browser connections."""

import threading
import time
from concurrent.futures import Future, wait
from contextlib import ExitStack

from onyx.agents.runtime import Run
from onyx.cache.interface import CacheLockLostError
from onyx.chat.chat_processing_checker import (
    PROCESSING_REFRESH_INTERVAL_S,
)
from onyx.chat.emitter import Emitter
from onyx.chat.errors import chat_error
from onyx.chat.history_store import get_chat_history_store
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
from onyx.server.query_and_chat.placement import Placement
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
    try:
        turn = ChatTurnExecution(setup, user, response_future, stream_buffer)
    except BaseException:
        setup.admission.release()
        raise
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
        self._stores: list[ChatRunStore] = []
        self.cancellation = CancellationSignal()
        self.finished: Future[None] = Future()
        self._response_future = response_future
        self._response_workers: dict[Future[Run | None], ChatResponsePersistence] = {}
        self._lock = threading.Lock()
        self._completion_changed = threading.Event()
        self.delivery.finished.add_done_callback(
            lambda _future: self._completion_changed.set()
        )
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
        self.setup.admission.publish(self.setup.stream_id)

    def reject(self, error: Exception) -> None:
        self.cancellation.cancel()
        if self._response_future is not None:
            self._response_future.set_exception(error)

        def clear_status() -> None:
            try:
                self._clear_processing_status()
            finally:
                self.finished.set_result(None)

        def delivery_finished(_future: Future[None]) -> None:
            try:
                start_thread_future(clear_status, name="chat-status-cleanup")
            except Exception:
                logger.exception(
                    "Rejected chat processing status cleanup could not start"
                )
                clear_status()

        # No control thread exists to observe cleanup for a rejected turn.
        try:
            self.delivery.finish()
        finally:
            self.delivery.finished.add_done_callback(delivery_finished)

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
        for index, response in enumerate(self.setup.responses):
            persistence = ChatResponsePersistence(
                history_store=get_chat_history_store(
                    message_id=response.message_id,
                    chat_session_id=self.setup.chat_session_id,
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
            emitter = Emitter(self._publish, persistence.model_index)
            try:
                worker = start_thread_future(
                    lambda persistence=persistence, emitter=emitter: self._run_response(
                        persistence,
                        emitter,
                        startup_error=startup_error,
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
        self._wait_for_completion()

    def _wait_for_completion(self) -> None:
        deadline = time.monotonic() + CHAT_RESPONSE_WAIT_TIMEOUT_S
        timed_out = False
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
                logger.exception("Chat response polling failed; draining active work")
            if not timed_out and time.monotonic() >= deadline:
                timed_out = True
                logger.error("Chat turn exceeded its response wait bound")
                self.cancellation.cancel()
            with self._lock:
                stores = tuple(self._stores)
            if not self._response_workers and not any(
                store.has_owned_work for store in stores
            ):
                if not self.delivery.is_closing:
                    if self._stopped_by_user:
                        self.delivery.publish(
                            Packet(
                                placement=Placement(turn_index=0),
                                obj=OverallStop(stop_reason="user_cancelled"),
                            )
                        )
                    self.delivery.finish()
                if self.delivery.finished.done() and self._clear_processing_status():
                    self.finished.set_result(None)
                    return
            self._completion_changed.wait(_CANCEL_POLL_INTERVAL_S)

    def _register_store(self, store: ChatRunStore) -> None:
        with self._lock:
            self._stores.append(store)

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
                failed = (
                    persistence.outcome.done()
                    and persistence.outcome.exception() is not None
                )
                if run is not None:
                    if not failed:
                        coordinator = persistence.coordinator
                        if coordinator is None:
                            raise RuntimeError("Chat response run has no coordinator")
                        completion = coordinator.completion(run.id)
                        if not completion.done():
                            continue
                        if (
                            completion.exception() is not None
                            and not persistence.outcome.done()
                        ):
                            persistence.report_save_failure(run)
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
            del self._response_workers[worker]

    def _clear_processing_status(self) -> bool:
        try:
            self.setup.admission.release()
            return True
        except Exception:
            logger.exception("Failed to clear chat processing status; will retry")
            return False

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
        links.enter_context(self.cancellation.on_cancel(cancellation.cancel))
        try:
            if startup_error is not None:
                raise startup_error
            cancellation.check()
            chat_agent = create_chat_agent(
                self.setup, self.user, index, cancellation, self._auto_filters
            )
            persistence.tool_ids = {
                tool.name: tool.id for tool in chat_agent.application_tools
            }
            if isinstance(chat_agent, DeepResearchAgent):
                if self.setup.research_tool_id is None:
                    raise ValueError("Deep research tool configuration is missing")
                persistence.tool_ids[RESEARCH_AGENT_TOOL_NAME] = (
                    self.setup.research_tool_id
                )
            else:
                persistence.initial_citations = dict(chat_agent.initial_citations)
            coordinator = create_chat_agent_coordinator(
                chat_agent,
                message_id=self.setup.responses[index].message_id,
                previous_run_id=self.setup.previous_run_id,
                chat_session_id=self.setup.chat_session_id,
                persist_content=record_mode_persists_content(
                    self.setup.incognito_record_mode
                ),
                llm=self.setup.responses[index].llm,
                tools=chat_agent.application_tools,
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
                run = chat_agent.start(
                    background=False,
                    messages=self.setup.input_messages,
                    max_steps=chat_agent.max_steps,
                    cancellation=cancellation,
                    coordinator=coordinator,
                    event_dispatcher=self.delivery.events,
                    on_event=ResponsePresenter(
                        emitter,
                        tool_ids={
                            tool.name: tool.id for tool in chat_agent.application_tools
                        },
                    ).consume,
                )

            coordinator.completion(run.id).add_done_callback(
                lambda _future: links.close()
            )
            coordinator.completion(run.id).add_done_callback(
                lambda _future: self._completion_changed.set()
            )
            run.add_idle_callback(self._completion_changed.set)
            return run
        except BaseException as failure:
            try:
                persistence.save_failure(failure)
            except Exception:
                logger.exception(
                    "Response startup finalization failed for model %d", index
                )
            finally:
                links.close()
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
        self._poll_stream_status()

    def _poll_stream_status(self) -> None:
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
