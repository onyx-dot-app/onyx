import os
import threading
import time
from collections.abc import Callable, Generator
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask

from ee.onyx.server.log_export.collection import (
    build_log_zip,
    get_default_log_directories,
)
from onyx.auth.permissions import require_permission
from onyx.db.enums import Permission
from onyx.db.models import User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.constants import STANDARD_CHUNK_SIZE
from shared_configs.configs import MULTI_TENANT

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
        zip_buffer = build_log_zip(get_default_log_directories(), API_SERVER_SCOPE_NOTE)

        # The archive is fully materialized before streaming, so its exact size
        # is known and an explicit Content-Length can be sent.
        zip_buffer.seek(0, os.SEEK_END)
        zip_size = zip_buffer.tell()
        zip_buffer.seek(0)

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
                "Content-Length": str(zip_size),
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
