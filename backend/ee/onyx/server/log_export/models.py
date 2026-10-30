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
    # Why collection failed (``FAILED``), or what an ``UPLOADED`` piece is
    # missing because access was denied.
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


class KubernetesLogStream(BaseModel):
    """One container log the Kubernetes collection reads."""

    pod_name: str
    container_name: str
    # Reads the container instance that ran before the last restart.
    previous: bool

    @property
    def arcname(self) -> str:
        suffix = ".previous.log" if self.previous else ".log"
        return f"logs/{self.pod_name}/{self.container_name}{suffix}"


class TerminationSummary(BaseModel):
    reason: str | None
    exit_code: int | None
    started_at: datetime | None
    finished_at: datetime | None


class ContainerSummary(BaseModel):
    name: str
    # Init containers run before the main ones, e.g. the object-store wait.
    init: bool
    ready: bool
    restart_count: int
    # ``running``, ``waiting: <reason>``, or ``terminated: <reason>``.
    state: str
    # How the previous instance ended, e.g. ``OOMKilled`` with exit code 137.
    last_terminated: TerminationSummary | None


class PodSummary(BaseModel):
    """One entry of ``pods.json`` in the Kubernetes piece."""

    name: str
    component: str | None
    node: str | None
    phase: str | None
    # Pod-level reason and message, e.g. ``Evicted`` with the resource pressure.
    reason: str | None
    message: str | None
    containers: list[ContainerSummary]
