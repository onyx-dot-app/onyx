"""Session saves and restores for Firecracker harness sandboxes.

Save: the guest daemon archives the session directory without dependencies
and caches (CaptureSession), the node agent uploads the archive through a
presigned PUT, the file store checks it, and the new save is committed in
the cache before the old file is deleted. Restore: before a session's first
use on a new VM instance, its last save comes back through a presigned GET.

A stop saves every session of the VM first (`SessionSaveCheckpointer`) and
keeps a busy VM. The node-report idle evictor runs the save and the stop in
the background (`BackgroundIdleStop`).
"""

import abc
import threading
import time
from collections.abc import Callable, Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager
from uuid import UUID

from pydantic import SecretStr

from onyx.cache.factory import get_cache_backend, get_shared_cache_backend
from onyx.cache.interface import CacheBackend
from onyx.configs.constants import FileOrigin
from onyx.file_store.file_store import PresignableFileStore, get_default_file_store
from onyx.file_store.models import PresignedRequest as FileStorePresignedRequest
from onyx.microvm.agent_client import HostAgentClient, HostAgentClientFactory
from onyx.microvm.daemon_client import (
    SandboxDaemonClient,
    SandboxDaemonError,
    SandboxDaemonErrorReason,
)
from onyx.microvm.lifecycle import (
    SandboxActivityProbe,
    SandboxCheckpointer,
    VmStopOutcome,
)
from onyx.microvm.models import AgentVm, FileType, PresignedRequest, VmInstance
from onyx.microvm.registry import (
    get_registered_node,
    get_sandbox_daemon_key,
    get_sandbox_placement,
)
from onyx.server.features.build.sandbox.firecracker.harness_state import (
    get_session_save,
    sessions_on_instance,
    set_session_save,
)
from onyx.server.features.build.sandbox.firecracker.models import SessionSave
from onyx.server.features.build.sandbox.harness_base import HarnessSandboxError
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR

logger = setup_logger()

# Top-level directories never saved. The daemon also skips its own excludes
# (node_modules, venvs, caches) at any depth inside each root.
SAVE_EXCLUDED_ROOTS: frozenset[str] = frozenset(
    {
        "node_modules",
        ".venv",
        "venv",
        "__pycache__",
        ".next",
        ".cache",
        ".npm",
        ".pnpm-store",
        ".yarn",
        ".bun",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".turbo",
        ".parcel-cache",
    }
)
# One session's save (capture and upload, 15 min each at most) ends within
# this time. A stop renews its sandbox lock for each session.
SESSION_SAVE_MAX_SECONDS = 35 * 60.0
_ARCHIVE_FILE_TYPE = "application/zstd"
_ARCHIVE_DISPLAY_NAME = "craft-session-save.tar.zst"

_IDLE_STOP_LOCKED_RETRIES = 5
_IDLE_STOP_LOCKED_PAUSE_SECONDS = 0.2
_IDLE_STOP_WORKERS = 4


class SessionSaveError(HarnessSandboxError):
    """A session could not be saved or restored."""


class SessionArchiveStore(abc.ABC):
    """Object storage for session archives, reached by the node agent
    through presigned URLs."""

    @abc.abstractmethod
    def presign_upload(self, *, size: int, sha256: str) -> tuple[str, PresignedRequest]:
        """A pending upload ID and its PUT request."""

    @abc.abstractmethod
    def finalize(self, pending_upload_id: str) -> str:
        """Check the uploaded object; returns its file ID."""

    @abc.abstractmethod
    def presign_download(self, file_id: str) -> PresignedRequest:
        pass

    @abc.abstractmethod
    def delete(self, file_id: str) -> None:
        pass


def _agent_request(request: FileStorePresignedRequest) -> PresignedRequest:
    return PresignedRequest(
        url=SecretStr(request.url), method=request.method, headers=request.headers
    )


class FileStoreArchiveStore(SessionArchiveStore):
    """Archives in the deployment file store (S3, GCS or Azure)."""

    def __init__(self, store: PresignableFileStore) -> None:
        self._store = store

    def presign_upload(self, *, size: int, sha256: str) -> tuple[str, PresignedRequest]:
        upload = self._store.presign_upload(
            display_name=_ARCHIVE_DISPLAY_NAME,
            file_origin=FileOrigin.SANDBOX_SNAPSHOT,
            file_type=_ARCHIVE_FILE_TYPE,
            size=size,
            sha256=sha256,
        )
        return upload.pending_upload_id, _agent_request(upload.request)

    def finalize(self, pending_upload_id: str) -> str:
        return self._store.finalize_presigned_upload(pending_upload_id)

    def presign_download(self, file_id: str) -> PresignedRequest:
        return _agent_request(self._store.presign_download(file_id))

    def delete(self, file_id: str) -> None:
        self._store.delete_file(file_id, error_on_missing=False)


