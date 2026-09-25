"""Project and save one chat response, with an observable persistence outcome."""

import threading
import time
from concurrent.futures import Future

from onyx.agents.agent_coordination import AgentCoordinator, RunStore
from onyx.agents.models import RunState
from onyx.agents.runtime import Run, validate_run_completion
from onyx.chat.citation_processor import CitationMapping
from onyx.chat.errors import chat_error
from onyx.chat.history_store import ChatHistoryStore
from onyx.chat.models import (
    PERSISTENCE_ERROR_MESSAGES,
    ChatResponseOutcome,
    ChatResponseSnapshot,
    PendingChatResponseSave,
    PersistenceStatus,
    StreamingError,
)
from onyx.chat.presentation import project_response
from onyx.chat.stream_buffer import ChatDelivery
from onyx.llm.cancellation import AgentCancelled
from onyx.llm.interfaces import LLM
from onyx.utils.logger import setup_logger

logger = setup_logger()
PERSISTENCE_WAIT_SECONDS = 30.0


class ChatResponsePersistence(RunStore):
    """Save root output and report storage failures independently of model failures."""

    def __init__(
        self,
        *,
        history_store: ChatHistoryStore,
        model_index: int,
        llm: LLM,
        delivery: ChatDelivery,
        outcome: Future[ChatResponseOutcome],
    ) -> None:
        self.message_id = history_store.message_id
        self.history_store = history_store
        self.model_index = model_index
        self.llm = llm
        self.delivery = delivery
        self.outcome = outcome
        self.tool_ids: dict[str, int] = {}
        self.initial_citations: CitationMapping = {}
        self.coordinator: AgentCoordinator | None = None
        self._lock = threading.Lock()
        self._pending_save: PendingChatResponseSave | None = None

    def save(self, run: Run) -> None:
        snapshot = run.snapshot()
        if snapshot.parent_run_id is not None:
            return
        error: BaseException | None = None
        try:
            validate_run_completion(snapshot)
        except BaseException as failure:
            error = failure
        self._save(snapshot, error, delivery_failed=run.delivery_failed)

    def save_failure(self, error: BaseException) -> None:
        self._save(None, error)

    def report_save_failure(self, run: Run) -> None:
        """Report a rejected save without attempting another database write."""
        if self.outcome.done():
            return
        try:
            response = self._project(
                run.snapshot(), None, delivery_failed=run.delivery_failed
            )
        except Exception as error:
            logger.exception("Failed to project rejected response save")
            with self._lock:
                if not self.outcome.done():
                    self.outcome.set_exception(error)
            return
        with self._lock:
            self._report(
                ChatResponseOutcome(
                    response=response,
                    persistence_status=PersistenceStatus.FAILED,
                )
            )

    @property
    def is_save_overdue(self) -> bool:
        with self._lock:
            return (
                self._pending_save is not None
                and self._pending_save.deadline <= time.monotonic()
            )

    def expire_save(self) -> None:
        with self._lock:
            pending = self._pending_save
            if (
                pending is None
                or pending.deadline > time.monotonic()
                or self.outcome.done()
            ):
                return
            logger.error(
                "Response persistence exceeded its wait bound for model %d",
                self.model_index,
            )
            self._report(
                ChatResponseOutcome(
                    response=pending.response,
                    persistence_status=PersistenceStatus.UNCONFIRMED,
                )
            )

    def _report(self, outcome: ChatResponseOutcome) -> None:
        """Publish once while the caller holds the persistence lock."""
        if self.outcome.done():
            return
        self.outcome.set_result(outcome)
        if message := PERSISTENCE_ERROR_MESSAGES.get(outcome.persistence_status):
            self.delivery.publish(
                StreamingError(
                    error=message,
                    error_code="RESPONSE_SAVE_ERROR",
                    is_retryable=True,
                    details={"model_index": self.model_index},
                )
            )

    def _save(
        self,
        snapshot: RunState | None,
        error: BaseException | None,
        *,
        delivery_failed: bool = False,
    ) -> None:
        try:
            response = self._project(snapshot, error, delivery_failed=delivery_failed)
            if error is not None and not isinstance(error, AgentCancelled):
                failure = (
                    error
                    if isinstance(error, Exception)
                    else RuntimeError("Agent task failed")
                )
                packet = chat_error(failure, self.llm, self.model_index)
                self.delivery.publish(packet)
                response = response.model_copy(update={"error": packet.error})
            with self._lock:
                self._pending_save = PendingChatResponseSave(
                    response=response,
                    deadline=time.monotonic() + PERSISTENCE_WAIT_SECONDS,
                )
            try:
                self.history_store.save_response(response)
            except Exception:
                with self._lock:
                    self._report(
                        ChatResponseOutcome(
                            response=response,
                            persistence_status=PersistenceStatus.FAILED,
                        )
                    )
                raise
            else:
                with self._lock:
                    self._report(
                        ChatResponseOutcome(
                            response=response,
                            persistence_status=PersistenceStatus.SAVED,
                        )
                    )
            finally:
                with self._lock:
                    self._pending_save = None
        except Exception as failure:
            with self._lock:
                if not self.outcome.done():
                    self.outcome.set_exception(failure)
                    self.delivery.publish(
                        StreamingError(
                            error=PERSISTENCE_ERROR_MESSAGES[PersistenceStatus.FAILED],
                            error_code="RESPONSE_SAVE_ERROR",
                            is_retryable=True,
                            details={"model_index": self.model_index},
                        )
                    )
            raise

    def _project(
        self,
        snapshot: RunState | None,
        error: BaseException | None,
        *,
        delivery_failed: bool = False,
    ) -> ChatResponseSnapshot:
        if snapshot is None:
            return ChatResponseSnapshot(
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
        return project_response(
            snapshot,
            response_id=self.message_id,
            tool_ids=self.tool_ids,
            initial_citations=self.initial_citations,
            registrations=self.coordinator.registrations() if self.coordinator else (),
        ).model_copy(update={"delivery_failed": delivery_failed})
