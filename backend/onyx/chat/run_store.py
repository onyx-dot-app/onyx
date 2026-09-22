"""Live response ownership and explicit, safe checkpoint transfer across API pods."""

import os
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from uuid import UUID, uuid4

from pydantic import BaseModel

from onyx.agents.checkpoint import CheckpointBinding
from onyx.agents.concurrency import OPERATION_TIMEOUT_SECONDS
from onyx.agents.coordination import AgentCoordinator, AgentInfo
from onyx.agents.models import AgentContext, ExecutionCheckpoint, RunSnapshot
from onyx.agents.runtime import Agent, Run, RunNotTransferable
from onyx.agents.transcript import RunStatus
from onyx.cache.interface import CacheBackend
from onyx.chat.checkpoint import restore_checkpoint_data, save_checkpoint_data
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
    save_response_progress__no_commit,
)
from onyx.db.chat_response_items import finish_checkpoint__no_commit
from onyx.db.chat_subagents import (
    load_agent_history,
    load_session_agent_metadata,
    lookup_session_agent,
)
from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR

logger = setup_logger()
OWNER_TTL_SECONDS = 60
OWNER_POLL_SECONDS = 0.25
OWNER_REFRESH_SECONDS = 10
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


class _OwnerLease:
    def __init__(self, owner: ResponseOwner) -> None:
        self.owner = owner
        self.lock = threading.Lock()
        self.released = False
        self.refreshed = time.monotonic()
        self.error: Exception | None = None


class _OwnedRun:
    def __init__(self, agent: Agent, run: Run, lease: _OwnerLease) -> None:
        self.agent = agent
        self.run = run
        self.lease = lease
        self.owner = lease.owner


