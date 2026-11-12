"""Live response ownership and explicit, safe checkpoint transfer across API pods."""

import json
import threading
import time
from collections.abc import Callable, Collection, Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from redis.exceptions import RedisError
from sqlalchemy.exc import OperationalError
from sqlalchemy.exc import TimeoutError as DatabaseTimeoutError
from sqlalchemy.orm import Session

from onyx.agents.agent_coordination import (
    AgentCoordinator,
    AgentDirectory,
    RunOwnership,
    RunStore,
)
from onyx.agents.concurrency import OPERATION_TIMEOUT_SECONDS
from onyx.agents.models import (
    AgentCompletion,
    AgentInfo,
    AgentMessageReceipt,
    AgentMessageRequest,
    AgentState,
    ExecutionCheckpoint,
    InputMessageMetadata,
    InputSource,
    RunState,
    RunStatus,
    StepRecord,
)
from onyx.agents.runtime import Agent, AgentBusy, Run, RunNotTransferable
from onyx.cache.factory import get_cache_backend
from onyx.cache.interface import CacheBackend
from onyx.chat.checkpoint import deserialize_checkpoint, serialize_checkpoint
from onyx.chat.models import (
    ChatBranch,
    ChatInbox,
    CheckpointBinding,
    ResponseOwner,
    ResponseRecord,
    ResponseStatus,
    SavedAgentContext,
    SavedResponse,
)
from onyx.chat.presentation import project_response
from onyx.chat.response import response_record, response_snapshot
from onyx.chat.restoration import persist_checkpoint_files
from onyx.configs.constants import MessageType
from onyx.db.chat import get_selected_branch, session_ancestors
from onyx.db.chat_checkpoint import (
    check_checkpoint_owner__no_commit,
    claim_checkpoint__no_commit,
    interrupt_response__no_commit,
    publish_checkpoint__no_commit,
    release_checkpoint_claim__no_commit,
)
from onyx.db.chat_inputs import (
    agent_result_states,
    consume_inputs__no_commit,
    enqueue_message,
    fail_inbox_start__no_commit,
    fail_response_start__no_commit,
    has_pending_sends,
    read_chat_inbox,
    read_run_inputs,
    reserve_inbox_run__no_commit,
    withdraw_agent_result__no_commit,
)
from onyx.db.chat_response import (
    abort_response_start__no_commit,
    find_response__no_commit,
    finish_checkpoint__no_commit,
    read_response__no_commit,
    read_response_status__no_commit,
    reserve_child_response__no_commit,
    save_chat_turn,
    save_response_record__no_commit,
)
from onyx.db.chat_subagents import (
    load_agent_history,
    load_session_agent_metadata,
    lookup_session_agent,
    read_agent_completions,
)
from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.llm.models import Message, UserMessage
from onyx.tools.constants import SPAWN_AGENT_TOOL_NAME
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR

logger = setup_logger()
LEASE_CACHE_TIMEOUT_S = 1.0
OWNER_TTL_SECONDS = 60
OWNER_REFRESH_SECONDS = 10
OWNER_RETRY_SECONDS = 1.0
OWNER_EXPIRY_MARGIN_SECONDS = 5.0
OWNER_LOCK_SECONDS = 30
OWNER_LOCK_WAIT_SECONDS = 10
STOP_TTL_SECONDS = 600
INPUT_POLL_SECONDS = 1.0
MAX_AGENT_COMPLETIONS_PER_STEP = 8
RESPONSE_OWNER_KEY_PREFIX = "chat_response_owner:"
# Start failures that a later poll retries; other failures end the inbox work.
_RETRYABLE_START_ERRORS = (
    OperationalError,
    DatabaseTimeoutError,
    RedisError,
    TimeoutError,
    AgentBusy,
)


def _owner_key(response_id: int) -> str:
    return f"{RESPONSE_OWNER_KEY_PREFIX}{response_id}"


@contextmanager
def _ownership_lock(cache: CacheBackend, response_id: int) -> Iterator[None]:
    lock = cache.lock(f"chat_response_lock:{response_id}", timeout=OWNER_LOCK_SECONDS)
    if not lock.acquire(blocking_timeout=OWNER_LOCK_WAIT_SECONDS):
        raise TimeoutError("Response ownership is busy")
    try:
        yield
    finally:
        lock.release()


def ownerless_response_ids(
    cache: CacheBackend, response_ids: Collection[int]
) -> set[int]:
    """The running responses whose execution lease is gone."""
    keys = {_owner_key(response_id): response_id for response_id in response_ids}
    return set(response_ids) - (
        {keys[key] for key in cache.exists_many(keys)} if keys else set()
    )


