"""Live response ownership and explicit, safe checkpoint transfer across API pods."""

import os
import threading
import time
from collections.abc import Callable, Iterator
from concurrent.futures import Future
from contextlib import contextmanager
from uuid import UUID, uuid4

from pydantic import BaseModel

from onyx.agents.agent_coordination import (
    AgentCoordinator,
    AgentDirectory,
    RunOwnership,
    RunStore,
)
from onyx.agents.concurrency import OPERATION_TIMEOUT_SECONDS
from onyx.agents.execution_records import RunStatus
from onyx.agents.models import AgentInfo, AgentState, ExecutionCheckpoint, RunState
from onyx.agents.runtime import Agent, Run, RunNotTransferable
from onyx.cache.factory import get_cache_backend
from onyx.cache.interface import CacheBackend
from onyx.chat.checkpoint import (
    CheckpointBinding,
    deserialize_checkpoint,
    serialize_checkpoint,
)
from onyx.chat.models import ResponseRecord, SavedAgentContext
from onyx.chat.response import response_record, response_snapshot
from onyx.chat.restoration import persist_checkpoint_files
from onyx.db.chat_checkpoint import (
    ResponseStatus,
    SavedResponse,
    check_checkpoint_owner__no_commit,
    claim_checkpoint__no_commit,
    interrupt_response__no_commit,
    publish_checkpoint__no_commit,
    read_response__no_commit,
    read_response_status__no_commit,
    release_checkpoint_claim__no_commit,
    save_response_record__no_commit,
)
from onyx.db.chat_response_messages import finish_checkpoint__no_commit
from onyx.db.chat_subagents import (
    load_agent_history,
    load_session_agent_metadata,
    lookup_session_agent,
)
from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import start_thread_future
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
ENABLE_CHAT_CHECKPOINTS = (
    os.environ.get("ENABLE_CHAT_CHECKPOINTS", "true").lower() == "true"
)


class ResponseOwner(BaseModel):
    token: UUID
    message_id: int
    root_message_id: int
    revision: int | None = None


class _OwnershipLost(RuntimeError):
    pass


