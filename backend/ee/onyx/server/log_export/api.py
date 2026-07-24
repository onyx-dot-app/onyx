import os
from collections.abc import Generator
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

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


@router.get("/admin/log-export/download")
def download_api_server_logs(
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
) -> StreamingResponse:
    if MULTI_TENANT:
        raise OnyxError(
            OnyxErrorCode.SINGLE_TENANT_ONLY,
            "Log export is only available on self-hosted deployments.",
        )

    zip_buffer = build_log_zip(get_default_log_directories(), API_SERVER_SCOPE_NOTE)

    # The archive is fully materialized before streaming, so its exact size is
    # known and an explicit Content-Length can be sent.
    zip_buffer.seek(0, os.SEEK_END)
    zip_size = zip_buffer.tell()
    zip_buffer.seek(0)

    def iter_zip() -> Generator[bytes, None, None]:
        try:
            while chunk := zip_buffer.read(STANDARD_CHUNK_SIZE):
                yield chunk
        finally:
            zip_buffer.close()

    timestamp = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d_%H-%M-%S")
    return StreamingResponse(
        content=iter_zip(),
        media_type="application/zip",
        headers={
            "Content-Disposition": (
                f"attachment; filename=onyx_api_server_logs_{timestamp}.zip"
            ),
            "Content-Length": str(zip_size),
        },
    )
