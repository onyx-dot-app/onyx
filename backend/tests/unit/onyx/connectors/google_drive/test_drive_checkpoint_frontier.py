"""Checkpoint frontier (completed_until) semantics for Google Drive retrieval.

The retrieval listing is ordered by modifiedTime and resumes from
completed_until, so the frontier must never move backward within a stage +
drive/folder. A regression changes the listing query, invalidates the saved
page token, and restarts retrieval from the regressed timestamp — looping
forever if the same file causes the same regression on every pass (as happened
when shortcut resolution replaced a file's modifiedTime with its target's).
"""

from collections.abc import Iterator
from datetime import datetime
from typing import Any

from onyx.connectors.google_drive.connector import (
    GoogleDriveConnector,
    _resume_start,
)
from onyx.connectors.google_drive.file_retrieval import DriveFileFieldType
from onyx.connectors.google_drive.models import (
    DriveRetrievalStage,
    GoogleDriveCheckpoint,
    RetrievedDriveFile,
    StageCompletion,
)
from onyx.utils.threadpool_concurrency import ThreadSafeDict

_USER = "user@example.com"


def _ts(iso: str) -> float:
    return datetime.fromisoformat(iso).timestamp()


def _file(
    file_id: str,
    modified_time: str,
    parent_id: str | None = None,
    stage: DriveRetrievalStage = DriveRetrievalStage.MY_DRIVE_FILES,
) -> RetrievedDriveFile:
    drive_file: dict[str, Any] = {
        "id": file_id,
        "name": file_id,
        "modifiedTime": modified_time,
        "webViewLink": f"https://drive.google.com/file/d/{file_id}",
    }
    return RetrievedDriveFile(
        completion_stage=stage,
        drive_file=drive_file,
        user_email=_USER,
        parent_id=parent_id,
    )


def _checkpoint(
    stage: DriveRetrievalStage = DriveRetrievalStage.MY_DRIVE_FILES,
    current_folder_or_drive_id: str | None = None,
) -> GoogleDriveCheckpoint:
    return GoogleDriveCheckpoint(
        has_more=True,
        retrieved_folder_and_drive_ids=set(),
        completion_stage=stage,
        completion_map=ThreadSafeDict(
            {
                _USER: StageCompletion(
                    stage=stage,
                    completed_until=0,
                    current_folder_or_drive_id=current_folder_or_drive_id,
                )
            }
        ),
    )


def _funnel(
    checkpoint: GoogleDriveCheckpoint, files: list[RetrievedDriveFile]
) -> Iterator[RetrievedDriveFile]:
    connector = GoogleDriveConnector(include_my_drives=True)

    def retrieval_method(
        field_type: DriveFileFieldType,  # noqa: ARG001
        checkpoint: GoogleDriveCheckpoint,  # noqa: ARG001
        start: float | None = None,  # noqa: ARG001
        end: float | None = None,  # noqa: ARG001
    ) -> Iterator[RetrievedDriveFile]:
        yield from files

    return connector._checkpointed_retrieval(
        retrieval_method=retrieval_method,
        field_type=DriveFileFieldType.STANDARD,
        checkpoint=checkpoint,
        start=None,
        end=None,
    )


def test_out_of_order_mtime_never_regresses_frontier() -> None:
    checkpoint = _checkpoint()
    completion = checkpoint.completion_map[_USER]
    gen = _funnel(
        checkpoint,
        [
            _file("f1", "2024-06-01T00:00:00Z"),
            _file("f2", "2024-01-15T00:00:00Z"),  # unexpected out-of-order timestamp
            _file("f3", "2024-06-03T00:00:00Z"),
        ],
    )

    next(gen)
    assert completion.completed_until == _ts("2024-06-01T00:00:00Z")
    next(gen)
    assert completion.completed_until == _ts("2024-06-01T00:00:00Z")
    next(gen)
    assert completion.completed_until == _ts("2024-06-03T00:00:00Z")


def test_frontier_resets_when_drive_changes() -> None:
    checkpoint = _checkpoint(
        stage=DriveRetrievalStage.SHARED_DRIVE_FILES,
        current_folder_or_drive_id="drive_1",
    )
    completion = checkpoint.completion_map[_USER]
    gen = _funnel(
        checkpoint,
        [
            _file(
                "f1",
                "2024-06-01T00:00:00Z",
                parent_id="drive_1",
                stage=DriveRetrievalStage.SHARED_DRIVE_FILES,
            ),
            # next drive starts over at an earlier timestamp; this is a
            # legitimate reset, not a regression
            _file(
                "f2",
                "2024-02-01T00:00:00Z",
                parent_id="drive_2",
                stage=DriveRetrievalStage.SHARED_DRIVE_FILES,
            ),
        ],
    )

    next(gen)
    assert completion.completed_until == _ts("2024-06-01T00:00:00Z")
    next(gen)
    assert completion.completed_until == _ts("2024-02-01T00:00:00Z")
    assert completion.current_folder_or_drive_id == "drive_2"


def test_resume_start_clamps_to_range_start() -> None:
    assert _resume_start(100.0, 200.0) == 200.0
    assert _resume_start(300.0, 200.0) == 300.0
    assert _resume_start(300.0, None) == 300.0