class _OwnerLease:
    def __init__(self, owner: ResponseOwner) -> None:
        self.owner = owner
        self.lock = threading.Lock()
        self.released = False
        self.refreshed = time.monotonic()
        self.renewal: Future[None] | None = None
        self.renewal_started = self.refreshed
        self.retry_at = self.refreshed
        self.error: Exception | None = None


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
        self.cache = cache
        self.control_cache = control_cache or get_cache_backend(
            tenant_id=tenant_id, operation_timeout_s=LEASE_CACHE_TIMEOUT_S
        )
        self._stop_check: Future[list[str]] | None = None
        self._root_response = root_response
        self._lock = threading.Lock()
        self._owned: dict[str, _OwnedRun] = {}
        self._leases: dict[str, _OwnerLease] = {}
        self._coordinator: AgentCoordinator | None = None
        self._build_agent: Callable[[ExecutionCheckpoint], Agent] | None = None

    def _with_tenant[T](self, operation: Callable[[], T]) -> T:
        token = CURRENT_TENANT_ID_CONTEXTVAR.set(self.tenant_id)
        try:
            return operation()
        finally:
            CURRENT_TENANT_ID_CONTEXTVAR.reset(token)

    def _owner_key(self, run_id: str) -> str:
        return f"chat_response_owner:{run_id}"

    def _stop_key(self, run_id: str) -> str:
        return f"chat_response_stop:{run_id}"

    @contextmanager
    def _ownership_lock(self, run_id: str) -> Iterator[None]:
        lock = self.cache.lock(
            f"chat_response_lock:{run_id}", timeout=OWNER_LOCK_SECONDS
        )
        if not lock.acquire(blocking_timeout=OWNER_LOCK_WAIT_SECONDS):
            raise TimeoutError("Response ownership is busy")
        try:
            yield
        finally:
            lock.release()

    def _owner(self, run_id: str) -> ResponseOwner | None:
        value = self.cache.get(self._owner_key(run_id))
        return ResponseOwner.model_validate_json(value) if value is not None else None

    def _require_owner(self, owned: _OwnedRun) -> None:
        if self._owner(owned.run.id) != owned.owner:
            raise RuntimeError("Response ownership was lost")

    def _binding(self, message_id: int) -> CheckpointBinding:
        return CheckpointBinding(
            tenant_id=self.tenant_id,
            branch_id=str(message_id),
            context_version=f"response:{message_id}",
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

    def _load_status(self, run_id: str, parent_id: str | None = None) -> ResponseStatus:
        with get_session_with_tenant(tenant_id=self.tenant_id) as session:
            saved = read_response_status__no_commit(session, run_id)
        if saved is None:
            raise LookupError("Response is unavailable")
        if (
            saved.root_session_id != self.chat_session_id
            or saved.root_message_id not in self.visible_response_ids
        ):
            raise ValueError("Response is unavailable on this branch")
        if parent_id is not None and saved.parent_agent_id != (parent_id or None):
            raise ValueError("Response is unavailable to this parent")
        if saved.status == RunStatus.RUNNING:
            with self._ownership_lock(saved.run_id):
                if self._owner(saved.run_id) is None:
                    with get_session_with_tenant(tenant_id=self.tenant_id) as session:
                        interrupt_response__no_commit(session, saved.message_id)
                        session.commit()
                        current = read_response_status__no_commit(session, saved.run_id)
                    if current is None:
                        raise LookupError("Response was removed")
                    saved = current
        return saved

    def _load(self, run_id: str, parent_id: str | None = None) -> SavedResponse:
        self._load_status(run_id, parent_id)
        with get_session_with_tenant(tenant_id=self.tenant_id) as session:
            saved = read_response__no_commit(session, run_id)
        if saved is None:
            raise LookupError("Response is unavailable")
        return saved

    def discovery(self) -> list[AgentInfo]:
        return self._with_tenant(lambda: load_session_agent_metadata(self.response_id))

    def lookup_agent(self, agent_id: str, parent_id: str) -> AgentInfo | None:
        return self._with_tenant(
            lambda: lookup_session_agent(self.response_id, agent_id, parent_id)
        )

    def read_run(self, run_id: str, parent_id: str) -> RunState | None:
        try:
            saved = self._load(run_id, parent_id)
        except LookupError:
            return None
        snapshot = response_snapshot(saved.response)
        snapshot.run_id = run_id
        return snapshot

    def read_run_status(self, run_id: str, parent_id: str) -> RunStatus:
        return self._load_status(run_id, parent_id).status

    def load_history(self, run_id: str, parent_id: str) -> SavedAgentContext:
        saved = self._load(run_id, parent_id)
        if not saved.response.status.is_terminal:
            raise ValueError("Response must finish before another run starts")
        return self._with_tenant(
            lambda: load_agent_history(self.response_id, saved.agent.id)
        )

    def cancel_run(self, run_id: str, parent_id: str) -> None:
        saved = self._load(run_id, parent_id)
        if saved.response.status.is_terminal:
            return
        self.cache.set(self._stop_key(saved.response.run_id), 1, ex=STOP_TTL_SECONDS)
        with self._ownership_lock(saved.response.run_id):
            if self._owner(saved.response.run_id) is None:
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

    def _save_output(self, owned: _OwnedRun, snapshot: RunState) -> int:
        record = self._record(snapshot)
        with self._ownership_lock(owned.run.id):
            self._require_owner(owned)
            with get_session_with_tenant(tenant_id=self.tenant_id) as session:
                check_checkpoint_owner__no_commit(
                    session, owned.owner.message_id, owned.owner.revision
                )
                message_id = save_response_record__no_commit(
                    session, owned.owner.root_message_id, record
                )
                if snapshot.status.is_terminal:
                    finish_checkpoint__no_commit(session, message_id)
                session.commit()
            return message_id

    def register(self, run: Run) -> None:
        snapshot = run.snapshot(include_children=False)
        with self._lock:
            lease = self._leases.get(run.id)
            claimed = lease.owner if lease is not None else None
            parent = self._owned.get(snapshot.parent_run_id or "")
        if parent is not None:
            self._save_output(parent, parent.run.snapshot(include_children=False))
        if claimed is None:
            with self._ownership_lock(run.id):
                if self._owner(run.id) is not None:
                    raise ValueError("Response already has an owner")
                with get_session_with_tenant(tenant_id=self.tenant_id) as session:
                    message_id = save_response_record__no_commit(
                        session, self.response_id, self._record(snapshot)
                    )
                    session.commit()
                claimed = ResponseOwner(
                    token=uuid4(),
                    message_id=message_id,
                    root_message_id=self.response_id,
                )
                lease = _OwnerLease(claimed)
                with self._lock:
                    self._leases[run.id] = lease
                self.cache.set(
                    self._owner_key(run.id),
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
            self._refresh_owner(run.id, lease.owner)
            if (
                time.monotonic() - started
                >= OWNER_TTL_SECONDS - OWNER_EXPIRY_MARGIN_SECONDS
            ):
                raise TimeoutError("Response ownership renewal took too long")
            lease.refreshed = started
        with self._lock:
            self._owned[run.id] = _OwnedRun(run, lease)

    def abort_start(self, run_id: str) -> None:
        with self._lock:
            lease = self._leases.get(run_id)
        if lease is None:
            return
        with lease.lock:
            lease.released = True
        try:
            with self._ownership_lock(run_id):
                if self._owner(run_id) != lease.owner:
                    return
                if lease.owner.revision is not None:
                    with get_session_with_tenant(tenant_id=self.tenant_id) as session:
                        release_checkpoint_claim__no_commit(
                            session, lease.owner.message_id, lease.owner.revision
                        )
                        session.commit()
                self.cache.delete(self._owner_key(run_id))
        finally:
            with self._lock:
                self._leases.pop(run_id, None)
                self._owned.pop(run_id, None)

    @property
    def has_owned_work(self) -> bool:
        with self._lock:
            return bool(self._leases)

    def _release_owner(self, run_id: str, lease: _OwnerLease) -> None:
        with lease.lock:
            lease.released = True
        try:
            with self._ownership_lock(run_id):
                if self._owner(run_id) == lease.owner:
                    self.cache.delete(self._owner_key(run_id))
        finally:
            with self._lock:
                self._leases.pop(run_id, None)

    def save(self, run: Run) -> None:
        with self._lock:
            owned = self._owned.get(run.id)
        if owned is None:
            raise ValueError("Run has no storage ownership")
        if owned.owner.message_id != self.response_id or self._root_response is None:
            self._save_output(owned, run.snapshot(include_children=False))
            return
        with self._ownership_lock(run.id):
            self._require_owner(owned)
            with get_session_with_tenant(tenant_id=self.tenant_id) as session:
                check_checkpoint_owner__no_commit(
                    session, owned.owner.message_id, owned.owner.revision
                )
            self._root_response.save(run)

    def release(self, run_id: str) -> None:
        with self._lock:
            owned = self._owned.get(run_id)
        if owned is None:
            return
        try:
            self._release_owner(run_id, owned.lease)
        finally:
            with self._lock:
                self._owned.pop(run_id, None)

    def _refresh_owner(self, run_id: str, owner: ResponseOwner) -> None:
        if not self.control_cache.expire_if_value(
            self._owner_key(run_id), owner.model_dump_json().encode(), OWNER_TTL_SECONDS
        ):
            raise _OwnershipLost("Response ownership was lost")

    def _read_stop_requests(self, run_ids: list[str]) -> list[str]:
        return [
            run_id for run_id in run_ids if self.cache.exists(self._stop_key(run_id))
        ]

    def poll_control(self) -> None:
        """Enforce ownership deadlines independently of pending cache operations."""
        with self._lock:
            leases = list(self._leases.items())
        stopped: set[str] = set()
        if self._stop_check is not None and self._stop_check.done():
            try:
                stopped.update(self._stop_check.result())
            except Exception:
                logger.exception("Failed to read agent Stop requests; will retry")
            self._stop_check = None
        if self._stop_check is None and leases:
            self._stop_check = start_thread_future(
                lambda: self._read_stop_requests([run_id for run_id, _ in leases]),
                name="agent-stop-check",
            )
        for run_id, lease in leases:
            if not lease.lock.acquire(blocking=False):
                continue
            try:
                if lease.released:
                    continue
                now = time.monotonic()
                if lease.error is None and (
                    now
                    >= lease.refreshed + OWNER_TTL_SECONDS - OWNER_EXPIRY_MARGIN_SECONDS
                ):
                    lease.error = TimeoutError(
                        "Response ownership renewal deadline expired"
                    )
                if (
                    lease.error is None
                    and lease.renewal is not None
                    and lease.renewal.done()
                ):
                    try:
                        lease.renewal.result()
                    except _OwnershipLost as error:
                        lease.error = error
                    except Exception:
                        lease.retry_at = now + OWNER_RETRY_SECONDS
                        logger.exception(
                            "Response ownership renewal failed; will retry"
                        )
                    else:
                        # The request start is a conservative bound on the server's TTL.
                        lease.refreshed = lease.renewal_started
                    lease.renewal = None
                if (
                    lease.error is None
                    and lease.renewal is None
                    and now >= lease.retry_at
                    and now - lease.refreshed >= OWNER_REFRESH_SECONDS
                ):
                    lease.renewal_started = now
                    lease.renewal = start_thread_future(
                        lambda run_id=run_id, owner=lease.owner: self._refresh_owner(
                            run_id, owner
                        ),
                        name="agent-lease-renewal",
                    )
                if lease.error is not None:
                    stopped.add(run_id)
            finally:
                lease.lock.release()
        for run_id in stopped:
            with self._lock:
                owned = self._owned.get(run_id)
            if owned is not None:
                owned.run.cancel()

    def handoff(self, run_id: str) -> None:
        """Save a paused run before releasing ownership for another API pod."""
        with self._lock:
            owned = self._owned[run_id]
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
        data = serialize_checkpoint(
            captured, record, self._binding(owned.owner.message_id)
        )
        published = False

        def save(_checkpoint: ExecutionCheckpoint) -> None:
            nonlocal published
            with self._ownership_lock(run_id):
                self._require_owner(owned)
                with get_session_with_tenant(tenant_id=self.tenant_id) as session:
                    check_checkpoint_owner__no_commit(
                        session, owned.owner.message_id, owned.owner.revision
                    )
                    save_response_record__no_commit(
                        session,
                        owned.owner.root_message_id,
                        record.model_copy(update={"status": RunStatus.RUNNING}),
                    )
                    saved = read_response__no_commit(session, run_id)
                    if saved is None:
                        raise ValueError("Response is unavailable")
                    deserialize_checkpoint(
                        data,
                        saved.response,
                        captured.agent_state,
                        self._binding(owned.owner.message_id),
                    )
                    publish_checkpoint__no_commit(
                        session,
                        owned.owner.message_id,
                        data,
                        expected_revision=owned.owner.revision,
                    )
                    session.commit()
                    published = True

        try:
            owned.run.handoff(expected_revision=captured.run_state.revision, save=save)
        finally:
            if published:
                try:
                    self._release_owner(run_id, owned.lease)
                finally:
                    with self._lock:
                        self._owned.pop(run_id, None)

    def resume(self, run_id: str, *, context: AgentState) -> Run | None:
        """Resume with authorized, rehydrated history; never reconstruct a live owner."""
        build_agent = self._build_agent
        if self._coordinator is None or build_agent is None:
            raise ValueError("Bind feature reconstruction before resuming")
        saved = self._load(run_id)
        run_id = saved.response.run_id
        with self._ownership_lock(run_id):
            if self._owner(run_id) is not None:
                return None
            with get_session_with_tenant(tenant_id=self.tenant_id) as session:
                checkpoint = claim_checkpoint__no_commit(session, saved.message_id)
                session.commit()
            if checkpoint is None:
                return None
            owner = ResponseOwner(
                token=uuid4(),
                message_id=saved.message_id,
                root_message_id=saved.root_message_id,
                revision=checkpoint.revision,
            )
            lease = _OwnerLease(owner)
            try:
                self.cache.set(
                    self._owner_key(run_id),
                    owner.model_dump_json(),
                    ex=OWNER_TTL_SECONDS,
                )
            except Exception:
                with get_session_with_tenant(tenant_id=self.tenant_id) as session:
                    release_checkpoint_claim__no_commit(
                        session, saved.message_id, checkpoint.revision
                    )
                    session.commit()
                raise
        with self._lock:
            self._leases[run_id] = lease
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
                self.abort_start(run_id)
            except Exception:
                logger.exception("Response reconstruction rollback failed")
            raise
