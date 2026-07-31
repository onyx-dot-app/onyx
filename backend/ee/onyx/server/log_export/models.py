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