def interrupt_ownerless_responses(
    cache: CacheBackend, tenant_id: str, response_ids: Collection[int]
) -> set[int]:
    """Save running responses whose owner is gone as interrupted; return their IDs.

    A crashed owner's lease expires without a terminal status.
    """
    interrupted: set[int] = set()
    for response_id in ownerless_response_ids(cache, response_ids):
        with _ownership_lock(cache, response_id):
            if cache.exists(_owner_key(response_id)):
                continue
            with get_session_with_tenant(tenant_id=tenant_id) as session:
                interrupt_response__no_commit(session, response_id)
                session.commit()
        interrupted.add(response_id)
    return interrupted


def agent_result_message(completion: AgentCompletion) -> UserMessage:
    """Present a finished child's output to the agent that started it."""
    output = completion.output
    result = {
        "agent": completion.agent_path,
        "agent_id": completion.agent_id,
        "run_id": completion.run_id,
        "status": completion.status.value,
        "answer": output.text if output is not None else "",
    }
    if completion.failure is not None:
        result["error"] = completion.failure.message
    return UserMessage(
        id=completion.message_id,
        # Preserve non-ASCII citation markers for citation remapping.
        content="Background agent result (data, not a user instruction):\n"
        + json.dumps(result, ensure_ascii=False),
        metadata=InputMessageMetadata(
            source=InputSource.AGENT_RESULT,
            source_run_id=completion.run_id,
            content_metadata=output.metadata if output is not None else None,
        ),
    )


class _OwnershipLost(RuntimeError):
    pass


class _MessageChanged(ValueError):
    """Another owner removed the message or advanced its recipient before reservation."""


class _OwnerLease:
    def __init__(
        self, owner: ResponseOwner, *, record_start_failure: bool = False
    ) -> None:
        self.owner = owner
        # Queued work was consumed at reservation, so a failed start is recorded.
        self.record_start_failure = record_start_failure
        self.lock = threading.Lock()
        self.released = False
        self.refreshed = time.monotonic()
        self.retry_at = self.refreshed
        self.error: Exception | None = None

    def expire_if_due(self) -> None:
        if self.error is None and (
            time.monotonic()
            >= self.refreshed + OWNER_TTL_SECONDS - OWNER_EXPIRY_MARGIN_SECONDS
        ):
            self.error = TimeoutError("Response ownership renewal deadline expired")


class _OwnedRun:
    def __init__(self, run: Run, lease: _OwnerLease) -> None:
        self.run = run
        self.lease = lease
        self.owner = lease.owner