class ChatRunStore:
    """Persist runs on one authorized branch. The application polls control while ownership remains."""

    def __init__(
        self,
        *,
        tenant_id: str,
        chat_session_id: UUID,
        response_id: int,
        visible_response_ids: list[int],
        cache: CacheBackend,
        on_root_complete: Callable[[RunSnapshot], None] | None = None,
        control_cache: CacheBackend | None = None,
    ) -> None:
        self.tenant_id = tenant_id
        self.chat_session_id = chat_session_id
        self.response_id = response_id
        self.visible_response_ids = set(visible_response_ids) | {response_id}
        self.cache = cache
        self.control_cache = control_cache or cache
        self._on_root_complete = on_root_complete
        self._lock = threading.Lock()
        self._owned: dict[str, _OwnedRun] = {}
        self._claims: dict[str, ResponseOwner] = {}
        self._leases: dict[str, _OwnerLease] = {}
        self._draining: set[str] = set()
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
        resolve_agent: Callable[[str, str], Agent] | None = None,
    ) -> AgentCoordinator:
        if self._coordinator is not None:
            raise ValueError("Response store is already bound")
        self._build_agent = build_agent
        self._coordinator = coordinator.view(
            resolve_agent=resolve_agent,
            lookup_agent=self.lookup_agent,
            read_run=self.read_run,
            read_run_status=self.read_run_status,
            on_start=self.on_start,
            on_complete=self.on_complete,
            cancel_run=self.cancel_run,
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

    def read_run(self, run_id: str, parent_id: str) -> RunSnapshot | None:
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

    def _record(self, snapshot: RunSnapshot) -> ResponseRecord:
        registrations = self._coordinator.registrations() if self._coordinator else []
        return response_record(
            snapshot.model_copy(update={"child_runs": []}), registrations
        )

    def _save_output(self, owned: _OwnedRun, snapshot: RunSnapshot) -> int:
        record = self._record(snapshot)
        with self._ownership_lock(owned.run.id):
            self._require_owner(owned)
            with get_session_with_tenant(tenant_id=self.tenant_id) as session:
                check_checkpoint_owner__no_commit(
                    session, owned.owner.message_id, owned.owner.revision
                )
                message_id = save_response_progress__no_commit(
                    session, owned.owner.root_message_id, record
                )
                if snapshot.status.is_terminal:
                    finish_checkpoint__no_commit(session, message_id)
                session.commit()
            return message_id

    def on_start(self, agent: Agent, run: Run, _info: AgentInfo) -> Callable[[], None]:
        snapshot = run.snapshot()
        with self._lock:
            claimed = self._claims.pop(run.id, None)
            parent = self._owned.get(snapshot.parent_run_id or "")
        if parent is not None:
            self._save_output(parent, parent.run.snapshot())
        if claimed is None:
            with self._ownership_lock(run.id):
                if self._owner(run.id) is not None:
                    raise ValueError("Response already has an owner")
                with get_session_with_tenant(tenant_id=self.tenant_id) as session:
                    message_id = save_response_progress__no_commit(
                        session, self.response_id, self._record(snapshot)
                    )
                    session.commit()
                claimed = ResponseOwner(
                    token=uuid4(),
                    message_id=message_id,
                    root_message_id=self.response_id,
                )
                self.cache.set(
                    self._owner_key(run.id),
                    claimed.model_dump_json(),
                    ex=OWNER_TTL_SECONDS,
                )
        with self._ownership_lock(run.id):
            if self._owner(run.id) != claimed:
                raise RuntimeError(
                    "Response ownership was lost before execution started"
                )
        with self._lock:
            lease = self._leases.get(run.id)
            if lease is None:
                lease = _OwnerLease(claimed)
                self._leases[run.id] = lease
            owned = _OwnedRun(agent, run, lease)
            self._owned[run.id] = owned

        def abort() -> None:
            try:
                self._release_owner(run.id, lease)
            finally:
                with self._lock:
                    self._owned.pop(run.id, None)

        return abort

    @property
    def has_owned_work(self) -> bool:
        with self._lock:
            return bool(self._leases or self._draining)

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

    def on_complete(self, snapshot: RunSnapshot) -> None:
        with self._lock:
            owned = self._owned.get(snapshot.run_id)
        if owned is None:
            return
        run_id = snapshot.run_id
        with self._lock:
            self._draining.add(run_id)

        def drained() -> None:
            with self._lock:
                self._draining.discard(run_id)

        owned.run.add_idle_callback(drained)
        try:
            if (
                owned.owner.message_id == self.response_id
                and self._on_root_complete is not None
            ):
                with self._ownership_lock(snapshot.run_id):
                    self._require_owner(owned)
                    with get_session_with_tenant(tenant_id=self.tenant_id) as session:
                        check_checkpoint_owner__no_commit(
                            session, owned.owner.message_id, owned.owner.revision
                        )
                    self._on_root_complete(snapshot)
            else:
                self._save_output(owned, snapshot)
        except BaseException:
            try:
                self._release_owner(snapshot.run_id, owned.lease)
            except Exception:
                logger.exception(
                    "Response ownership cleanup failed after persistence failure"
                )
            raise
        else:
            self._release_owner(snapshot.run_id, owned.lease)
        finally:
            with self._lock:
                self._owned.pop(snapshot.run_id, None)

    def _refresh_owner(self, run_id: str, owner: ResponseOwner) -> None:
        if not self.control_cache.expire_if_value(
            self._owner_key(run_id), owner.model_dump_json().encode(), OWNER_TTL_SECONDS
        ):
            raise RuntimeError("Response ownership was lost")

    @contextmanager
    def _renew_during_reconstruction(
        self, run_id: str, owner: ResponseOwner
    ) -> Iterator[Callable[[], None]]:
        lease = _OwnerLease(owner)
        with self._lock:
            self._leases[run_id] = lease

        def finish() -> None:
            with lease.lock:
                if lease.error is not None:
                    raise RuntimeError(
                        "Response ownership failed during restoration"
                    ) from lease.error
                self._refresh_owner(run_id, owner)
                lease.refreshed = time.monotonic()

        try:
            yield finish
        except BaseException:
            with lease.lock:
                lease.released = True
            with self._lock:
                self._leases.pop(run_id, None)
            raise

    def poll_control(self) -> None:
        """Renew leases and check Stop without waiting for persistence locks."""
        with self._lock:
            leases = list(self._leases.items())
        for run_id, lease in leases:
            if not lease.lock.acquire(blocking=False):
                continue
            try:
                if lease.released or lease.error is not None:
                    continue
                try:
                    stop_requested = self.control_cache.exists(self._stop_key(run_id))
                    now = time.monotonic()
                    if now - lease.refreshed >= OWNER_REFRESH_SECONDS:
                        self._refresh_owner(run_id, lease.owner)
                        lease.refreshed = now
                except Exception as error:
                    lease.error = error
                    stop_requested = True
                    logger.exception("Response ownership control failed")
            finally:
                lease.lock.release()
            with self._lock:
                owned = self._owned.get(run_id)
            if stop_requested and owned is not None:
                owned.run.cancel()

    def release(self, run_id: str, *, coordinator: AgentCoordinator) -> None:
        """Publish a safe checkpoint. Approval delivery is an application concern."""
        with self._lock:
            owned = self._owned[run_id]
        if owned.run.status != RunStatus.SUSPENDED or not owned.run.wait_for_idle(
            timeout=OPERATION_TIMEOUT_SECONDS
        ):
            raise ValueError("Response must be suspended and idle before transfer")
        published = False
        try:
            captured = owned.agent.capture()
            progress = captured.snapshot.progress
            if progress is None:
                raise RunNotTransferable("Response has no saved execution progress")
            for child_id in progress.child_run_ids:
                if not self.read_run_status(child_id, owned.agent.id).is_terminal:
                    raise RunNotTransferable(
                        "Child responses must be saved before parent transfer"
                    )
            self._with_tenant(
                lambda: persist_checkpoint_files(
                    captured, session_id=self.chat_session_id
                )
            )
            record = self._record(captured.snapshot)
            data = save_checkpoint_data(
                captured, record, self._binding(owned.owner.message_id)
            )
            with self._ownership_lock(run_id):
                self._require_owner(owned)
                with get_session_with_tenant(tenant_id=self.tenant_id) as session:
                    check_checkpoint_owner__no_commit(
                        session, owned.owner.message_id, owned.owner.revision
                    )
                    save_response_progress__no_commit(
                        session,
                        owned.owner.root_message_id,
                        record.model_copy(update={"status": RunStatus.RUNNING}),
                    )
                    saved = read_response__no_commit(session, run_id)
                    if saved is None:
                        raise ValueError("Response is unavailable")
                    restore_checkpoint_data(
                        data,
                        saved.response,
                        captured.context,
                        self._binding(owned.owner.message_id),
                    )
                    session.commit()
            with owned.lease.lock:
                self._refresh_owner(run_id, owned.owner)
                owned.lease.refreshed = time.monotonic()
            transferred = owned.agent.handoff(
                remote_cancel=lambda: self.cancel_run(
                    run_id, self._load(run_id).agent.parent_id or ""
                )
            )
            if transferred.snapshot.revision != captured.snapshot.revision:
                raise RunNotTransferable(
                    "Response changed while preparing its checkpoint"
                )
            with self._ownership_lock(run_id):
                self._require_owner(owned)
                with get_session_with_tenant(tenant_id=self.tenant_id) as session:
                    check_checkpoint_owner__no_commit(
                        session, owned.owner.message_id, owned.owner.revision
                    )
                    publish_checkpoint__no_commit(
                        session,
                        owned.owner.message_id,
                        data,
                        expected_revision=owned.owner.revision,
                    )
                    session.commit()
                    published = True
                with owned.lease.lock:
                    owned.lease.released = True
                    self.cache.delete(self._owner_key(run_id))
        except Exception:
            if owned.run.is_remote:
                try:
                    if not published:
                        with self._ownership_lock(run_id):
                            if self._owner(run_id) == owned.owner:
                                self.cache.delete(self._owner_key(run_id))
                                with get_session_with_tenant(
                                    tenant_id=self.tenant_id
                                ) as session:
                                    interrupt_response__no_commit(
                                        session, owned.owner.message_id
                                    )
                                    session.commit()
                except Exception:
                    logger.exception("Failed to record interrupted checkpoint transfer")
                finally:
                    with owned.lease.lock:
                        owned.lease.released = True
                    with self._lock:
                        self._leases.pop(run_id, None)
                        self._owned.pop(run_id, None)
                    coordinator.view(
                        read_run=self.read_run, read_run_status=self.read_run_status
                    ).transfer(owned.run)
            raise
        with owned.lease.lock:
            owned.lease.released = True
        with self._lock:
            self._leases.pop(run_id, None)
            self._owned.pop(run_id, None)
        coordinator.view(
            read_run=self.read_run, read_run_status=self.read_run_status
        ).transfer(owned.run)

    def resume(self, run_id: str, *, context: AgentContext) -> Run | None:
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
        try:
            with self._renew_during_reconstruction(
                run_id, owner
            ) as finish_reconstruction:
                captured = restore_checkpoint_data(
                    checkpoint.data,
                    saved.response,
                    context,
                    self._binding(saved.message_id),
                )
                agent = self._with_tenant(lambda: build_agent(captured))
                self._coordinator.register(saved.agent)
                for info in self.discovery():
                    self._coordinator.register(info)
                with self._lock:
                    self._claims[run_id] = owner

                def on_start(
                    agent: Agent, run: Run, info: AgentInfo
                ) -> Callable[[], None]:
                    if run.id == run_id:
                        finish_reconstruction()
                    return self.on_start(agent, run, info)

                coordinator = self._coordinator.view(on_start=on_start)
                return self._with_tenant(
                    lambda: agent.resume(captured.snapshot, coordinator=coordinator)
                )
        except Exception:
            with self._lock:
                self._claims.pop(run_id, None)
            with self._ownership_lock(run_id):
                if self._owner(run_id) == owner:
                    with get_session_with_tenant(tenant_id=self.tenant_id) as session:
                        release_checkpoint_claim__no_commit(
                            session, saved.message_id, checkpoint.revision
                        )
                        session.commit()
                    self.cache.delete(self._owner_key(run_id))
            raise
