from datetime import datetime
from enum import Enum

from pydantic import BaseModel


class LogExportReceiptStatus(str, Enum):
    UPLOADED = "uploaded"
    # A piece for this host already existed, so only a receipt was written.
    # Best-effort: collectors running simultaneously on one host may each report
    # ``UPLOADED`` instead.
    DUPLICATE_HOST = "duplicate_host"
    NO_LOGS_FOUND = "no_logs_found"
    FAILED = "failed"


class LogExportReceipt(BaseModel):
    """Outcome report written by each collector, one per fanned-out worker.

    Receipts mean "this worker reported"; pieces must be discovered by listing
    the export's file-ID prefix, never derived from receipt statuses.
    """

    export_id: str
    worker_name: str
    hostname: str
    status: LogExportReceiptStatus
    # Number of log files in the uploaded piece; 0 unless ``status`` is
    # ``UPLOADED``.
    file_count: int
    # Size of the uploaded piece zip in bytes; 0 unless ``status`` is
    # ``UPLOADED``.
    size_bytes: int
    collected_at: datetime
    # Why collection failed; only set when ``status`` is ``FAILED``.
    error: str | None = None


class LogExportManifest(BaseModel):
    """Export metadata written at fan-out time, before any receipt exists."""

    export_id: str
    created_at: datetime
    # Receipts are awaited until this instant; afterwards the export is
    # ``READY`` regardless of who reported.
    deadline: datetime
    requester_email: str
    onyx_version: str
    # Every worker expected to write a receipt, including the api_server's
    # inline collection.
    worker_names: list[str]


class LogExportSnapshot(BaseModel):
    """
    Everything stored under one export's file store prefix at a point in time.
    """

    manifest: LogExportManifest
    receipts: list[LogExportReceipt]
    piece_file_ids: list[str]


class LogExportBundleManifest(LogExportManifest):
    """Manifest enriched with receipt outcomes, embedded in the download."""

    receipts: list[LogExportReceipt]


class LogExportState(str, Enum):
    COLLECTING = "collecting"
    READY = "ready"


class LogExportStartResponse(BaseModel):
    export_id: str


class LogExportStatusResponse(BaseModel):
    export_id: str
    state: LogExportState
    created_at: datetime
    deadline: datetime
    receipts: list[LogExportReceipt]
    # Manifest workers that have not written a receipt yet.
    pending_worker_names: list[str]
