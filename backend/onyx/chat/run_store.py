"""Live response ownership and explicit, safe checkpoint transfer across API pods."""

import threading
import time
from collections.abc import Callable, Collection, Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

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
    BackgroundDelegation,
    ExecutionCheckpoint,
    RunState,
    RunStatus,
    StepRecord,
)
from onyx.agents.runtime import Agent, Run, RunNotTransferable
from onyx.cache.factory import get_cache_backend
from onyx.cache.interface import CacheBackend
from onyx.chat.checkpoint import deserialize_checkpoint, serialize_checkpoint
from onyx.chat.models import (
    ChatBranch,
    CheckpointBinding,
    ResponseOwner,
    ResponseRecord,
    ResponseStatus,
    SavedResponse,
)
from onyx.chat.presentation import project_response
from onyx.chat.response import response_record, response_snapshot
from onyx.chat.restoration import persist_checkpoint_files
from onyx.configs.constants import MessageType
from onyx.db.chat import (
    get_selected_response,
    response_invocation,
    root_response_id,
    visible_message_ids,
)
from onyx.db.chat_checkpoint import (
    check_checkpoint_owner__no_commit,
    claim_checkpoint__no_commit,
    interrupt_response__no_commit,
    publish_checkpoint__no_commit,
    release_checkpoint_claim__no_commit,
)
from onyx.db.chat_inputs import (
    activate_reserved_message,
    can_start_message,
    close_response_inputs,
    enqueue_message,
    fail_pending_message,
    fail_reserved_message,
    inputs_available,
    latest_agent_response,
    latest_agent_responses,
    lock_agent,
    message_receipt,
    pending_inputs,
    queued_request,
    receive_messages,
    reserve_input_response,
    resolve_delegation_messages,
)
from onyx.db.chat_response import (
    abort_response_start__no_commit,
    find_response__no_commit,
    finish_checkpoint__no_commit,
    read_response__no_commit,
    read_response_status__no_commit,
    reserve_agent_continuation__no_commit,
    reserve_child_response__no_commit,
    save_chat_turn,
    save_response_record__no_commit,
)
from onyx.db.chat_subagents import (
    active_subagent_response_ids,
    background_response_statuses,
    load_session_agent_metadata,
    pending_agent_completion_ids,
    read_agent_completions,
    unread_agent_result_ids,
)
from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.llm.cancellation import CancellationSignal
from onyx.llm.models import Message, UserMessage
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
RESPONSE_OWNER_KEY_PREFIX = "chat_response_owner:"


def active_response_ids(cache: CacheBackend, response_ids: Collection[int]) -> set[int]:
    keys = {
        f"{RESPONSE_OWNER_KEY_PREFIX}{response_id}": response_id
        for response_id in response_ids
    }
    return {keys[key] for key in cache.exists_many(keys)} if keys else set()


class _OwnershipLost(RuntimeError):
    pass


class _MessageChanged(ValueError):
    """Another owner removed the message or advanced its recipient before reservation."""


class _OwnerLease:
    def __init__(self, owner: ResponseOwner) -> None:
        self.owner = owner
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


