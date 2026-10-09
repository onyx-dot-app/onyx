"""External dependency unit tests for log-export file-store storage.

Runs against the real (Postgres/MinIO-backed) file store; log files come from
tmp directories.
"""

from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4
from zipfile import ZipFile

import pytest
from sqlalchemy.orm import Session

from ee.onyx.server.log_export.models import LogExportReceipt, LogExportReceiptStatus
from ee.onyx.server.log_export.storage import (
    LOG_EXPORT_RETENTION,
    collect_logs_into_file_store,
    delete_expired_log_exports,
    export_file_id_prefix,
    piece_file_id,
    receipt_file_id,
)
from onyx.db.models import FileRecord
from onyx.file_store.file_store import get_default_file_store

pytestmark = pytest.mark.usefixtures(
    "db_session", "tenant_context", "initialize_file_store"
)


def test_collect_uploads_piece_and_receipt(tmp_path: Path) -> None:
    # Precondition.
    (tmp_path / "onyx_debug.log").write_text("debug line\n")
    export_id = uuid4().hex

    # Under test.
    receipt = collect_logs_into_file_store(
        export_id=export_id,
        worker_name="primary",
        log_directories=[tmp_path],
    )

    # Postcondition.
    assert receipt.status is LogExportReceiptStatus.UPLOADED
    assert receipt.file_count == 1
    file_store = get_default_file_store()
    piece_bytes = file_store.read_file(
        piece_file_id(export_id, receipt.hostname)
    ).read()
    assert receipt.size_bytes == len(piece_bytes)
    with ZipFile(BytesIO(piece_bytes)) as zip_file:
        log_entries = [
            name for name in zip_file.namelist() if name.endswith("onyx_debug.log")
        ]
        assert len(log_entries) == 1, "The piece zip must contain the planted log file."
        assert zip_file.read(log_entries[0]) == b"debug line\n"
    receipt_bytes = file_store.read_file(receipt_file_id(export_id, "primary")).read()
    assert LogExportReceipt.model_validate_json(receipt_bytes) == receipt


def test_second_worker_on_same_host_dedupes(tmp_path: Path) -> None:
    # Precondition.
    (tmp_path / "onyx_debug.log").write_text("debug line\n")
    export_id = uuid4().hex
    collect_logs_into_file_store(
        export_id=export_id,
        worker_name="primary",
        log_directories=[tmp_path],
    )

    # Under test.
    receipt = collect_logs_into_file_store(
        export_id=export_id,
        worker_name="light",
        log_directories=[tmp_path],
    )

    # Postcondition.
    assert receipt.status is LogExportReceiptStatus.DUPLICATE_HOST
    assert receipt.file_count == 0
    assert receipt.size_bytes == 0
    file_store = get_default_file_store()
    file_ids = [
        record.file_id
        for record in file_store.list_files_by_prefix(export_file_id_prefix(export_id))
    ]
    assert len([f for f in file_ids if "/piece_" in f]) == 1
    assert len([f for f in file_ids if "/receipt_" in f]) == 2


def test_empty_directory_reports_no_logs_found(tmp_path: Path) -> None:
    # Precondition.
    export_id = uuid4().hex

    # Under test.
    receipt = collect_logs_into_file_store(
        export_id=export_id,
        worker_name="monitoring",
        log_directories=[tmp_path],
    )

    # Postcondition: a receipt but no piece.
    assert receipt.status is LogExportReceiptStatus.NO_LOGS_FOUND
    file_store = get_default_file_store()
    file_ids = [
        record.file_id
        for record in file_store.list_files_by_prefix(export_file_id_prefix(export_id))
    ]
    assert file_ids == [receipt_file_id(export_id, "monitoring")]


def test_collection_failure_writes_failed_receipt(tmp_path: Path) -> None:
    # Precondition.
    export_id = uuid4().hex

    # Under test.
    with patch(
        "ee.onyx.server.log_export.storage.build_log_zip",
        side_effect=OSError("disk exploded"),
    ):
        receipt = collect_logs_into_file_store(
            export_id=export_id,
            worker_name="primary",
            log_directories=[tmp_path],
        )

    # Postcondition: the failure is recorded in a persisted receipt.
    assert receipt.status is LogExportReceiptStatus.FAILED
    assert receipt.error is not None
    assert "disk exploded" in receipt.error
    file_store = get_default_file_store()
    receipt_bytes = file_store.read_file(receipt_file_id(export_id, "primary")).read()
    assert LogExportReceipt.model_validate_json(receipt_bytes) == receipt


def test_cleanup_deletes_only_expired_exports(
    tmp_path: Path, db_session: Session
) -> None:
    # Precondition: two exports, one aged past retention.
    (tmp_path / "onyx_debug.log").write_text("debug line\n")
    old_export_id = uuid4().hex
    fresh_export_id = uuid4().hex
    for export_id in (old_export_id, fresh_export_id):
        collect_logs_into_file_store(
            export_id=export_id,
            worker_name="primary",
            log_directories=[tmp_path],
        )
    expired_at = (
        datetime.now(tz=timezone.utc) - LOG_EXPORT_RETENTION - timedelta(minutes=1)
    )
    db_session.query(FileRecord).filter(
        FileRecord.file_id.startswith(export_file_id_prefix(old_export_id))
    ).update({"created_at": expired_at}, synchronize_session=False)
    db_session.commit()

    # Under test.
    deleted_count = delete_expired_log_exports()

    # Postcondition: the aged export is gone, the fresh one is intact. Leftovers
    # from earlier test runs may also be deleted, hence ``>=``.
    assert deleted_count >= 2
    file_store = get_default_file_store()
    assert file_store.list_files_by_prefix(export_file_id_prefix(old_export_id)) == []
    remaining = file_store.list_files_by_prefix(export_file_id_prefix(fresh_export_id))
    assert len(remaining) == 2, "The fresh piece and receipt must survive cleanup."