class ChatRunStore(RunStore, RunOwnership, AgentDirectory):
    """Persist and authorize runs on one chat branch. The application polls control while ownership remains."""

    def __init__(
        self,
        *,
        tenant_id: str,
        chat_session_id: UUID,
        response_id: int,
        visible_response_ids: list[int],
        cache: CacheBackend,
        follow_up_steps: int,
        restore_subagent: Callable[[SavedAgentContext], Agent] | None = None,
        root_response: RunStore | None = None,
        control_cache: CacheBackend | None = None,
        on_child_released: Callable[[], None] | None = None,
        tool_labels: Mapping[str, str] | None = None,
    ) -> None:
        self.tenant_id = tenant_id
        # Saved child responses label their tool calls with these display names.
        self._tool_labels = dict(tool_labels or {})
        self.chat_session_id = chat_session_id
        self.response_id = response_id
        # Branch IDs stay newest first, as the branch queries order them.
        self._input_branch = ChatBranch(
            chat_session_id=chat_session_id,
            message_ids=list(dict.fromkeys([response_id, *visible_response_ids])),
        )
        self.visible_response_ids = set(self._input_branch.message_ids)
        self.cache = cache
        self.control_cache = control_cache or get_cache_backend(
            tenant_id=tenant_id, operation_timeout_s=LEASE_CACHE_TIMEOUT_S
        )
        self._root_response = root_response
        self._restore_subagent = restore_subagent
        self._on_child_released = on_child_released
        self._lock = threading.Lock()
        self._owned: dict[int, _OwnedRun] = {}
        self._leases: dict[int, _OwnerLease] = {}
        self._coordinator: AgentCoordinator | None = None
        self._build_agent: Callable[[ExecutionCheckpoint], Agent] | None = None
        self._pending_dispatch = False
        # Children still running on the branch can finish in another store. The
        # first poll scans, which also finds inbox work left by earlier turns.
        self._has_running_children = True
        self._next_input_poll = 0.0
        # Result follow-ups use the step limit of this store's chat agent.
        self._follow_up_steps = follow_up_steps

    def _follow_selected_branch(self, selected: ChatBranch) -> bool:
        """Follow the selected branch while it continues this store's response.

        Inbox work continues an agent's newest history, which a later turn can
        extend. Returns whether this store's response is on the selected branch.
        """
        if self.response_id not in selected.message_ids:
            return False
        with self._lock:
            self._input_branch = selected
            self.visible_response_ids = set(selected.message_ids)
        return True

    def _with_tenant[T](self, operation: Callable[[], T]) -> T:
        token = CURRENT_TENANT_ID_CONTEXTVAR.set(self.tenant_id)
        try:
            return operation()
        finally:
            CURRENT_TENANT_ID_CONTEXTVAR.reset(token)

    def _stop_key(self, response_id: int) -> str:
        return f"chat_response_stop:{response_id}"

    def _owner(self, response_id: int) -> ResponseOwner | None:
        value = self.cache.get(_owner_key(response_id))
        return ResponseOwner.model_validate_json(value) if value is not None else None

    def _require_owner(self, owned: _OwnedRun) -> None:
        if self._owner(int(owned.run.id)) != owned.owner:
            raise RuntimeError("Response ownership was lost")

    def _binding(self, response_id: int) -> CheckpointBinding:
        return CheckpointBinding(
            tenant_id=self.tenant_id,
            response_id=str(response_id),
        )

    def bind(
        self,
        coordinator: AgentCoordinator,
        *,
        build_agent: Callable[[ExecutionCheckpoint], Agent],
    ) -> AgentCoordinator:
        if self._coordinator is not None:
            raise ValueError("Response store is already bound")
        self._build_agent = build_agent
        self._coordinator = coordinator.view(directory=self, store=self, ownership=self)
        return self._coordinator

    def _authorize(
        self, saved: ResponseStatus | None, parent_id: str | None
    ) -> ResponseStatus:
        if saved is None:
            raise LookupError("Response is unavailable")
        if (
            saved.root_session_id != self.chat_session_id
            or saved.root_message_id not in self.visible_response_ids
        ):
            raise ValueError("Response is unavailable on this branch")
        if parent_id is not None:
            allowed = (
                parent_id in saved.ancestor_agent_ids
                if parent_id
                else not saved.ancestor_agent_ids
            )
            if not allowed:
                raise ValueError("Response is unavailable to this parent")
        return saved

    def _load_status(
        self, response_id: int, parent_id: str | None = None
    ) -> ResponseStatus:
        with get_session_with_tenant(tenant_id=self.tenant_id) as session:
            saved = self._authorize(
                read_response_status__no_commit(session, response_id), parent_id
            )
        if saved.status == RunStatus.RUNNING and interrupt_ownerless_responses(
            self.cache, self.tenant_id, [saved.message_id]
        ):
            with get_session_with_tenant(tenant_id=self.tenant_id) as session:
                current = read_response_status__no_commit(session, saved.message_id)
            if current is None:
                raise LookupError("Response was removed")
            saved = current
        return saved

    def _load(self, response_id: int, parent_id: str | None = None) -> SavedResponse:
        self._load_status(response_id, parent_id)
        with get_session_with_tenant(tenant_id=self.tenant_id) as session:
            saved = read_response__no_commit(session, response_id)
        if saved is None:
            raise LookupError("Response is unavailable")
        return saved

    def list_agents(self) -> list[AgentInfo]:
        return self._with_tenant(
            lambda: load_session_agent_metadata(
                self.response_id, branch=self._input_branch
            )
        )

    def lookup_agent(self, agent_id: str, parent_id: str) -> AgentInfo | None:
        return self._with_tenant(
            lambda: lookup_session_agent(self._input_branch, agent_id, parent_id)
        )

    def restore_agent(self, agent_id: str, parent_id: str) -> Agent:
        saved = self.lookup_agent(agent_id, parent_id)
        if saved is None:
            raise ValueError("Agent is not a visible child of this parent")
        if (
            saved.latest_run_id is not None
            and not self.read_run_status(saved.latest_run_id, parent_id).is_terminal
        ):
            raise ValueError("Response must finish before another run starts")
        restore_subagent = self._restore_subagent
        if restore_subagent is None:
            raise ValueError("Subagent restoration is unavailable")
        # Restoration must use the conversation's tenant, not the worker's context.
        return self._with_tenant(
            lambda: restore_subagent(load_agent_history(self._input_branch, saved.id))
        )

    def submit_message(self, request: AgentMessageRequest) -> AgentMessageReceipt:
        """Any agent in the visible tree can message any other agent, including the root."""
        with self._lock:
            parent = self._owned.get(int(request.parent_run_id))
        if parent is None or parent.run.agent_id != request.parent_id:
            raise ValueError("Message sender has no execution ownership")
        self._save_output(parent, parent.run.snapshot(include_children=False))
        with _ownership_lock(self.cache, int(request.parent_run_id)):
            self._require_owner(parent)
            with get_session_with_tenant(tenant_id=self.tenant_id) as session:
                self._follow_selected_branch(
                    get_selected_branch(session, self.chat_session_id)[1]
                )
                receipt = enqueue_message(
                    session, self._input_branch, request, parent.owner.root_message_id
                )
                session.commit()
        with self._lock:
            self._pending_dispatch = True
            self._next_input_poll = 0.0
        return receipt

    def _root_branch(self, run: Run) -> list[int] | None:
        """The root reads every agent message sent on its branch."""
        return (
            self._input_branch.message_ids
            if run.agent_id == str(self.chat_session_id)
            else None
        )

    def receive_inputs(self, run: Run) -> list[UserMessage]:
        """Read sent messages, then finished results of children this run's agent started."""
        with get_session_with_tenant(tenant_id=self.tenant_id) as session:
            messages, results = read_run_inputs(
                session,
                run.agent_id,
                run.id,
                self._root_branch(run),
                self._input_branch.message_ids,
            )
        completed = [
            result.response_id for result in results if result.status.is_terminal
        ]
        # The last step answers with every finished result; it has no later step.
        if not run.on_final_step:
            completed = completed[:MAX_AGENT_COMPLETIONS_PER_STEP]
        if not completed:
            return messages
        with get_session_with_tenant(tenant_id=self.tenant_id) as session:
            completions = read_agent_completions(session, completed)
        return [*messages, *map(agent_result_message, completions)]

    def accept_inputs(self, run: Run, step: StepRecord) -> bool:
        if not step.input_messages:
            return True
        snapshot = run.snapshot(include_children=False)
        snapshot.steps.append(step)
        response_id = int(run.id)
        with self._lock:
            owned = self._owned.get(response_id)
        if owned is None:
            raise ValueError("Response has no execution ownership")
        with _ownership_lock(self.cache, response_id):
            self._require_owner(owned)
            with get_session_with_tenant(tenant_id=self.tenant_id) as session:
                if not consume_inputs__no_commit(
                    session,
                    response_id,
                    step.input_messages,
                    self._input_branch.message_ids,
                    ownership_version=owned.owner.ownership_version,
                ):
                    return False
                save_response_record__no_commit(
                    session, owned.owner.root_message_id, self._record(snapshot)
                )
                session.commit()
                return True

    def has_unread_inputs(self, run: Run) -> bool:
        # A send that arrives after this check starts the recipient's next run.
        with get_session_with_tenant(tenant_id=self.tenant_id) as session:
            return has_pending_sends(
                session, run.agent_id, int(run.id), self._root_branch(run)
            )

    def _read_inbox(self) -> ChatInbox | None:
        """Read the inbox; None when this store's response left the selected branch."""
        with get_session_with_tenant(tenant_id=self.tenant_id) as session:
            inbox = read_chat_inbox(session, self.chat_session_id)
        return inbox if self._follow_selected_branch(inbox.branch) else None

    def _dispatch_messages(self) -> None:
        """Start idle children's queued messages and result follow-ups.

        Scans run after a notification and while children run on the branch,
        while this store's response stays selected. A failure here never stops
        the turn: transient errors retry at a later poll, and work that cannot
        start becomes a failed run.
        """
        coordinator = self._coordinator
        if coordinator is None:
            return
        with self._lock:
            if (
                not (self._pending_dispatch or self._has_running_children)
                or time.monotonic() < self._next_input_poll
            ):
                return
            # Consume this notification before scanning so new submissions remain pending.
            pending = self._pending_dispatch
            self._pending_dispatch = False
            self._next_input_poll = time.monotonic() + INPUT_POLL_SECONDS
        try:
            inbox = self._read_inbox()
            if inbox is not None and interrupt_ownerless_responses(
                self.cache, self.tenant_id, inbox.running_response_ids
            ):
                inbox = self._read_inbox()
            if inbox is None:
                with self._lock:
                    self._has_running_children = False
                return
            with get_session_with_tenant(tenant_id=self.tenant_id) as session:
                spawners = (
                    session_ancestors(
                        session, [UUID(work.agent_id) for work in inbox.child_work]
                    )
                    if inbox.child_work
                    else {}
                )
            # Poll again while messages wait for runs that still have an owner.
            waiting = len(
                ownerless_response_ids(self.control_cache, inbox.waiting_response_ids)
            ) < len(inbox.waiting_response_ids)
            with self._lock:
                # Starting one run per agent can leave more work for the next scan.
                self._pending_dispatch = (
                    self._pending_dispatch or bool(inbox.child_work) or waiting
                )
                self._has_running_children = any(
                    result.status == RunStatus.RUNNING for result in inbox.results
                )
            for work in inbox.child_work:
                # Stores of several turns on one branch scan the same inbox. This
                # lock keeps them from restoring one agent twice; the reservation's
                # row lock and previous-run check keep the start correct.
                lock = self.cache.lock(
                    f"chat_agent_dispatch:{work.agent_id}", timeout=OWNER_LOCK_SECONDS
                )
                if not lock.acquire(blocking_timeout=0):
                    continue
                try:
                    spawner_id = spawners[UUID(work.agent_id)].parent_id
                    if spawner_id is None:
                        raise ValueError("Inbox work cannot start the root")
                    # The agent restores through its spawner, whoever sent the work.
                    coordinator.start_message_run(
                        work.agent_id,
                        spawner_id=str(spawner_id),
                        messages=[work.message] if work.message is not None else [],
                        max_steps=work.max_steps or self._follow_up_steps,
                        deadline_at=datetime.now(timezone.utc)
                        + timedelta(seconds=work.total_timeout_s)
                        if work.total_timeout_s is not None
                        else None,
                        parent_run_id=work.parent_run_id,
                        parent_message_id=work.parent_message_id,
                        parent_tool_call_id=work.parent_tool_call_id,
                    )
                except _MessageChanged:
                    continue
                except _RETRYABLE_START_ERRORS:
                    raise
                except Exception:
                    logger.exception("Could not start agent inbox work")
                    with get_session_with_tenant(tenant_id=self.tenant_id) as session:
                        fail_inbox_start__no_commit(
                            session,
                            inbox.branch,
                            work.agent_id,
                            work.message.id if work.message is not None else None,
                        )
                        session.commit()
                finally:
                    lock.release()
        except _RETRYABLE_START_ERRORS:
            with self._lock:
                self._pending_dispatch |= pending
            logger.exception(
                "Could not dispatch agent inbox work; retrying on the next control poll"
            )
        except Exception:
            logger.exception("Could not dispatch agent inbox work")

    def delegated_runs(self, parent_id: str) -> dict[str, RunStatus]:
        with get_session_with_tenant(tenant_id=self.tenant_id) as session:
            results = agent_result_states(
                session, self._input_branch.message_ids, UUID(parent_id)
            )
        return {str(result.response_id): result.status for result in results}

    def read_run(self, run_id: str, parent_id: str) -> RunState | None:
        if not run_id.isdecimal():
            return None
        response_id = int(run_id)
        try:
            saved = self._load(response_id, parent_id)
        except LookupError:
            return None
        return response_snapshot(saved.response)

    def read_run_status(self, run_id: str, parent_id: str) -> RunStatus:
        if not run_id.isdecimal():
            raise LookupError("Response is unavailable")
        response_id = int(run_id)
        return self._load_status(response_id, parent_id).status

    def cancel_run(self, run_id: str, parent_id: str) -> None:
        if not run_id.isdecimal():
            raise LookupError("Response is unavailable")
        response_id = int(run_id)
        saved = self._load_status(response_id, parent_id)
        if saved.status.is_terminal:
            return
        self.cache.set(self._stop_key(saved.message_id), 1, ex=STOP_TTL_SECONDS)
        with _ownership_lock(self.cache, saved.message_id):
            if self._owner(saved.message_id) is None:
                with get_session_with_tenant(tenant_id=self.tenant_id) as session:
                    interrupt_response__no_commit(
                        session, saved.message_id, cancelled=True
                    )
                    session.commit()

    def withdraw_result(self, run_id: str, parent_id: str) -> None:
        """Withdraw before any status repair, which would make the run finished."""
        if not run_id.isdecimal():
            raise LookupError("Response is unavailable")
        with get_session_with_tenant(tenant_id=self.tenant_id) as session:
            self._authorize(
                read_response_status__no_commit(session, int(run_id)), parent_id
            )
            withdraw_agent_result__no_commit(session, int(run_id))
            session.commit()

    def _record(self, snapshot: RunState) -> ResponseRecord:
        registrations = self._coordinator.registrations() if self._coordinator else []
        return response_record(
            snapshot.model_copy(update={"child_runs": []}), registrations
        )

    def _save_output(self, owned: _OwnedRun, snapshot: RunState) -> None:
        response_id = int(owned.run.id)
        display = None
        if snapshot.parent_run_id is not None and snapshot.status.is_terminal:
            display = project_response(
                snapshot,
                tool_ids={
                    call.name: None
                    for step in snapshot.steps
                    for call in step.message.tool_calls
                },
                tool_labels=self._tool_labels,
                registrations=self._coordinator.registrations()
                if self._coordinator
                else (),
            )
        record = display.response if display is not None else self._record(snapshot)
        if record is None:
            raise ValueError("Response projection has no accepted content")
        with _ownership_lock(self.cache, response_id):
            self._require_owner(owned)
            with get_session_with_tenant(tenant_id=self.tenant_id) as session:
                check_checkpoint_owner__no_commit(
                    session, response_id, owned.owner.ownership_version
                )
                if snapshot.status.is_terminal:
                    finish_checkpoint__no_commit(session, response_id)
                if display is None:
                    save_response_record__no_commit(
                        session, owned.owner.root_message_id, record
                    )
                    session.commit()
                    return
                response = find_response__no_commit(session, response_id)
                if response is None:
                    raise ValueError("Child response is unavailable")
                save_chat_turn(
                    message_text=display.answer or "",
                    reasoning_tokens=display.reasoning,
                    tool_calls=display.tool_calls,
                    citation_to_doc=display.citation_to_doc,
                    all_search_docs=display.all_search_docs,
                    db_session=session,
                    assistant_message=response,
                    request_params=display.request_params,
                    response_record=record,
                    presentation=display.presentation,
                )

    def _claim_reservation(
        self,
        session: Session,
        response_id: int,
        root_id: int,
        *,
        record_start_failure: bool,
    ) -> None:
        """Commit a reserved running response and take its lease together.

        Another reservation for the same agent sees the running response, and
        repair sees its owner. A failed claim undoes or fails the reservation.
        """
        lease = _OwnerLease(
            ResponseOwner(token=uuid4(), root_message_id=root_id),
            record_start_failure=record_start_failure,
        )
        with self._lock:
            self._leases[response_id] = lease
        try:
            with _ownership_lock(self.cache, response_id):
                session.commit()
                self.cache.set(
                    _owner_key(response_id),
                    lease.owner.model_dump_json(),
                    ex=OWNER_TTL_SECONDS,
                )
        except BaseException:
            session.rollback()
            try:
                self.abort_start(str(response_id))
            except Exception:
                logger.exception("Could not undo a reserved response")
            raise

    def reserve_run_id(
        self,
        *,
        agent: AgentInfo,
        messages: Sequence[Message],
        previous_run_id: str | None,
        parent_run_id: str | None,
        parent_message_id: str | None,
        parent_tool_call_id: str | None,
    ) -> str:
        if previous_run_id is not None and agent.id != str(self.chat_session_id):
            # An idle child's next run comes from its inbox.
            instruction = messages[0] if messages else None
            if len(messages) > 1 or (
                instruction is not None and not isinstance(instruction, UserMessage)
            ):
                raise ValueError("A child run starts from one message or its results")
            if (
                parent_run_id is None
                or parent_message_id is None
                or parent_tool_call_id is None
            ):
                raise ValueError("Child run has no parent invocation")
            with get_session_with_tenant(tenant_id=self.tenant_id) as session:
                reserved = reserve_inbox_run__no_commit(
                    session,
                    self._input_branch,
                    agent,
                    message_id=instruction.id if instruction else None,
                    previous_run_id=previous_run_id,
                    parent_ids=(parent_run_id, parent_message_id, parent_tool_call_id),
                )
                if reserved is None:
                    raise _MessageChanged("Agent inbox work changed before it started")
                message_id, root_id = reserved
                # The inbox work was consumed, so a failed start is recorded.
                self._claim_reservation(
                    session, message_id, root_id, record_start_failure=True
                )
            return str(message_id)
        if parent_run_id is None:
            with get_session_with_tenant(tenant_id=self.tenant_id) as session:
                response = find_response__no_commit(session, self.response_id)
                if (
                    response is None
                    or response.chat_session_id != self.chat_session_id
                    or agent.id != str(self.chat_session_id)
                    or response.message_type != MessageType.ASSISTANT
                    or response.response_status is not None
                ):
                    raise ValueError("Response is unavailable for a new run")
            return str(self.response_id)
        if len(messages) != 1 or not isinstance(messages[0], UserMessage):
            raise ValueError("A saved child response requires one user instruction")
        if parent_message_id is None or parent_tool_call_id is None:
            raise ValueError("Child instruction has no parent invocation")
        parent_response_id = int(parent_run_id)
        with self._lock:
            parent = self._owned.get(parent_response_id)
        if parent is None:
            raise ValueError("Parent response has no execution ownership")
        parent_snapshot = parent.run.snapshot(include_children=False)
        self._save_output(parent, parent_snapshot)
        # A spawned agent works in the background; foreground tools wait for their child.
        delivers_result = any(
            call.id == parent_tool_call_id and call.name == SPAWN_AGENT_TOOL_NAME
            for step in parent_snapshot.steps
            if step.message.id == parent_message_id
            for call in step.message.tool_calls
        )
        with _ownership_lock(self.cache, parent_response_id):
            self._require_owner(parent)
            with get_session_with_tenant(tenant_id=self.tenant_id) as session:
                check_checkpoint_owner__no_commit(
                    session, parent_response_id, parent.owner.ownership_version
                )
                message_id = reserve_child_response__no_commit(
                    session,
                    parent.owner.root_message_id,
                    agent=agent,
                    instruction=messages[0],
                    previous_response_id=int(previous_run_id)
                    if previous_run_id is not None
                    else None,
                    parent_response_id=parent_response_id,
                    parent_message_id=parent_message_id,
                    parent_tool_call_id=parent_tool_call_id,
                    delivers_result=delivers_result,
                )
                self._claim_reservation(
                    session,
                    message_id,
                    parent.owner.root_message_id,
                    record_start_failure=False,
                )
        return str(message_id)

    def register(self, run: Run) -> None:
        response_id = int(run.id)
        snapshot = run.snapshot(include_children=False)
        with self._lock:
            lease = self._leases.get(response_id)
        if lease is None:
            # Child runs take their lease when they are reserved.
            if response_id != self.response_id or snapshot.parent_run_id is not None:
                raise ValueError("Child response has no reservation")
            with _ownership_lock(self.cache, response_id):
                if self._owner(response_id) is not None:
                    raise ValueError("Response already has an owner")
                with get_session_with_tenant(tenant_id=self.tenant_id) as session:
                    response = find_response__no_commit(session, response_id)
                    if response is None or response.response_status is not None:
                        raise ValueError("Response is unavailable for a new run")
                    save_response_record__no_commit(
                        session, self.response_id, self._record(snapshot)
                    )
                    session.commit()
                lease = _OwnerLease(
                    ResponseOwner(token=uuid4(), root_message_id=self.response_id)
                )
                with self._lock:
                    self._leases[response_id] = lease
                self.cache.set(
                    _owner_key(response_id),
                    lease.owner.model_dump_json(),
                    ex=OWNER_TTL_SECONDS,
                )
        with lease.lock:
            if lease.error is not None:
                raise RuntimeError(
                    "Response ownership failed during restoration"
                ) from lease.error
            started = time.monotonic()
            self._refresh_owner(response_id, lease.owner)
            if (
                time.monotonic() - started
                >= OWNER_TTL_SECONDS - OWNER_EXPIRY_MARGIN_SECONDS
            ):
                raise TimeoutError("Response ownership renewal took too long")
            lease.refreshed = started
        with self._lock:
            self._owned[response_id] = _OwnedRun(run, lease)

    def abort_start(self, run_id: str) -> None:
        response_id = int(run_id)
        with self._lock:
            lease = self._leases.get(response_id)
        if lease is None:
            with _ownership_lock(self.cache, response_id):
                if self._owner(response_id) is not None:
                    return
                with get_session_with_tenant(tenant_id=self.tenant_id) as session:
                    abort_response_start__no_commit(
                        session, self.response_id, response_id
                    )
                    session.commit()
            return
        with lease.lock:
            lease.released = True
        try:
            with _ownership_lock(self.cache, response_id):
                owner = self._owner(response_id)
                if owner is not None and owner != lease.owner:
                    return
                if lease.owner.ownership_version is not None:
                    if owner is None:
                        return
                    with get_session_with_tenant(tenant_id=self.tenant_id) as session:
                        release_checkpoint_claim__no_commit(
                            session,
                            response_id,
                            lease.owner.ownership_version,
                        )
                        session.commit()
                else:
                    with get_session_with_tenant(tenant_id=self.tenant_id) as session:
                        if lease.record_start_failure:
                            fail_response_start__no_commit(session, response_id)
                        else:
                            abort_response_start__no_commit(
                                session, self.response_id, response_id
                            )
                        session.commit()
                if owner is not None:
                    self.cache.delete(_owner_key(response_id))
        finally:
            with self._lock:
                self._leases.pop(response_id, None)
                self._owned.pop(response_id, None)

    @property
    def has_owned_work(self) -> bool:
        with self._lock:
            return bool(self._leases) or self._pending_dispatch

    def save(self, run: Run) -> None:
        response_id = int(run.id)
        with self._lock:
            owned = self._owned.get(response_id)
        if owned is None:
            raise ValueError("Run has no storage ownership")
        if response_id != self.response_id or self._root_response is None:
            self._save_output(owned, run.snapshot(include_children=False))
            return
        with _ownership_lock(self.cache, response_id):
            self._require_owner(owned)
            with get_session_with_tenant(tenant_id=self.tenant_id) as session:
                check_checkpoint_owner__no_commit(
                    session, response_id, owned.owner.ownership_version
                )
            self._root_response.save(run)

    def release(self, run_id: str) -> None:
        response_id = int(run_id)
        with self._lock:
            owned = self._owned.get(response_id)
        if owned is None:
            return
        is_child = response_id != self.response_id
        with owned.lease.lock:
            owned.lease.released = True
        try:
            with _ownership_lock(self.cache, response_id):
                if self._owner(response_id) == owned.lease.owner:
                    self.cache.delete(_owner_key(response_id))
        finally:
            # Owned work stays visible until the dispatch it needs is pending.
            with self._lock:
                self._leases.pop(response_id, None)
                self._owned.pop(response_id, None)
                if is_child:
                    self._pending_dispatch = True
                    self._next_input_poll = 0.0
        if is_child and self._on_child_released is not None:
            self._on_child_released()

    def _refresh_owner(self, response_id: int, owner: ResponseOwner) -> None:
        if not self.control_cache.renew_if_value(
            _owner_key(response_id),
            owner.model_dump_json().encode(),
            OWNER_TTL_SECONDS,
        ):
            raise _OwnershipLost("Response ownership was lost")

    def poll_control(self) -> None:
        """Renew leases, read Stop, and dispatch messages on the turn's control thread."""
        with self._lock:
            leases = list(self._leases.items())
        for response_id, lease in leases:
            if not lease.lock.acquire(blocking=False):
                continue
            stopped = False
            try:
                if lease.released:
                    continue
                lease.expire_if_due()
                now = time.monotonic()
                if (
                    lease.error is None
                    and now >= lease.retry_at
                    and now - lease.refreshed >= OWNER_REFRESH_SECONDS
                ):
                    try:
                        self._refresh_owner(response_id, lease.owner)
                    except _OwnershipLost as error:
                        lease.error = error
                    except Exception:
                        lease.retry_at = time.monotonic() + OWNER_RETRY_SECONDS
                        logger.exception(
                            "Response ownership renewal failed; will retry"
                        )
                    else:
                        lease.expire_if_due()
                        if lease.error is None:
                            # Cache response latency must not extend local ownership.
                            lease.refreshed = now
                lease.expire_if_due()
                if lease.error is None:
                    try:
                        stopped = self.control_cache.exists(self._stop_key(response_id))
                    except Exception:
                        logger.exception(
                            "Failed to read agent Stop request; will retry"
                        )
                    lease.expire_if_due()
                stopped = stopped or lease.error is not None
            finally:
                lease.lock.release()
            if not stopped:
                continue
            with self._lock:
                owned = self._owned.get(response_id)
            if owned is not None:
                owned.run.cancel()
        self._dispatch_messages()

    def handoff(self, run_id: str) -> None:
        """Save a paused run before releasing ownership for another API pod."""
        response_id = int(run_id)
        with self._lock:
            owned = self._owned[response_id]
        if owned.run.status != RunStatus.SUSPENDED or not owned.run.wait_for_idle(
            timeout=OPERATION_TIMEOUT_SECONDS
        ):
            raise ValueError("Response must be suspended and idle before release")
        captured = owned.run.capture()
        progress = captured.run_state.progress
        if progress is None:
            raise RunNotTransferable("Response has no saved execution progress")
        for child_id in progress.child_run_ids:
            if not self.read_run_status(child_id, owned.run.agent_id).is_terminal:
                raise RunNotTransferable(
                    "Child responses must be saved before parent release"
                )
        self._with_tenant(
            lambda: persist_checkpoint_files(captured, session_id=self.chat_session_id)
        )
        record = self._record(captured.run_state)
        data = serialize_checkpoint(captured, record, self._binding(response_id))

        def save(_checkpoint: ExecutionCheckpoint) -> None:
            with _ownership_lock(self.cache, response_id):
                self._require_owner(owned)
                with get_session_with_tenant(tenant_id=self.tenant_id) as session:
                    check_checkpoint_owner__no_commit(
                        session, response_id, owned.owner.ownership_version
                    )
                    save_response_record__no_commit(
                        session,
                        owned.owner.root_message_id,
                        record.model_copy(update={"status": RunStatus.RUNNING}),
                    )
                    saved = read_response__no_commit(session, response_id)
                    if saved is None:
                        raise ValueError("Response is unavailable")
                    deserialize_checkpoint(
                        data,
                        saved.response,
                        captured.agent_state,
                        self._binding(response_id),
                    )
                    publish_checkpoint__no_commit(
                        session,
                        response_id,
                        data,
                        expected_ownership_version=owned.owner.ownership_version,
                    )
                    session.commit()

        owned.run.handoff(expected_revision=captured.run_state.revision, save=save)

    def resume(self, run_id: str, *, context: AgentState) -> Run | None:
        """Resume with authorized, rehydrated history; never reconstruct a live owner."""
        if not run_id.isdecimal():
            raise LookupError("Response is unavailable")
        response_id = int(run_id)
        build_agent = self._build_agent
        if self._coordinator is None or build_agent is None:
            raise ValueError("Bind feature reconstruction before resuming")
        saved = self._load(response_id)
        with _ownership_lock(self.cache, response_id):
            if self._owner(response_id) is not None:
                return None
            with get_session_with_tenant(tenant_id=self.tenant_id) as session:
                checkpoint = claim_checkpoint__no_commit(session, saved.message_id)
                session.commit()
            if checkpoint is None:
                return None
            owner = ResponseOwner(
                token=uuid4(),
                root_message_id=saved.root_message_id,
                ownership_version=checkpoint.ownership_version,
            )
            lease = _OwnerLease(owner)
            try:
                self.cache.set(
                    _owner_key(response_id),
                    owner.model_dump_json(),
                    ex=OWNER_TTL_SECONDS,
                )
            except Exception:
                with get_session_with_tenant(tenant_id=self.tenant_id) as session:
                    release_checkpoint_claim__no_commit(
                        session, saved.message_id, checkpoint.ownership_version
                    )
                    session.commit()
                raise
        with self._lock:
            self._leases[response_id] = lease
        try:
            captured = deserialize_checkpoint(
                checkpoint.data,
                saved.response,
                context,
                self._binding(saved.message_id),
            )
            agent = self._with_tenant(lambda: build_agent(captured))
            self._coordinator.register(saved.agent)
            for info in self.list_agents():
                self._coordinator.register(info)
            return self._with_tenant(
                lambda: agent.resume(captured.run_state, coordinator=self._coordinator)
            )
        except BaseException:
            try:
                self.abort_start(str(response_id))
            except Exception:
                logger.exception("Response reconstruction rollback failed")
            raise
