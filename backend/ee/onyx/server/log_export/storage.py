"""File-store layout and lifecycle for admin log exports.

All state for one export lives under ``log_export/{export_id}/`` in the default
file store: one ``piece_{hostname}.zip`` per container plus one
``receipt_{worker_name}.json`` per fanned-out worker. Shared by the collector
celery tasks and the log-export API endpoints.
"""

import os
import shutil
import socket
import tempfile
import zipfile
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path

from ee.onyx.server.log_export.collection import (
    SENSITIVE_DATA_WARNING,
    BuiltLogZip,
    build_log_zip,
)
from ee.onyx.server.log_export.models import (
    LogExportBundleManifest,
    LogExportManifest,
    LogExportReceipt,
    LogExportReceiptStatus,
    LogExportSnapshot,
    LogExportState,
)
from onyx.configs.constants import FileOrigin
from onyx.file_store.constants import MAX_IN_MEMORY_SIZE, STANDARD_CHUNK_SIZE
from onyx.file_store.file_store import get_default_file_store
from onyx.utils.logger import setup_logger

logger = setup_logger()

LOG_EXPORT_FILE_ID_PREFIX = "log_export/"

# How long export artifacts (pieces and receipts) stay in the file store before
# the hourly cleanup task deletes them.
LOG_EXPORT_RETENTION = timedelta(hours=12)

# How long an export waits for worker receipts before reporting ``READY``
# regardless; also the ``expires=`` of the fanned-out collector tasks, so a task
# a dead worker never picked up is discarded instead of running late.
LOG_EXPORT_COLLECTION_DEADLINE = timedelta(seconds=90)

ZIP_FILE_TYPE = "application/zip"
JSON_FILE_TYPE = "application/json"

BUNDLE_README_FILE_NAME = "README.txt"
BUNDLE_MANIFEST_FILE_NAME = "manifest.json"


def export_file_id_prefix(export_id: str) -> str:
    """Returns the file-ID prefix shared by all artifacts of one export."""
    return f"{LOG_EXPORT_FILE_ID_PREFIX}{export_id}/"


def piece_file_id(export_id: str, hostname: str) -> str:
    """Returns the file ID of the log zip collected from the given host."""
    return f"{export_file_id_prefix(export_id)}piece_{hostname}.zip"


def receipt_file_id(export_id: str, worker_name: str) -> str:
    """Returns the file ID of the given worker's collection receipt."""
    return f"{export_file_id_prefix(export_id)}receipt_{worker_name}.json"


def manifest_file_id(export_id: str) -> str:
    """Returns the file ID of the export's manifest."""
    return f"{export_file_id_prefix(export_id)}{BUNDLE_MANIFEST_FILE_NAME}"


def save_manifest(manifest: LogExportManifest) -> None:
    """Writes the export's manifest to the file store."""
    get_default_file_store().save_file(
        content=BytesIO(manifest.model_dump_json(indent=2).encode("utf-8")),
        display_name=BUNDLE_MANIFEST_FILE_NAME,
        file_origin=FileOrigin.LOG_EXPORT,
        file_type=JSON_FILE_TYPE,
        file_id=manifest_file_id(manifest.export_id),
    )


def read_export_snapshot(export_id: str) -> LogExportSnapshot | None:
    """Reads the manifest, receipts, and piece IDs stored for an export.

    Returns:
        The export's current contents, or None when no manifest exists under its
        prefix (i.e. the export was never started or has been cleaned up).
    """
    file_store = get_default_file_store()
    prefix = export_file_id_prefix(export_id)
    file_ids = {record.file_id for record in file_store.list_files_by_prefix(prefix)}
    if manifest_file_id(export_id) not in file_ids:
        return None
    manifest = LogExportManifest.model_validate_json(
        file_store.read_file(manifest_file_id(export_id)).read()
    )
    receipts = [
        LogExportReceipt.model_validate_json(file_store.read_file(file_id).read())
        for file_id in sorted(file_ids)
        if file_id.removeprefix(prefix).startswith("receipt_")
    ]
    piece_file_ids = sorted(
        file_id
        for file_id in file_ids
        if file_id.removeprefix(prefix).startswith("piece_")
    )
    return LogExportSnapshot(
        manifest=manifest, receipts=receipts, piece_file_ids=piece_file_ids
    )


