import threading
import time
from collections.abc import Callable, Generator
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask

from ee.onyx.server.log_export.collection import (
    build_log_zip,
    get_default_log_directories,
)
from ee.onyx.server.log_export.models import (
    LogExportManifest,
    LogExportStartResponse,
    LogExportState,
    LogExportStatusResponse,
)
from ee.onyx.server.log_export.storage import (
    LOG_EXPORT_COLLECTION_DEADLINE,
    build_export_bundle,
    collect_logs_into_file_store,
    derive_export_state,
    read_export_snapshot,
    save_manifest,
)
from onyx import __version__
from onyx.auth.permissions import require_permission
from onyx.background.celery.versioned_apps.client import app as client_app
from onyx.configs.constants import (
    OnyxCeleryPriority,
    OnyxCeleryQueues,
    OnyxCeleryTask,
)
from onyx.db.enums import Permission
from onyx.db.models import User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.constants import STANDARD_CHUNK_SIZE
from onyx.utils.logger import setup_logger
from shared_configs.configs import MULTI_TENANT

logger = setup_logger()

router = APIRouter()

API_SERVER_SCOPE_NOTE = (
    "Scope: this export contains log files from the api_server container only. "
    "Logs from background workers and other services are not included; use "
    "'docker logs <container>' or 'kubectl logs <pod>' to retrieve those."
)