def default_archive_store() -> SessionArchiveStore | None:
    """None when the file store cannot sign URLs (no session saves)."""
    store = get_default_file_store()
    if isinstance(store, PresignableFileStore):
        return FileStoreArchiveStore(store)
    return None


@contextmanager
def tenant_scope(tenant_id: str) -> Iterator[None]:
    """Run file store calls in the sandbox's tenant (node reports and
    background stops have no tenant of their own)."""
    token = CURRENT_TENANT_ID_CONTEXTVAR.set(tenant_id)
    try:
        yield
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(token)


def _is_virtualenv(daemon: SandboxDaemonClient, session_id: UUID, root: str) -> bool:
    """A top-level directory with pyvenv.cfg: the daemon skips these only
    below a capture root."""
    try:
        _, chunks = daemon.read_file(
            session_id=str(session_id), path=f"{root}/pyvenv.cfg", length=1
        )
    except SandboxDaemonError as e:
        if e.reason is SandboxDaemonErrorReason.FILE_NOT_FOUND:
            return False
        raise
    for _ in chunks:
        pass
    return True


def save_session(
    cache: CacheBackend,
    agent: HostAgentClient,
    daemon: SandboxDaemonClient,
    store: SessionArchiveStore,
    instance: VmInstance,
    session_id: UUID,
) -> SessionSave:
    """Capture, upload and commit one session, then delete the old archive.
    Raises on any failure; the old save stays committed. An upload that
    fails leaves the capture on the node until it expires."""
    previous = get_session_save(cache, session_id)
    try:
        listing = daemon.list_files(session_id=str(session_id))
    except SandboxDaemonError as e:
        if e.reason is not SandboxDaemonErrorReason.FILE_NOT_FOUND:
            raise
        # No call made the session directory on this VM: nothing changed.
        if previous is not None:
            return previous
        listing = None
    if listing is not None and listing.truncated:
        # A partial list would save a partial session.
        raise SessionSaveError(f"session {session_id} has too many entries to save")
    roots = sorted(
        e.name
        for e in (listing.entries if listing is not None else [])
        if e.type is FileType.DIRECTORY
        and e.name not in SAVE_EXCLUDED_ROOTS
        and not e.name.startswith(".craft-")
        and not _is_virtualenv(daemon, session_id, e.name)
    )
    save = SessionSave(
        file_id=None, size_bytes=0, sha256="", roots=[], saved_at=time.time()
    )
    if roots:
        capture = agent.capture_session(
            instance, session_id=str(session_id), roots=roots
        )
        pending_id, request = store.presign_upload(
            size=capture.size_bytes, sha256=capture.sha256
        )
        agent.upload_capture(capture_id=capture.capture_id, request=request)
        save = save.model_copy(
            update={
                "file_id": store.finalize(pending_id),
                "size_bytes": capture.size_bytes,
                "sha256": capture.sha256,
                "roots": capture.roots,
            }
        )
    set_session_save(cache, session_id, save)
    if previous is not None and previous.file_id not in (None, save.file_id):
        try:
            store.delete(previous.file_id)
        except Exception:
            # An orphaned archive costs storage only; the new save is committed.
            logger.warning(
                "sandbox_fc_save_prune_failed session=%s", session_id, exc_info=True
            )
    logger.info(
        "sandbox_fc_session_saved session=%s bytes=%d", session_id, save.size_bytes
    )
    return save


def restore_session(
    cache: CacheBackend,
    agent: HostAgentClient,
    store: SessionArchiveStore,
    instance: VmInstance,
    session_id: UUID,
) -> None:
    """Restore a session's last save into a VM instance, if it has one."""
    save = get_session_save(cache, session_id)
    if save is None or save.file_id is None:
        return
    agent.restore_session(
        instance,
        session_id=str(session_id),
        request=store.presign_download(save.file_id),
        size_bytes=save.size_bytes,
        sha256=save.sha256,
        roots=save.roots,
    )
    logger.info(
        "sandbox_fc_session_restored session=%s bytes=%d", session_id, save.size_bytes
    )


