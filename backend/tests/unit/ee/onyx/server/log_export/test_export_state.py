from datetime import datetime, timedelta, timezone

from ee.onyx.server.log_export.models import (
    LogExportManifest,
    LogExportReceipt,
    LogExportReceiptStatus,
    LogExportSnapshot,
    LogExportState,
)
from ee.onyx.server.log_export.storage import derive_export_state

_NOW = datetime(2026, 7, 31, 12, 0, 0, tzinfo=timezone.utc)


def _snapshot(
    worker_names: list[str],
    reported_worker_names: list[str],
    deadline: datetime,
) -> LogExportSnapshot:
    manifest = LogExportManifest(
        export_id="abc",
        created_at=_NOW - timedelta(seconds=30),
        deadline=deadline,
        requester_email="admin@example.com",
        onyx_version="1.0.0",
        worker_names=worker_names,
    )
    receipts = [
        LogExportReceipt(
            export_id="abc",
            worker_name=worker_name,
            hostname="host",
            status=LogExportReceiptStatus.UPLOADED,
            file_count=1,
            size_bytes=10,
            collected_at=_NOW,
        )
        for worker_name in reported_worker_names
    ]
    return LogExportSnapshot(manifest=manifest, receipts=receipts, piece_file_ids=[])


def test_collecting_while_receipts_missing_before_deadline() -> None:
    # Precondition.
    snapshot = _snapshot(
        ["api_server", "primary"], ["api_server"], _NOW + timedelta(seconds=60)
    )

    # Under test and postcondition.
    assert derive_export_state(snapshot, now=_NOW) is LogExportState.COLLECTING


def test_ready_when_all_receipts_present() -> None:
    # Precondition.
    snapshot = _snapshot(
        ["api_server", "primary"],
        ["api_server", "primary"],
        _NOW + timedelta(seconds=60),
    )

    # Under test and postcondition.
    assert derive_export_state(snapshot, now=_NOW) is LogExportState.READY


def test_ready_when_deadline_passed_despite_missing_receipts() -> None:
    # Precondition.
    snapshot = _snapshot(
        ["api_server", "primary"], ["api_server"], _NOW - timedelta(seconds=1)
    )

    # Under test and postcondition.
    assert derive_export_state(snapshot, now=_NOW) is LogExportState.READY
