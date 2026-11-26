"""Container implementation of `HarnessSandbox`: one container per user
sandbox, without KVM. A `ContainerRuntime` runs it: a Kubernetes pod
(`PodRuntime`) or a Docker container on Compose (`DockerRuntime`).

The shared guest daemon logic is `DaemonHarnessSandbox`; this module adds
the container hooks. A call finds the sandbox's container record and checks
the daemon (Health); else, under the sandbox's container lock, it starts the
daemon again (a new generation: Init) or creates a new container (a new
attempt, with a new key and TLS certificate). Sessions save to and restore
from the file store through the daemon (`FileStoreSessionTransfer`). A
Celery sweep stops idle containers after it saves their sessions
(`stop_if_idle`) and deletes containers that no record names
(`sweep`).
"""

import time
from datetime import UTC, datetime
from enum import Enum
from uuid import UUID

from onyx.cache.factory import get_cache_backend
from onyx.cache.interface import CacheBackend, CacheLock, CacheLockLostError
from onyx.microvm.agent_client import HostAgentError
from onyx.microvm.configs import SANDBOX_FC_TURN_END_SAVE_INTERVAL_SECONDS
from onyx.microvm.daemon_client import SandboxDaemonClient, SandboxDaemonError
from onyx.microvm.models import DaemonHealth
from onyx.microvm.registry import (
    clear_sandbox_daemon_key,
    get_sandbox_daemon_key,
    set_sandbox_daemon_key,
)
from onyx.server.features.build.configs import (
    SANDBOX_HARNESS_IDLE_TIMEOUT_SECONDS,
    SANDBOX_HARNESS_START_TIMEOUT_SECONDS,
    SANDBOX_RESOURCE_GRACE_SECONDS,
)
from onyx.server.features.build.sandbox.container.models import (
    ContainerRecord,
    ContainerSpec,
    ContainerState,
    RuntimeContainer,
)
from onyx.server.features.build.sandbox.container.runtime import (
    ContainerRuntime,
    container_name,
)
from onyx.server.features.build.sandbox.container.state import (
    clear_container_record,
    container_lock,
    get_container_record,
    set_container_record,
    update_container_record,
)
from onyx.server.features.build.sandbox.container.tls import (
    DaemonChannelPool,
    new_daemon_credentials,
)
from onyx.server.features.build.sandbox.container.transfer import (
    FileStoreArchives,
    FileStoreSessionTransfer,
)
from onyx.server.features.build.sandbox.daemon_harness import (
    DaemonHarnessSandbox,
    RunningInstance,
)
from onyx.server.features.build.sandbox.firecracker.harness_state import (
    last_attempt,
    mark_session_on_instance,
    note_wanted,
    record_attempt,
    sessions_on_instance,
    wanted_since,
)
from onyx.server.features.build.sandbox.firecracker.session_saves import (
    SESSION_SAVE_MAX_SECONDS,
    SessionTransfer,
    save_instance_sessions,
)
from onyx.server.features.build.sandbox.harness_base import (
    EXEC_DEFAULT_ENV,
    HarnessSandboxError,
)
from onyx.server.features.build.sandbox.models import (
    HarnessSandboxKey,
    HarnessSandboxRef,
    SandboxProvisionContentionError,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Health of a recorded daemon on each call; a slow answer takes the start
# path, which waits longer.
_HEALTH_TIMEOUT_SECONDS = 5.0
_HEALTH_POLL_SECONDS = 0.25
# The container lock's lease: longer than a start (with an image pull). A stop
# renews it for each session save.
_LOCK_LEASE_SECONDS = 10 * 60.0


class IdleStopOutcome(str, Enum):
    NOT_RUNNING = "not_running"
    NOT_IDLE = "not_idle"
    NO_SAVES = "no_saves"
    LOCKED = "locked"
    BUSY = "busy"
    # A save failed or was cancelled: the container stays.
    KEPT = "kept"
    STOPPED = "stopped"


class ContainerInstance(RunningInstance):
    """A running container daemon and the record that names it."""

    def __init__(self, record: ContainerRecord, daemon: SandboxDaemonClient) -> None:
        super().__init__(
            daemon=daemon, attempt=record.attempt, generation=record.generation
        )
        self.record = record

    @property
    def files_identity(self) -> tuple[int, int]:
        # Session files live as long as the container (Docker writable
        # layer, pod emptyDir): a daemon restart keeps them.
        return (self.attempt, 0)


class ContainerHarnessSandbox(DaemonHarnessSandbox[ContainerInstance]):
    def __init__(
        self,
        *,
        runtime: ContainerRuntime,
        archives: FileStoreArchives | None,
        idle_timeout_seconds: int = SANDBOX_HARNESS_IDLE_TIMEOUT_SECONDS,
        start_timeout_seconds: float = SANDBOX_HARNESS_START_TIMEOUT_SECONDS,
        turn_end_save_interval_seconds: int = SANDBOX_FC_TURN_END_SAVE_INTERVAL_SECONDS,
        orphan_grace_seconds: int = SANDBOX_RESOURCE_GRACE_SECONDS,
    ) -> None:
        super().__init__(
            archive_store=archives,
            turn_end_save_interval_seconds=turn_end_save_interval_seconds,
        )
        self.runtime = runtime
        # None: no session saves, so no idle stop.
        self._file_archives = archives
        self._idle_timeout = idle_timeout_seconds
        self._start_timeout = start_timeout_seconds
        self._orphan_grace = orphan_grace_seconds
        self._channels = DaemonChannelPool()

    # Daemon

    def _daemon(
        self, tenant_cache: CacheBackend, sandbox_id: UUID, record: ContainerRecord
    ) -> SandboxDaemonClient | None:
        key = get_sandbox_daemon_key(tenant_cache, sandbox_id, attempt=record.attempt)
        if key is None:
            return None
        return SandboxDaemonClient(
            self._channels.channel(record.address, record.cert_pem),
            sandbox_id=str(sandbox_id),
            sandboxd_key=key,
        )

    def _probe(
        self, tenant_cache: CacheBackend, sandbox_id: UUID, record: ContainerRecord
    ) -> ContainerInstance | None:
        """The recorded instance when its daemon answers as it. Raises the
        daemon's errors (no answer)."""
        if record.runtime is not self.runtime.kind:
            return None
        daemon = self._daemon(tenant_cache, sandbox_id, record)
        if daemon is None:
            return None
        health = daemon.health(timeout=_HEALTH_TIMEOUT_SECONDS)
        if health.initialized and health.generation == record.generation:
            return ContainerInstance(record, daemon)
        return None

    def _wait_for_health(
        self, daemon: SandboxDaemonClient, deadline: float
    ) -> DaemonHealth | None:
        while True:
            try:
                return daemon.health(timeout=_HEALTH_TIMEOUT_SECONDS)
            except (HostAgentError, SandboxDaemonError):
                if time.monotonic() + _HEALTH_POLL_SECONDS >= deadline:
                    return None
            time.sleep(_HEALTH_POLL_SECONDS)

    def _initialize(
        self,
        tenant_cache: CacheBackend,
        sandbox_id: UUID,
        record: ContainerRecord,
        deadline: float,
    ) -> ContainerInstance | None:
        """Init the daemon as a new generation unless it runs as the
        recorded one. None when it does not answer by `deadline`. Hold the
        container lock."""
        daemon = self._daemon(tenant_cache, sandbox_id, record)
        if daemon is None:
            return None
        health = self._wait_for_health(daemon, deadline)
        if health is None:
            return None
        if health.initialized and health.generation == record.generation:
            return ContainerInstance(record, daemon)
        generation = max(record.generation, health.generation) + 1
        daemon.init(
            generation=generation,
            scratch_gib=0,
            # No secrets: the egress proxy injects them.
            env=dict(EXEC_DEFAULT_ENV),
            session_ids=[],
        )
        record = record.model_copy(
            update={"generation": generation, "last_active": int(time.time())}
        )
        set_container_record(tenant_cache, sandbox_id, record)
        logger.info(
            "sandbox_container_initialized sandbox=%s name=%s generation=%d",
            sandbox_id,
            record.name,
            generation,
        )
        return ContainerInstance(record, daemon)

    def _create(
        self, tenant_cache: CacheBackend, sandbox: HarnessSandboxKey, lock: CacheLock
    ) -> ContainerInstance:
        """A new container (the next attempt) with a new key and certificate.
        Hold the container lock. The start budget begins after the image
        pull, which can take minutes."""
        sandbox_id = sandbox.sandbox_id
        self.runtime.prepare()
        _renew_lock(lock, _LOCK_LEASE_SECONDS)
        deadline = time.monotonic() + self._start_timeout
        attempt = last_attempt(tenant_cache, sandbox_id) + 1
        record_attempt(tenant_cache, sandbox_id, attempt)
        credentials = new_daemon_credentials()
        set_sandbox_daemon_key(
            tenant_cache, sandbox_id, attempt=attempt, key=credentials.key
        )
        name = container_name(sandbox_id, attempt)
        try:
            address = self.runtime.create(
                ContainerSpec(
                    tenant_id=sandbox.tenant_id,
                    sandbox_id=sandbox_id,
                    attempt=attempt,
                    name=name,
                ),
                credentials,
                deadline,
            )
            record = ContainerRecord(
                runtime=self.runtime.kind,
                name=name,
                address=address,
                attempt=attempt,
                generation=0,
                cert_pem=credentials.cert_pem,
                last_active=int(time.time()),
            )
            # Before Init: the orphan sweep keeps a container with a record.
            set_container_record(tenant_cache, sandbox_id, record)
            instance = self._initialize(tenant_cache, sandbox_id, record, deadline)
            if instance is None:
                raise HarnessSandboxError(
                    "The sandbox started, but its daemon did not answer in time. "
                    "Run the call again."
                )
        except BaseException:
            self._discard(tenant_cache, sandbox_id, name, attempt)
            raise
        return instance

    def _discard(
        self, tenant_cache: CacheBackend, sandbox_id: UUID, name: str, attempt: int
    ) -> None:
        """Delete a container and its records; a failed delete leaves an
        orphan for the sweep."""
        try:
            self.runtime.delete(name)
        except Exception:
            logger.warning(
                "sandbox_container_delete_failed name=%s", name, exc_info=True
            )
        clear_container_record(tenant_cache, sandbox_id, name=name)
        clear_sandbox_daemon_key(tenant_cache, sandbox_id, attempt=attempt)

    def _start(
        self, tenant_cache: CacheBackend, sandbox: HarnessSandboxKey
    ) -> ContainerInstance:
        sandbox_id = sandbox.sandbox_id
        lock = container_lock(tenant_cache, sandbox_id, _LOCK_LEASE_SECONDS)
        if not lock.acquire(blocking_timeout=self._start_timeout):
            raise SandboxProvisionContentionError(
                f"sandbox {sandbox_id} is starting or stopping on another worker"
            )
        try:
            deadline = time.monotonic() + self._start_timeout
            record = get_container_record(tenant_cache, sandbox_id)
            if record is not None and record.runtime is not self.runtime.kind:
                # Another backend's record: its sandbox stopped there.
                clear_container_record(tenant_cache, sandbox_id, name=record.name)
                record = None
            if record is not None:
                try:
                    instance = self._probe(tenant_cache, sandbox_id, record)
                except (HostAgentError, SandboxDaemonError):
                    instance = None
                if instance is not None:
                    return instance
                found = self.runtime.inspect(record.name)
                if found is not None and found.state is ContainerState.RUNNING:
                    record = (
                        self._moved(tenant_cache, sandbox_id, record, found) or record
                    )
                    instance = self._initialize(
                        tenant_cache, sandbox_id, record, deadline
                    )
                    if instance is not None:
                        return instance
                logger.info(
                    "sandbox_container_replaced sandbox=%s name=%s",
                    sandbox_id,
                    record.name,
                )
                self._discard(tenant_cache, sandbox_id, record.name, record.attempt)
            return self._create(tenant_cache, sandbox, lock)
        finally:
            if lock.owned():
                lock.release()

    # Hooks

    def _instance(self, sandbox: HarnessSandboxKey) -> ContainerInstance:
        tenant_cache = get_cache_backend(tenant_id=sandbox.tenant_id)
        # A stop that saves this sandbox now gives way to this call.
        note_wanted(tenant_cache, sandbox.sandbox_id)
        record = get_container_record(tenant_cache, sandbox.sandbox_id)
        if record is not None:
            try:
                instance = self._probe(tenant_cache, sandbox.sandbox_id, record)
            except (HostAgentError, SandboxDaemonError):
                instance = None
            if instance is not None:
                return instance
        return self._start(tenant_cache, sandbox)

    def _instance_if_running(
        self, tenant_cache: CacheBackend, sandbox_id: UUID
    ) -> ContainerInstance | None:
        record = get_container_record(tenant_cache, sandbox_id)
        if record is None:
            return None
        try:
            return self._probe(tenant_cache, sandbox_id, record)
        except (HostAgentError, SandboxDaemonError):
            found = self.runtime.inspect(record.name)
            if found is None or found.state is ContainerState.FAILED:
                return None
            moved = self._moved(tenant_cache, sandbox_id, record, found)
            if moved is None:
                raise
            return self._probe(tenant_cache, sandbox_id, moved)

    def _moved(
        self,
        tenant_cache: CacheBackend,
        sandbox_id: UUID,
        record: ContainerRecord,
        found: RuntimeContainer,
    ) -> ContainerRecord | None:
        """The record with the container's new address (a restart can move a
        published port); None when the address is the same."""
        if not found.address or found.address == record.address:
            return None
        moved = record.model_copy(update={"address": found.address})
        update_container_record(
            tenant_cache,
            sandbox_id,
            lambda current: moved if current.name == record.name else None,
        )
        return moved

    def _transfer(self, instance: ContainerInstance) -> SessionTransfer | None:
        if self._file_archives is None:
            return None
        return FileStoreSessionTransfer(instance.daemon, self._file_archives)

    def _mark_session_set_up(
        self,
        tenant_cache: CacheBackend,
        ref: HarnessSandboxRef,
        instance: ContainerInstance,
    ) -> None:
        lock = container_lock(tenant_cache, ref.sandbox_id, _LOCK_LEASE_SECONDS)
        if not lock.acquire(blocking_timeout=self._start_timeout):
            raise SandboxProvisionContentionError(
                f"sandbox {ref.sandbox_id} is stopping on another worker"
            )
        try:
            record = get_container_record(tenant_cache, ref.sandbox_id)
            if (
                record is None
                or record.name != instance.record.name
                or record.attempt != instance.attempt
            ):
                raise HarnessSandboxError(
                    "The sandbox stopped while this session was set up. "
                    "Run the call again."
                )
            mark_session_on_instance(
                tenant_cache, ref.sandbox_id, ref.session_id, instance.files_identity
            )
        finally:
            if lock.owned():
                lock.release()

    def _stop(
        self, tenant_id: str, tenant_cache: CacheBackend, sandbox_id: UUID
    ) -> None:
        lock = container_lock(tenant_cache, sandbox_id, _LOCK_LEASE_SECONDS)
        held = lock.acquire(blocking_timeout=self._start_timeout)
        if not held:
            # A purge does not wait for a stuck holder; the purge mark keeps
            # a container that starts after this unsaved, and the sweep
            # deletes it without a record.
            logger.warning(
                "sandbox_container_purge_without_lock tenant=%s sandbox=%s",
                tenant_id,
                sandbox_id,
            )
        try:
            record = get_container_record(tenant_cache, sandbox_id)
            if record is None or record.runtime is not self.runtime.kind:
                return
            try:
                self.runtime.delete(record.name)
            finally:
                clear_container_record(tenant_cache, sandbox_id, name=record.name)
        finally:
            if held and lock.owned():
                lock.release()

    def _forget_sandbox(self, tenant_cache: CacheBackend, sandbox_id: UUID) -> None:
        clear_container_record(tenant_cache, sandbox_id)
        clear_sandbox_daemon_key(tenant_cache, sandbox_id)

    # Activity

    def touch(self, ref: HarnessSandboxRef) -> None:
        now = int(time.time())
        update_container_record(
            get_cache_backend(tenant_id=ref.tenant_id),
            ref.sandbox_id,
            lambda record: (
                record.model_copy(update={"last_active": now})
                if record.last_active < now
                else None
            ),
        )

    # Idle stop and orphans (Celery: tasks/build/harness_containers.py)

    def stop_if_idle(self, tenant_id: str, sandbox_id: UUID) -> IdleStopOutcome:
        """Save every session, then delete the container, while it is idle
        and not busy. A call that asks for the sandbox during the saves
        cancels the stop."""
        tenant_cache = get_cache_backend(tenant_id=tenant_id)
        record = get_container_record(tenant_cache, sandbox_id)
        if record is None or record.runtime is not self.runtime.kind:
            return IdleStopOutcome.NOT_RUNNING
        if time.time() - record.last_active < self._idle_timeout:
            return IdleStopOutcome.NOT_IDLE
        if self._file_archives is None:
            return IdleStopOutcome.NO_SAVES
        lock = container_lock(tenant_cache, sandbox_id, _LOCK_LEASE_SECONDS)
        if not lock.acquire(blocking=False):
            return IdleStopOutcome.LOCKED
        try:
            record = get_container_record(tenant_cache, sandbox_id)
            if record is None:
                return IdleStopOutcome.NOT_RUNNING
            if time.time() - record.last_active < self._idle_timeout:
                return IdleStopOutcome.NOT_IDLE
            # A call that wanted the sandbox may still wait for this lock.
            since = time.time() - self._start_timeout

            def cancelled() -> bool:
                return wanted_since(tenant_cache, sandbox_id, since)

            if cancelled():
                return IdleStopOutcome.BUSY
            try:
                # Before the busy check: it waits for a restarting daemon.
                instance = self._instance_for_save(tenant_cache, sandbox_id, record)
            except Exception:
                logger.warning(
                    "sandbox_container_idle_check_failed sandbox=%s",
                    sandbox_id,
                    exc_info=True,
                )
                return IdleStopOutcome.KEPT
            if self.is_busy(tenant_id=tenant_id, sandbox_id=sandbox_id):
                return IdleStopOutcome.BUSY
            # No instance: the container is gone or failed, and its files with it.
            if instance is not None:
                transfer = self._transfer(instance)
                if transfer is None:
                    return IdleStopOutcome.NO_SAVES
                if not save_instance_sessions(
                    tenant_id,
                    tenant_cache,
                    instance.daemon,
                    transfer,
                    self._file_archives,
                    sandbox_id,
                    sessions_on_instance(
                        tenant_cache, sandbox_id, instance.files_identity
                    ),
                    cancelled=cancelled,
                    renew_lease=lambda: _renew_lock(lock, SESSION_SAVE_MAX_SECONDS),
                ):
                    return IdleStopOutcome.KEPT
                # A call, turn, approval or command that began during the saves.
                if cancelled() or self.is_busy(
                    tenant_id=tenant_id, sandbox_id=sandbox_id
                ):
                    return IdleStopOutcome.BUSY
            self._discard(tenant_cache, sandbox_id, record.name, record.attempt)
            logger.info(
                "sandbox_container_idle_stop sandbox=%s name=%s",
                sandbox_id,
                record.name,
            )
            return IdleStopOutcome.STOPPED
        finally:
            if lock.owned():
                lock.release()

    def _instance_for_save(
        self, tenant_cache: CacheBackend, sandbox_id: UUID, record: ContainerRecord
    ) -> ContainerInstance | None:
        """The container's daemon for a stop's saves. A restarted daemon is
        initialized again first: its files survived. None when the
        container is gone or failed. Hold the container lock."""
        try:
            instance = self._probe(tenant_cache, sandbox_id, record)
        except (HostAgentError, SandboxDaemonError):
            instance = None
        if instance is not None:
            return instance
        found = self.runtime.inspect(record.name)
        if found is None or found.state is ContainerState.FAILED:
            return None
        record = self._moved(tenant_cache, sandbox_id, record, found) or record
        instance = self._initialize(
            tenant_cache, sandbox_id, record, time.monotonic() + self._start_timeout
        )
        if instance is None:
            raise HarnessSandboxError(f"the daemon of {record.name} does not answer")
        return instance

    def sweep(self, deadline: float) -> list[HarnessSandboxKey]:
        """Delete containers that no record names, after the grace time, and
        return the sandboxes whose containers are idle."""
        now = datetime.now(UTC)
        idle: list[HarnessSandboxKey] = []
        for found in self.runtime.list_containers(deadline):
            if time.monotonic() >= deadline:
                break
            record = (
                None
                if found.tenant_id is None or found.sandbox_id is None
                else get_container_record(
                    get_cache_backend(tenant_id=found.tenant_id), found.sandbox_id
                )
            )
            if record is None or record.name != found.name:
                if (now - found.created_at).total_seconds() < self._orphan_grace:
                    continue
                logger.info("sandbox_container_orphan name=%s", found.name)
                try:
                    self.runtime.delete(found.name)
                except Exception:
                    logger.warning(
                        "sandbox_container_orphan_delete_failed name=%s",
                        found.name,
                        exc_info=True,
                    )
                continue
            if (
                found.tenant_id is not None
                and found.sandbox_id is not None
                and now.timestamp() - record.last_active >= self._idle_timeout
            ):
                idle.append(
                    HarnessSandboxKey(
                        tenant_id=found.tenant_id, sandbox_id=found.sandbox_id
                    )
                )
        return idle


def _renew_lock(lock: CacheLock, seconds: float) -> None:
    """Raises when the lock was lost: no later write."""
    if not lock.owned():
        raise CacheLockLostError("sandbox container lock lost")
    lock.extend(seconds)