def derive_export_state(snapshot: LogExportSnapshot, now: datetime) -> LogExportState:
    """Returns ``READY`` once every worker reported or the deadline passed."""
    reported = {receipt.worker_name for receipt in snapshot.receipts}
    if set(snapshot.manifest.worker_names) <= reported:
        return LogExportState.READY
    if now >= snapshot.manifest.deadline:
        return LogExportState.READY
    return LogExportState.COLLECTING


def _build_bundle_readme(snapshot: LogExportSnapshot) -> str:
    """Builds the README.txt content describing the download bundle."""
    manifest = snapshot.manifest
    lines = [
        "Onyx log export bundle",
        "======================",
        "",
        SENSITIVE_DATA_WARNING,
        "",
        f"Export ID: {manifest.export_id}",
        f"Onyx version: {manifest.onyx_version}",
        f"Requested by: {manifest.requester_email}",
        f"Created at (UTC): {manifest.created_at.isoformat()}",
        "",
        "Contents: one piece_<hostname>.zip per host that uploaded logs, plus",
        f"{BUNDLE_MANIFEST_FILE_NAME} with per-worker receipt outcomes.",
        "",
        "Worker outcomes:",
    ]
    reported = {receipt.worker_name for receipt in snapshot.receipts}
    for receipt in snapshot.receipts:
        detail = f" ({receipt.file_count} files, {receipt.size_bytes} bytes)"
        if receipt.status is not LogExportReceiptStatus.UPLOADED:
            detail = f" ({receipt.error})" if receipt.error else ""
        lines.append(f"  {receipt.worker_name}: {receipt.status.value}{detail}")
    lines.extend(
        f"  {worker_name}: no receipt (did not report before the deadline)"
        for worker_name in manifest.worker_names
        if worker_name not in reported
    )
    lines.append("")
    return "\n".join(lines)


def build_export_bundle(snapshot: LogExportSnapshot) -> BuiltLogZip:
    """Assembles the download zip from an export's stored artifacts.

    The bundle contains a ``README.txt``, a ``manifest.json`` enriched with
    receipt outcomes, and every stored ``piece_{hostname}.zip``. Pieces are
    copied in without recompression (they are already DEFLATE zips), streamed in
    chunks so large pieces never fully load into memory.

    Returns:
        The bundle per ``BuiltLogZip``; ``log_file_count`` is the number of
        pieces. The caller owns the buffer and must close it.
    """
    file_store = get_default_file_store()
    bundle_manifest = LogExportBundleManifest(
        **snapshot.manifest.model_dump(), receipts=snapshot.receipts
    )
    zip_buffer: tempfile.SpooledTemporaryFile[bytes] = tempfile.SpooledTemporaryFile(
        max_size=MAX_IN_MEMORY_SIZE
    )
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_STORED) as zip_file:
        zip_file.writestr(BUNDLE_README_FILE_NAME, _build_bundle_readme(snapshot))
        zip_file.writestr(
            BUNDLE_MANIFEST_FILE_NAME, bundle_manifest.model_dump_json(indent=2)
        )
        prefix = export_file_id_prefix(snapshot.manifest.export_id)
        for piece_id in snapshot.piece_file_ids:
            arcname = piece_id.removeprefix(prefix)
            with (
                file_store.read_file(piece_id, use_tempfile=True) as piece_stream,
                zip_file.open(arcname, mode="w") as destination,
            ):
                shutil.copyfileobj(piece_stream, destination, STANDARD_CHUNK_SIZE)

    zip_buffer.seek(0, os.SEEK_END)
    size_bytes = zip_buffer.tell()
    zip_buffer.seek(0)
    return BuiltLogZip(
        zip_buffer=zip_buffer,
        log_file_count=len(snapshot.piece_file_ids),
        size_bytes=size_bytes,
    )


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
            built = build_log_zip(
                log_directories,
                scope_note,
                shallow_log_directories=shallow_log_directories,
            )
            try:
                if built.log_file_count == 0:
                    status = LogExportReceiptStatus.NO_LOGS_FOUND
                else:
                    file_count = built.log_file_count
                    size_bytes = built.size_bytes
                    file_store.save_file(
                        content=built.zip_buffer,
                        display_name=f"piece_{hostname}.zip",
                        file_origin=FileOrigin.LOG_EXPORT,
                        file_type=ZIP_FILE_TYPE,
                        file_id=piece_id,
                    )
                    status = LogExportReceiptStatus.UPLOADED
            finally:
                built.zip_buffer.close()
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