class _ExpiringLock:
    """Non-blocking lock whose hold expires after a TTL.

    Guards against leaked holds: release hooks tied to the response lifecycle
    are skipped by Starlette on some exit paths (a body iterator raising, or
    client disconnects under ASGI >= 2.4), so a plain ``threading.Lock`` could
    stay held until process restart. Expiry bounds any such leak.

    ``try_acquire`` returns a token; ``release`` is a no-op unless the token
    belongs to the current hold, so a stale holder (or a duplicate call from a
    second cleanup hook) can never release a successor's hold.
    """

    def __init__(
        self, ttl_seconds: float, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._ttl_seconds = ttl_seconds
        self._clock = clock
        self._mutex = threading.Lock()
        self._current_token = 0
        self._held_until: float | None = None

    def try_acquire(self) -> int | None:
        """Returns a release token, or None if held and not yet expired."""
        with self._mutex:
            now = self._clock()
            if self._held_until is not None and now < self._held_until:
                return None
            self._current_token += 1
            self._held_until = now + self._ttl_seconds
            return self._current_token

    def release(self, token: int) -> None:
        """Releases the hold identified by ``token``; stale tokens are ignored."""
        with self._mutex:
            if token == self._current_token:
                self._held_until = None

    def held(self) -> bool:
        """Returns whether an unexpired hold exists."""
        with self._mutex:
            return self._held_until is not None and self._clock() < self._held_until


# Serializes exports process-wide: each one burns seconds of CPU on compression
# and holds a temp file until streaming ends, and concurrent exports of the same
# logs are pure waste. The TTL comfortably exceeds build time plus a slow
# streaming session (nginx's ``proxy_read_timeout`` defaults to 300s of idle).
_EXPORT_LOCK_TTL_SECONDS = 15 * 60
_EXPORT_LOCK = _ExpiringLock(ttl_seconds=_EXPORT_LOCK_TTL_SECONDS)


@router.get("/admin/log-export/download")
def download_api_server_logs(
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
) -> StreamingResponse:
    if MULTI_TENANT:
        raise OnyxError(
            OnyxErrorCode.SINGLE_TENANT_ONLY,
            "Log export is only available on self-hosted deployments.",
        )

    token = _EXPORT_LOCK.try_acquire()
    if token is None:
        raise OnyxError(
            OnyxErrorCode.RATE_LIMITED,
            "A log export is already in progress. Try again once it completes.",
        )

    handed_off = False
    try:
        # The archive is fully materialized before streaming, so its exact size
        # is known and an explicit Content-Length can be sent.
        built = build_log_zip(get_default_log_directories(), API_SERVER_SCOPE_NOTE)
        zip_buffer = built.zip_buffer

        def cleanup() -> None:
            # Wired to both the generator's ``finally`` and the response
            # background task because neither alone covers every exit path:
            # Starlette skips background tasks when the body iterator raises
            # (and on client disconnects under ASGI >= 2.4), while a generator
            # ``finally`` never runs if the generator is closed before its first
            # iteration. Double invocation is safe: ``close`` tolerates repeats
            # and ``release`` ignores stale or duplicate tokens.
            try:
                zip_buffer.close()
            finally:
                _EXPORT_LOCK.release(token)

        def iter_zip() -> Generator[bytes, None, None]:
            try:
                while chunk := zip_buffer.read(STANDARD_CHUNK_SIZE):
                    yield chunk
            finally:
                cleanup()

        timestamp = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d_%H-%M-%S")
        response = StreamingResponse(
            content=iter_zip(),
            media_type="application/zip",
            headers={
                "Content-Disposition": (
                    f"attachment; filename=onyx_api_server_logs_{timestamp}.zip"
                ),
                "Content-Length": str(built.size_bytes),
            },
            background=BackgroundTask(cleanup),
        )
        handed_off = True
        return response
    finally:
        # Once the response exists, its cleanup hooks own the release; until
        # then, any exit (including BaseException) releases here.
        if not handed_off:
            _EXPORT_LOCK.release(token)


API_SERVER_WORKER_NAME = "api_server"

# One collector task per worker type, each routed to a queue that worker
# consumes (queue assignments in ``backend/supervisord.conf``).
WORKER_COLLECT_QUEUES: dict[str, str] = {
    "primary": OnyxCeleryQueues.PRIMARY,
    "light": OnyxCeleryQueues.VESPA_METADATA_SYNC,
    "heavy": OnyxCeleryQueues.CSV_GENERATION,
    "docprocessing": OnyxCeleryQueues.DOCPROCESSING,
    "docfetching": OnyxCeleryQueues.CONNECTOR_DOC_FETCHING,
    "user_file_processing": OnyxCeleryQueues.USER_FILE_PROCESSING,
    "scheduled_tasks": OnyxCeleryQueues.SCHEDULED_TASKS,
    "monitoring": OnyxCeleryQueues.MONITORING,
}

# Serializes export starts. A successful start holds it until the status
# endpoint first observes that export ready, or failing that (nobody polls, or
# the poll lands on another replica) until the TTL expires at the collection
# deadline. A failed start releases it immediately.
_ASYNC_EXPORT_LOCK = _ExpiringLock(
    ttl_seconds=LOG_EXPORT_COLLECTION_DEADLINE.total_seconds()
)

# The export currently holding the lock, as an ``(export_id, token)`` pair.
# Never cleared, only overwritten by the next start: releasing a stale token is
# a no-op, so a leftover pair is harmless.
_ACTIVE_EXPORT: tuple[str, int] | None = None


def _release_export_slot_if_active(export_id: str) -> None:
    """Frees the export slot early once the given export is observed ready.

    Best-effort: only the process that started the export holds the pair, so a
    poll served by another replica falls back to the lock's TTL expiry.
    """
    active = _ACTIVE_EXPORT
    if active is None or active[0] != export_id:
        return
    _ASYNC_EXPORT_LOCK.release(active[1])


@router.post("/admin/log-export")
def start_log_export(
    user: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
) -> LogExportStartResponse:
    """
    Starts an export: fans out one collector task per worker type, collects the
    api_server's logs inline, and returns the export ID to poll.

    Fan-out failures (e.g. deployments with no broker or workers, like the
    onyx-lite overlay) degrade the export to just the api_server's logs instead
    of failing.
    """
    if MULTI_TENANT:
        raise OnyxError(
            OnyxErrorCode.SINGLE_TENANT_ONLY,
            "Log export is only available on self-hosted deployments.",
        )

    token = _ASYNC_EXPORT_LOCK.try_acquire()
    if token is None:
        raise OnyxError(
            OnyxErrorCode.RATE_LIMITED,
            "A log export is already in progress. Try again once it completes.",
        )

    global _ACTIVE_EXPORT

    started = False
    try:
        now = datetime.now(tz=timezone.utc)
        export_id = uuid4().hex
        deadline = now + LOG_EXPORT_COLLECTION_DEADLINE
        _ACTIVE_EXPORT = (export_id, token)

        # Fan out before the inline collection below so workers get the full
        # window before ``expires=`` discards their tasks, and their collection
        # overlaps the api_server's.
        enqueued_worker_names: list[str] = []
        for worker_name, queue in WORKER_COLLECT_QUEUES.items():
            try:
                client_app.send_task(
                    OnyxCeleryTask.EXPORT_LOGS_COLLECT_TASK,
                    priority=OnyxCeleryPriority.HIGHEST,
                    queue=queue,
                    expires=deadline,
                    kwargs={
                        "export_id": export_id,
                        "worker_name": worker_name,
                    },
                )
            except Exception as e:
                # All sends share one broker, so the first failure means the
                # rest would fail too. Only the workers already enqueued are
                # awaited.
                logger.warning(
                    "Log export fan-out failed while enqueueing %s; continuing "
                    "with %s: %s",
                    worker_name,
                    enqueued_worker_names,
                    e,
                )
                break
            enqueued_worker_names.append(worker_name)

        manifest = LogExportManifest(
            export_id=export_id,
            created_at=now,
            deadline=deadline,
            requester_email=user.email,
            onyx_version=__version__,
            worker_names=[API_SERVER_WORKER_NAME, *enqueued_worker_names],
        )
        save_manifest(manifest)

        # No celery worker runs in the api_server container, so its logs are
        # collected inline.
        collect_logs_into_file_store(
            export_id=export_id,
            worker_name=API_SERVER_WORKER_NAME,
            log_directories=get_default_log_directories(),
        )

        started = True
        return LogExportStartResponse(export_id=export_id)
    finally:
        # A failed start must not hold the export slot for the rest of the TTL;
        # any exit before success (including BaseException) releases.
        if not started:
            _ASYNC_EXPORT_LOCK.release(token)


# Declared after the sync ``/admin/log-export/download`` route above so that
# literal path keeps matching before ``{export_id}``.
@router.get("/admin/log-export/{export_id}")
def get_log_export_status(
    export_id: str,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
) -> LogExportStatusResponse:
    """Reports collection progress, derived from stored receipts."""
    snapshot = read_export_snapshot(export_id)
    if snapshot is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Log export not found.")

    state = derive_export_state(snapshot, now=datetime.now(tz=timezone.utc))
    if state is LogExportState.READY:
        _release_export_slot_if_active(export_id)

    reported = {receipt.worker_name for receipt in snapshot.receipts}
    return LogExportStatusResponse(
        export_id=export_id,
        state=state,
        created_at=snapshot.manifest.created_at,
        deadline=snapshot.manifest.deadline,
        receipts=snapshot.receipts,
        pending_worker_names=[
            worker_name
            for worker_name in snapshot.manifest.worker_names
            if worker_name not in reported
        ],
    )


@router.get("/admin/log-export/{export_id}/download")
def download_log_export(
    export_id: str,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
) -> StreamingResponse:
    """Streams the bundle of whatever pieces have arrived so far.

    Callers normally wait for the status endpoint to report ``ready``, but
    downloading earlier is allowed and simply bundles fewer pieces.
    """
    snapshot = read_export_snapshot(export_id)
    if snapshot is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Log export not found.")

    built = build_export_bundle(snapshot)
    zip_buffer = built.zip_buffer

    def cleanup() -> None:
        # Wired to both the generator's ``finally`` and the response background
        # task, matching ``download_api_server_logs``; ``close`` tolerates
        # repeats. No lock is involved here.
        zip_buffer.close()

    def iter_zip() -> Generator[bytes, None, None]:
        try:
            while chunk := zip_buffer.read(STANDARD_CHUNK_SIZE):
                yield chunk
        finally:
            cleanup()

    timestamp = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d_%H-%M-%S")
    return StreamingResponse(
        content=iter_zip(),
        media_type="application/zip",
        headers={
            "Content-Disposition": f"attachment; filename=onyx_logs_{timestamp}.zip",
            "Content-Length": str(built.size_bytes),
        },
        background=BackgroundTask(cleanup),
    )