class ChatRunStore(RunStore, RunOwnership):
    """Persist runs on one authorized branch. The application polls control while ownership remains."""

    def __init__(
        self,
        *,
        tenant_id: str,
        chat_session_id: UUID,
        response_id: int,
        visible_response_ids: list[int],
        cache: CacheBackend,
        root_response: RunStore | None = None,
        control_cache: CacheBackend | None = None,
    ) -> None:
        self.tenant_id = tenant_id
        self.chat_session_id = chat_session_id
        self.response_id = response_id
        self.visible_response_ids = set(visible_response_ids) | {response_id}
        self._input_branch = ChatBranch(
            chat_session_id=chat_session_id, message_ids=list(self.visible_response_ids)
        )
        self.cache = cache
        self.control_cache = control_cache or get_cache_backend(
            tenant_id=tenant_id, operation_timeout_s=LEASE_CACHE_TIMEOUT_S
        )
        self._root_response = root_response
        self._lock = threading.Lock()
        self._owned: dict[int, _OwnedRun] = {}
        self._leases: dict[int, _OwnerLease] = {}
        self._coordinator: AgentCoordinator | None = None
        self._build_agent: Callable[[ExecutionCheckpoint], Agent] | None = None
        self._message_reservations: dict[int, int] = {}
        self._starting_messages: set[str] = set()
        self._dispatch_lock = threading.Lock()
        self._pending_dispatch = False
        self._input_revision = 0
        self._next_input_poll = 0.0
        self._completion_step_limit: int | None = None

    def _with_tenant[T](self, operation: Callable[[], T]) -> T:
        token = CURRENT_TENANT_ID_CONTEXTVAR.set(self.tenant_id)
        try:
            return operation()
        finally:
            CURRENT_TENANT_ID_CONTEXTVAR.reset(token)

    def _owner_key(self, response_id: int) -> str:
        return f"{RESPONSE_OWNER_KEY_PREFIX}{response_id}"

    def _stop_key(self, response_id: int) -> str:
        return f"chat_response_stop:{response_id}"

    @contextmanager
    def _ownership_lock(self, response_id: int) -> Iterator[None]:
        lock = self.cache.lock(
            f"chat_response_lock:{response_id}", timeout=OWNER_LOCK_SECONDS
        )
        if not lock.acquire(blocking_timeout=OWNER_LOCK_WAIT_SECONDS):
            raise TimeoutError("Response ownership is busy")
        try:
            yield
        finally:
            lock.release()

    def _owner(self, response_id: int) -> ResponseOwner | None:
        value = self.cache.get(self._owner_key(response_id))
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
        directory: AgentDirectory,
    ) -> AgentCoordinator:
        if self._coordinator is not None:
            raise ValueError("Response store is already bound")
        self._build_agent = build_agent
        self._coordinator = coordinator.view(
            directory=directory, store=self, ownership=self
        )
        return self._coordinator

    def _load_status(
        self, response_id: int, parent_id: str | None = None
    ) -> ResponseStatus:
        with get_session_with_tenant(tenant_id=self.tenant_id) as session:
            saved = read_response_status__no_commit(session, response_id)
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
        if saved.status == RunStatus.RUNNING:
            with self._ownership_lock(saved.message_id):
                if self._owner(saved.message_id) is None:
                    with get_session_with_tenant(tenant_id=self.tenant_id) as session:
                        interrupt_response__no_commit(session, saved.message_id)
                        session.commit()
                        current = read_response_status__no_commit(
                            session, saved.message_id
                        )
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

    def discovery(self) -> list[AgentInfo]:
        return self._with_tenant(lambda: load_session_agent_metadata(self.response_id))

    def submit_message(self, request: AgentMessageRequest) -> AgentMessageReceipt:
        with self._lock:
            parent = self._owned.get(int(request.parent_run_id))
        if parent is None or parent.run.agent_id != request.parent_id:
            raise ValueError("Message sender has no execution ownership")
        self._save_output(parent, parent.run.snapshot(include_children=False))
        with self._ownership_lock(int(request.parent_run_id)):
            self._require_owner(parent)
            with get_session_with_tenant(tenant_id=self.tenant_id) as session:
                receipt = enqueue_message(session, self._input_branch, request)
                session.commit()
        with self._lock:
            self._pending_dispatch = True
            self._input_revision += 1
            self._next_input_poll = 0.0
        return receipt

    def resolve_delegation_messages(
        self, parent_run_id: str, delegations: Sequence[BackgroundDelegation]
    ) -> dict[str, str | None]:
        with self._lock:
            if int(parent_run_id) not in self._owned:
                raise ValueError("Delegation sender has no execution ownership")
        with get_session_with_tenant(tenant_id=self.tenant_id) as session:
            return resolve_delegation_messages(session, int(parent_run_id), delegations)

    def pending_messages(
        self, agent_id: str | None = None
    ) -> list[AgentMessageReceipt]:
        with get_session_with_tenant(tenant_id=self.tenant_id) as session:
            return [
                message_receipt(row)
                for row in pending_inputs(session, self._input_branch, agent_id)
            ]

    def receive_inputs(self, run: Run) -> list[UserMessage]:
        received = run.received_input_ids
        with get_session_with_tenant(tenant_id=self.tenant_id) as session:
            return receive_messages(session, run.agent_id, run.id, received)

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
        with self._ownership_lock(response_id):
            self._require_owner(owned)
            with get_session_with_tenant(tenant_id=self.tenant_id) as session:
                if not inputs_available(
                    session,
                    response_id,
                    step.input_messages,
                    ownership_version=owned.owner.ownership_version,
                ):
                    return False
                save_response_record__no_commit(
                    session, owned.owner.root_message_id, self._record(snapshot)
                )
                session.commit()
                return True

    def close_inputs(self, run: Run, *, can_continue: bool) -> bool:
        response_id = int(run.id)
        with self._lock:
            owned = self._owned.get(response_id)
        if owned is None:
            raise ValueError("Response has no execution ownership")
        with self._ownership_lock(response_id):
            self._require_owner(owned)
            with get_session_with_tenant(tenant_id=self.tenant_id) as session:
                pending = close_response_inputs(
                    session,
                    response_id,
                    can_continue=can_continue,
                    ownership_version=owned.owner.ownership_version,
                )
                session.commit()
                return pending

    def dispatch_messages(self) -> None:
        coordinator = self._coordinator
        with self._lock:
            if time.monotonic() < self._next_input_poll:
                return
            revision = self._input_revision
            self._next_input_poll = time.monotonic() + INPUT_POLL_SECONDS
        if (
            coordinator is None
            or coordinator.is_closed
            or not self._dispatch_lock.acquire(blocking=False)
        ):
            return
        try:
            with get_session_with_tenant(tenant_id=self.tenant_id) as session:
                rows = pending_inputs(session, self._input_branch)
                latest_by_agent = latest_agent_responses(
                    session,
                    self._input_branch,
                    {str(row.recipient_session_id) for row in rows},
                )
                running = {
                    self._owner_key(response_id): response_id
                    for response_id in active_subagent_response_ids(
                        session, self._input_branch
                    )
                }
                owners = (
                    self.control_cache.exists_many(running.keys()) if running else set()
                )
                for key, response_id in running.items():
                    if key not in owners:
                        self._load_status(response_id)
                for latest in latest_by_agent.values():
                    owner_key = self._owner_key(latest.id)
                    if owner_key in running and owner_key not in owners:
                        session.expire(latest, ["response_status"])
                requests = []
                selected: set[str] = set()
                for row in sorted(
                    rows, key=lambda item: item.target_response_id is not None
                ):
                    agent_id = str(row.recipient_session_id)
                    if agent_id in selected:
                        continue
                    latest = latest_by_agent.get(agent_id)
                    if can_start_message(row, latest):
                        requests.append(queued_request(row))
                        selected.add(agent_id)
                selected_root = get_selected_response(session, self.chat_session_id)
                completions = (
                    pending_agent_completion_ids(session, self._input_branch)
                    if selected_root is not None
                    and self.response_id in visible_message_ids(session, selected_root)
                    else []
                )
                with self._lock:
                    self._pending_dispatch = (
                        self._input_revision != revision
                        or bool(requests)
                        or any(
                            self._owner_key(latest.id) in owners
                            for latest in latest_by_agent.values()
                        )
                        or any(
                            response_id not in self.visible_response_ids
                            for response_id in completions
                        )
                    )
            for request in requests:
                lock = self.cache.lock(
                    f"chat_agent_dispatch:{request.agent_id}",
                    timeout=OWNER_LOCK_SECONDS,
                )
                if not lock.acquire(blocking_timeout=0):
                    continue
                try:
                    message_id = request.message.id
                    if message_id is None:
                        raise ValueError("Queued input has no identity")
                    with self._lock:
                        self._starting_messages.add(message_id)
                    try:
                        coordinator.start_message_run(request)
                    finally:
                        with self._lock:
                            self._starting_messages.discard(message_id)
                except _MessageChanged:
                    continue
                except Exception:
                    logger.exception("Could not start queued agent message")
                    with get_session_with_tenant(tenant_id=self.tenant_id) as session:
                        fail_pending_message(session, self._input_branch, request)
                        session.commit()
                finally:
                    lock.release()
            self._dispatch_completions(coordinator, completions, selected)
            coordinator.notify_inputs()
        finally:
            self._dispatch_lock.release()

    def _dispatch_completions(
        self,
        coordinator: AgentCoordinator,
        completions: list[int],
        submitted_agent_ids: set[str],
    ) -> None:
        for previous_id in completions:
            if (
                self._completion_step_limit is None
                or previous_id in self.visible_response_ids
            ):
                continue
            with get_session_with_tenant(tenant_id=self.tenant_id) as session:
                response = find_response__no_commit(session, previous_id)
                if response is None:
                    continue
                agent_id = str(response.chat_session_id)
                invocation = response_invocation(response)
                if invocation is None or invocation.parent_chat_message_id is None:
                    raise ValueError("Agent continuation has no original invocation")
                parent_run_id = str(invocation.parent_chat_message_id)
                parent_message_id = f"{parent_run_id}:{invocation.turn_number}"
                parent_tool_call_id = invocation.tool_call_id
            if agent_id in submitted_agent_ids:
                continue
            previous = coordinator.active_run(agent_id)
            if previous is not None and not previous.wait_for_idle(timeout=0):
                continue
            lock = self.cache.lock(
                f"chat_agent_dispatch:{agent_id}", timeout=OWNER_LOCK_SECONDS
            )
            if not lock.acquire(blocking_timeout=0):
                continue
            try:
                agent = coordinator.resolve_child(agent_id, str(self.chat_session_id))
                agent.start(
                    max_steps=self._completion_step_limit,
                    coordinator=coordinator,
                    cancellation=CancellationSignal(),
                    deadline_at=datetime.now(timezone.utc)
                    + timedelta(seconds=OPERATION_TIMEOUT_SECONDS),
                    parent_run_id=parent_run_id,
                    parent_message_id=parent_message_id,
                    parent_tool_call_id=parent_tool_call_id,
                )
            except _MessageChanged:
                continue
            except Exception:
                logger.exception("Could not continue agent after child completion")
                if coordinator.is_closed:
                    return
                with get_session_with_tenant(tenant_id=self.tenant_id) as session:
                    lock_agent(session, agent_id)
                    latest = latest_agent_response(
                        session, self._input_branch, agent_id
                    )
                    if (
                        latest is not None
                        and latest.id == previous_id
                        and latest.response_status == RunStatus.COMPLETE
                    ):
                        failed_id = reserve_agent_continuation__no_commit(
                            session, latest
                        )
                        fail_reserved_message(session, failed_id)
                        session.commit()
            finally:
                lock.release()

    def completed_agents(
        self,
        parent_id: str,
        received_run_ids: Collection[str],
        *,
        limit: int,
    ) -> list[AgentCompletion]:
        branch = ChatBranch(
            chat_session_id=self.chat_session_id,
            message_ids=list(self.visible_response_ids),
        )
        with get_session_with_tenant(tenant_id=self.tenant_id) as session:
            statuses = background_response_statuses(
                session, branch, parent_id, received_run_ids
            )
        running = {
            self._owner_key(response_id): response_id
            for response_id, status in statuses.items()
            if status == RunStatus.RUNNING
        }
        if running:
            owned = self.control_cache.exists_many(running.keys())
            for key, response_id in running.items():
                if key not in owned:
                    statuses[response_id] = self._load_status(
                        response_id, parent_id
                    ).status
        completed_ids = [
            response_id
            for response_id, status in statuses.items()
            if status.is_terminal
        ][:limit]
        if not completed_ids:
            return []
        with get_session_with_tenant(tenant_id=self.tenant_id) as session:
            return read_agent_completions(session, completed_ids)

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
        with self._ownership_lock(saved.message_id):
            if self._owner(saved.message_id) is None:
                with get_session_with_tenant(tenant_id=self.tenant_id) as session:
                    interrupt_response__no_commit(
                        session, saved.message_id, cancelled=True
                    )
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
                registrations=self._coordinator.registrations()
                if self._coordinator
                else (),
            )
        record = display.response if display is not None else self._record(snapshot)
        if record is None:
            raise ValueError("Response projection has no accepted content")
        with self._ownership_lock(response_id):
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
        instruction = (
            messages[0]
            if len(messages) == 1 and isinstance(messages[0], UserMessage)
            else None
        )
        with self._lock:
            queued_start = (
                instruction is not None and instruction.id in self._starting_messages
            )
        completion_start = (
            not messages
            and previous_run_id is not None
            and agent.id != str(self.chat_session_id)
        )
        if queued_start or completion_start:
            with get_session_with_tenant(tenant_id=self.tenant_id) as session:
                lock_agent(session, agent.id)
                if queued_start and instruction is not None:
                    row = next(
                        (
                            item
                            for item in pending_inputs(
                                session, self._input_branch, agent.id
                            )
                            if item.message_id == instruction.id
                        ),
                        None,
                    )
                    if row is None:
                        raise _MessageChanged("Message is no longer pending")
                    latest = latest_agent_response(
                        session, self._input_branch, agent.id
                    )
                    if (
                        not can_start_message(row, latest)
                        or (str(latest.id) if latest else None) != previous_run_id
                    ):
                        raise _MessageChanged(
                            "Agent execution changed before message acceptance"
                        )
                    request = queued_request(row)
                    if (parent_run_id, parent_message_id, parent_tool_call_id) != (
                        request.parent_run_id,
                        request.parent_message_id,
                        request.parent_tool_call_id,
                    ):
                        raise ValueError("Message invocation changed")
                    message_id, root_id = reserve_input_response(
                        session, row, agent, latest
                    )
                else:
                    latest = latest_agent_response(
                        session, self._input_branch, agent.id
                    )
                    if (
                        latest is None
                        or str(latest.id) != previous_run_id
                        or latest.response_status != RunStatus.COMPLETE
                        or not unread_agent_result_ids(
                            session, self._input_branch, agent.id
                        )
                    ):
                        raise _MessageChanged(
                            "Agent has no unread completion to accept"
                        )
                    invocation = response_invocation(latest)
                    if invocation is None or (
                        parent_run_id,
                        parent_message_id,
                        parent_tool_call_id,
                    ) != (
                        str(invocation.parent_chat_message_id),
                        f"{invocation.parent_chat_message_id}:{invocation.turn_number}",
                        invocation.tool_call_id,
                    ):
                        raise ValueError("Continuation changed its original invocation")
                    root_id = root_response_id(session, latest)
                    selected_root = get_selected_response(session, self.chat_session_id)
                    if selected_root is None or root_id not in visible_message_ids(
                        session, selected_root
                    ):
                        raise _MessageChanged(
                            "Agent continuation is no longer on the selected branch"
                        )
                    message_id = reserve_agent_continuation__no_commit(session, latest)
                owner = ResponseOwner(token=uuid4(), root_message_id=root_id)
                lease = _OwnerLease(owner)
                with self._ownership_lock(message_id):
                    try:
                        activate_reserved_message(session, message_id)
                        session.commit()
                        self.cache.set(
                            self._owner_key(message_id),
                            owner.model_dump_json(),
                            ex=OWNER_TTL_SECONDS,
                        )
                    except BaseException:
                        try:
                            session.rollback()
                            fail_reserved_message(session, message_id)
                            session.commit()
                        except Exception:
                            logger.exception(
                                "Could not record queued response startup failure"
                            )
                        try:
                            if self._owner(message_id) == owner:
                                self.cache.delete(self._owner_key(message_id))
                        except Exception:
                            logger.exception("Failed queued response lease will expire")
                        raise
                    with self._lock:
                        self._message_reservations[message_id] = root_id
                        self._leases[message_id] = lease
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
        self._save_output(parent, parent.run.snapshot(include_children=False))
        with self._ownership_lock(parent_response_id):
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
                )
                session.commit()
        return str(message_id)

    def register(self, run: Run) -> None:
        response_id = int(run.id)
        snapshot = run.snapshot(include_children=False)
        with self._lock:
            if response_id == self.response_id:
                if snapshot.progress is None:
                    raise ValueError("New response has no execution budget")
                self._completion_step_limit = snapshot.progress.step_limit
            lease = self._leases.get(response_id)
            claimed = lease.owner if lease is not None else None
            parent = (
                self._owned.get(int(snapshot.parent_run_id))
                if snapshot.parent_run_id is not None
                else None
            )
            message_root_id = self._message_reservations.get(response_id)
        if claimed is None:
            if (
                snapshot.parent_run_id is not None
                and parent is None
                and message_root_id is None
            ):
                raise ValueError("Parent response has no execution ownership")
            root_message_id = message_root_id or (
                parent.owner.root_message_id if parent else self.response_id
            )
            with self._ownership_lock(response_id):
                if self._owner(response_id) is not None:
                    raise ValueError("Response already has an owner")
                with get_session_with_tenant(tenant_id=self.tenant_id) as session:
                    response = find_response__no_commit(session, response_id)
                    if response is None or response.response_status is not None:
                        raise ValueError("Response is unavailable for a new run")
                    save_response_record__no_commit(
                        session, root_message_id, self._record(snapshot)
                    )
                    session.commit()
                claimed = ResponseOwner(
                    token=uuid4(),
                    root_message_id=root_message_id,
                )
                lease = _OwnerLease(claimed)
                with self._lock:
                    self._leases[response_id] = lease
                self.cache.set(
                    self._owner_key(response_id),
                    claimed.model_dump_json(),
                    ex=OWNER_TTL_SECONDS,
                )
        if lease is None:
            raise RuntimeError("Response registration did not establish ownership")
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
            queued_message = response_id in self._message_reservations
        if lease is None:
            with self._ownership_lock(response_id):
                if self._owner(response_id) is not None:
                    return
                with get_session_with_tenant(tenant_id=self.tenant_id) as session:
                    if queued_message:
                        fail_reserved_message(session, response_id)
                    else:
                        abort_response_start__no_commit(
                            session, self.response_id, response_id
                        )
                    session.commit()
            with self._lock:
                self._message_reservations.pop(response_id, None)
            return
        with lease.lock:
            lease.released = True
        try:
            with self._ownership_lock(response_id):
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
                        if queued_message:
                            fail_reserved_message(session, response_id)
                        else:
                            abort_response_start__no_commit(
                                session, self.response_id, response_id
                            )
                        session.commit()
                if owner is not None:
                    self.cache.delete(self._owner_key(response_id))
        finally:
            with self._lock:
                self._leases.pop(response_id, None)
                self._owned.pop(response_id, None)
                self._message_reservations.pop(response_id, None)

    @property
    def has_owned_work(self) -> bool:
        with self._lock:
            return bool(self._leases) or self._pending_dispatch

    def _release_owner(self, response_id: int, lease: _OwnerLease) -> None:
        with lease.lock:
            lease.released = True
        try:
            with self._ownership_lock(response_id):
                if self._owner(response_id) == lease.owner:
                    self.cache.delete(self._owner_key(response_id))
        finally:
            with self._lock:
                self._leases.pop(response_id, None)

    def save(self, run: Run) -> None:
        response_id = int(run.id)
        with self._lock:
            owned = self._owned.get(response_id)
        if owned is None:
            raise ValueError("Run has no storage ownership")
        if response_id != self.response_id or self._root_response is None:
            self._save_output(owned, run.snapshot(include_children=False))
            return
        with self._ownership_lock(response_id):
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
        try:
            self._release_owner(response_id, owned.lease)
        finally:
            with self._lock:
                self._owned.pop(response_id, None)
                self._message_reservations.pop(response_id, None)
                if response_id != self.response_id:
                    self._input_revision += 1
                    self._pending_dispatch = True
                    self._next_input_poll = 0.0

    def _refresh_owner(self, response_id: int, owner: ResponseOwner) -> None:
        if not self.control_cache.renew_if_value(
            self._owner_key(response_id),
            owner.model_dump_json().encode(),
            OWNER_TTL_SECONDS,
        ):
            raise _OwnershipLost("Response ownership was lost")

    def poll_control(self) -> None:
        """Renew ownership and read Stop requests on the caller's control thread."""
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
        self.dispatch_messages()

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
            with self._ownership_lock(response_id):
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
        with self._ownership_lock(response_id):
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
                    self._owner_key(response_id),
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
            for info in self.discovery():
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
