import os
import threading
from collections.abc import Generator
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

# Serializes exports process-wide: each one burns seconds of CPU on compression
# and holds a temp file until streaming ends, and concurrent exports of the same
# logs are pure waste.
_EXPORT_LOCK = threading.Lock()


@router.get("/admin/log-export/download")
def download_api_server_logs(
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
) -> StreamingResponse:
    if MULTI_TENANT:
        raise OnyxError(
            OnyxErrorCode.SINGLE_TENANT_ONLY,
            "Log export is only available on self-hosted deployments.",
        )

    if not _EXPORT_LOCK.acquire(blocking=False):
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

        def iter_zip() -> Generator[bytes, None, None]:
            while chunk := zip_buffer.read(STANDARD_CHUNK_SIZE):
                yield chunk

        def cleanup() -> None:
            # Runs after the response ends on every path: streamed fully, client
            # disconnected mid-stream, or disconnected before the first chunk. A
            # ``finally`` in ``iter_zip`` would be skipped on the last path,
            # since closing a never-started generator does not execute its body.
            try:
                zip_buffer.close()
            finally:
                _EXPORT_LOCK.release()

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
        # Once the response exists, its background task owns releasing the
        # lock; until then, any exit (including BaseException) releases here.
        if not handed_off:
            _EXPORT_LOCK.release()
