"""File-store layout and lifecycle for admin log exports.

All state for one export lives under ``log_export/{export_id}/`` in the
default file store: one ``piece_{hostname}.zip`` per container plus one
``receipt_{worker_name}.json`` per fanned-out worker. Shared by the collector
celery tasks and the log-export API endpoints.
"""

import os
import socket
import zipfile
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path

from ee.onyx.server.log_export.collection import README_FILE_NAME, build_log_zip
from ee.onyx.server.log_export.models import LogExportReceipt, LogExportReceiptStatus
from onyx.configs.constants import FileOrigin
from onyx.file_store.file_store import get_default_file_store
from onyx.utils.logger import setup_logger

logger = setup_logger()

LOG_EXPORT_FILE_ID_PREFIX = "log_export/"

# How long export artifacts (pieces and receipts) stay in the file store
# before the hourly cleanup task deletes them.
LOG_EXPORT_RETENTION = timedelta(hours=12)

ZIP_FILE_TYPE = "application/zip"
JSON_FILE_TYPE = "application/json"


def export_file_id_prefix(export_id: str) -> str:
    """Returns the file-ID prefix shared by all artifacts of one export."""
    return f"{LOG_EXPORT_FILE_ID_PREFIX}{export_id}/"


def piece_file_id(export_id: str, hostname: str) -> str:
    """Returns the file ID of the log zip collected from the given host."""
    return f"{export_file_id_prefix(export_id)}piece_{hostname}.zip"


def receipt_file_id(export_id: str, worker_name: str) -> str:
    """Returns the file ID of the given worker's collection receipt."""
    return f"{export_file_id_prefix(export_id)}receipt_{worker_name}.json"


def collect_logs_into_file_store(
    export_id: str,
    worker_name: str,
    log_directories: Sequence[Path],
    shallow_log_directories: Sequence[Path] = (),
) -> LogExportReceipt:
    """Zips this host's log files into the file store and writes a receipt.

    Uploads ``piece_{hostname}.zip`` unless a piece for this hostname already
    exists or no log files were found. The existence check is best-effort
    dedupe: collectors fanned out simultaneously to worker types sharing a
    container can all pass it and redundantly upload the same piece (harmless,
    since ``save_file`` upserts), each reporting ``UPLOADED``.

    Writes ``receipt_{worker_name}.json`` recording the outcome, including a
    ``FAILED`` receipt when collection raises. Receipts mean "this worker
    reported"; consumers must discover pieces by listing the export's file-ID
    prefix. A receipt can still be missing entirely (e.g. unreachable file
    store), so export readiness must also be bounded by a deadline.

    Args:
        export_id: Export this collection belongs to; determines the file-ID
            prefix all artifacts are written under.
        worker_name: Worker type this collector runs as, recorded in the
            receipt and its file ID.
        log_directories: Directories searched recursively for log files.
        shallow_log_directories: Directories searched without recursing, per
            ``build_log_zip``.

    Returns:
        The receipt that was written.
    """
    hostname = socket.gethostname()
    file_store = get_default_file_store()

    status: LogExportReceiptStatus
    file_count = 0
    size_bytes = 0
    error: str | None = None

    try:
        piece_id = piece_file_id(export_id, hostname)
        existing_file_ids = {
            record.file_id
            for record in file_store.list_files_by_prefix(
                export_file_id_prefix(export_id)
            )
        }
        if piece_id in existing_file_ids:
            status = LogExportReceiptStatus.DUPLICATE_HOST
        else:
            scope_note = (
                f"Scope: log files from host {hostname}, collected by the "
                f"{worker_name} worker."
            )
            if shallow_log_directories:
                scope_note += (
                    " May include top-level system logs from the container image."
                )
            zip_buffer = build_log_zip(
                log_directories,
                scope_note,
                shallow_log_directories=shallow_log_directories,
            )
            try:
                with zipfile.ZipFile(zip_buffer) as zip_file:
                    file_count = sum(
                        1 for name in zip_file.namelist() if name != README_FILE_NAME
                    )
                if file_count == 0:
                    status = LogExportReceiptStatus.NO_LOGS_FOUND
                else:
                    zip_buffer.seek(0, os.SEEK_END)
                    size_bytes = zip_buffer.tell()
                    zip_buffer.seek(0)
                    file_store.save_file(
                        content=zip_buffer,
                        display_name=f"piece_{hostname}.zip",
                        file_origin=FileOrigin.LOG_EXPORT,
                        file_type=ZIP_FILE_TYPE,
                        file_id=piece_id,
                    )
                    status = LogExportReceiptStatus.UPLOADED
            finally:
                zip_buffer.close()
    except Exception as e:
        logger.exception(
            "Log export collection failed: export_id=%s worker_name=%s",
            export_id,
            worker_name,
        )
        status = LogExportReceiptStatus.FAILED
        error = str(e)
        file_count = 0
        size_bytes = 0

    receipt = LogExportReceipt(
        export_id=export_id,
        worker_name=worker_name,
        hostname=hostname,
        status=status,
        file_count=file_count,
        size_bytes=size_bytes,
        collected_at=datetime.now(tz=timezone.utc),
        error=error,
    )
    file_store.save_file(
        content=BytesIO(receipt.model_dump_json(indent=2).encode("utf-8")),
        display_name=f"receipt_{worker_name}.json",
        file_origin=FileOrigin.LOG_EXPORT,
        file_type=JSON_FILE_TYPE,
        file_id=receipt_file_id(export_id, worker_name),
    )
    return receipt


def delete_expired_log_exports() -> int:
    """Deletes log-export artifacts older than ``LOG_EXPORT_RETENTION``.

    Returns:
        The number of file records deleted.
    """
    cutoff = datetime.now(tz=timezone.utc) - LOG_EXPORT_RETENTION
    file_store = get_default_file_store()
    deleted_count = 0
    for record in file_store.list_files_by_prefix(LOG_EXPORT_FILE_ID_PREFIX):
        if record.created_at >= cutoff:
            continue
        file_store.delete_file(record.file_id, error_on_missing=False)
        deleted_count += 1
    if deleted_count:
        logger.info("Deleted %d expired log-export files", deleted_count)
    return deleted_count