class SessionSaveCheckpointer(SandboxCheckpointer):
    """Saves every session set up on the VM. Keeps the VM (False) when the
    sandbox is busy before or after the saves, or when a save fails."""

    save_lease_seconds = SESSION_SAVE_MAX_SECONDS

    def __init__(
        self,
        store: SessionArchiveStore,
        client_factory: HostAgentClientFactory,
        activity: SandboxActivityProbe,
    ) -> None:
        self._store = store
        self._client_factory = client_factory
        self._activity = activity

    def save_checkpoint(
        self,
        *,
        tenant_id: str,
        sandbox_id: UUID,
        vm: AgentVm,
        renew_lease: Callable[[], None],
    ) -> bool:
        if self._activity.is_busy(tenant_id=tenant_id, sandbox_id=sandbox_id):
            return False
        tenant_cache = get_cache_backend(tenant_id=tenant_id)
        placement = get_sandbox_placement(tenant_cache, sandbox_id)
        key = get_sandbox_daemon_key(tenant_cache, sandbox_id, attempt=vm.attempt)
        node = (
            None
            if placement is None
            else get_registered_node(get_shared_cache_backend(), placement.node_id)
        )
        if key is None or node is None:
            return False
        agent = self._client_factory.client(node.address)
        instance = VmInstance(
            sandbox_id=vm.sandbox_id,
            attempt=vm.attempt,
            generation=vm.generation,
            sandboxd_key=key,
        )
        daemon = SandboxDaemonClient(
            agent.channel, sandbox_id=vm.sandbox_id, sandboxd_key=key
        )
        sessions = sessions_on_instance(
            tenant_cache, sandbox_id, (vm.attempt, vm.generation)
        )
        with tenant_scope(tenant_id):
            for session_id in sessions:
                # Raises when the stop lost the lock: no later commit.
                renew_lease()
                try:
                    save_session(
                        tenant_cache, agent, daemon, self._store, instance, session_id
                    )
                except Exception:
                    # A stop needs every session saved.
                    logger.warning(
                        "sandbox_fc_session_save_failed sandbox=%s session=%s",
                        sandbox_id,
                        session_id,
                        exc_info=True,
                    )
                    return False
        # A turn, approval or command that began during the saves.
        return not self._activity.is_busy(tenant_id=tenant_id, sandbox_id=sandbox_id)


class BackgroundIdleStop(SandboxCheckpointer):
    """The node-report evictor's checkpointer. A save can take minutes, so
    it starts `stop_if_idle` in the background and keeps the VM for now."""

    def __init__(self, stop_if_idle: Callable[[str, UUID], VmStopOutcome]) -> None:
        self._stop_if_idle = stop_if_idle
        self._lock = threading.Lock()
        self._executor: ThreadPoolExecutor | None = None
        self.running: dict[UUID, Future[None]] = {}

    def save_checkpoint(
        self,
        *,
        tenant_id: str,
        sandbox_id: UUID,
        vm: AgentVm,  # noqa: ARG002
        renew_lease: Callable[[], None],  # noqa: ARG002
    ) -> bool:
        with self._lock:
            if sandbox_id not in self.running:
                if self._executor is None:
                    self._executor = ThreadPoolExecutor(
                        max_workers=_IDLE_STOP_WORKERS,
                        thread_name_prefix="fc-idle-stop",
                    )
                self.running[sandbox_id] = self._executor.submit(
                    self._run, tenant_id, sandbox_id
                )
        return False

    def _run(self, tenant_id: str, sandbox_id: UUID) -> None:
        try:
            outcome = self._stop_if_idle(tenant_id, sandbox_id)
            # The report that queued this stop holds the sandbox lock until
            # save_checkpoint returns.
            for _ in range(_IDLE_STOP_LOCKED_RETRIES):
                if outcome is not VmStopOutcome.LOCKED:
                    break
                time.sleep(_IDLE_STOP_LOCKED_PAUSE_SECONDS)
                outcome = self._stop_if_idle(tenant_id, sandbox_id)
            logger.info(
                "sandbox_fc_idle_stop sandbox=%s outcome=%s", sandbox_id, outcome.value
            )
        except Exception:
            logger.exception("sandbox_fc_idle_stop_failed sandbox=%s", sandbox_id)
        finally:
            with self._lock:
                self.running.pop(sandbox_id, None)
