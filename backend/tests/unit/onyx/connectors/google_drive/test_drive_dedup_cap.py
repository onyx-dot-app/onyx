"""Dedup-set behavior for Google Drive retrieval.

The set exists only to avoid re-downloading a file within one run, so it is
bounded: past the cap the connector re-yields and lets the indexing pipeline
drop the duplicate. It must never grow without limit, because the checkpoint is
re-serialized on every connector yield.
"""

from collections.abc import Iterator
from typing import Any
from unittest.mock import patch

from onyx.connectors.google_drive import connector as connector_mod
from onyx.connectors.google_drive.connector import GoogleDriveConnector
from onyx.connectors.google_drive.file_retrieval import DriveFileFieldType
from onyx.connectors.google_drive.models import (
    DriveRetrievalStage,
    GoogleDriveCheckpoint,
    RetrievedDriveFile,
    StageCompletion,
)
from onyx.utils.threadpool_concurrency import ThreadSafeDict

_USER = "user@example.com"
_MOD = "onyx.connectors.google_drive.connector"


def _file(file_id: str) -> RetrievedDriveFile:
    drive_file: dict[str, Any] = {
        "id": file_id,
        "name": file_id,
        "modifiedTime": "2024-06-01T00:00:00Z",
        "webViewLink": f"https://docs.google.com/document/d/{file_id}/edit",
    }
    return RetrievedDriveFile(
        completion_stage=DriveRetrievalStage.MY_DRIVE_FILES,
        drive_file=drive_file,
        user_email=_USER,
    )


def _checkpoint() -> GoogleDriveCheckpoint:
    return GoogleDriveCheckpoint(
        has_more=True,
        retrieved_folder_and_drive_ids=set(),
        completion_stage=DriveRetrievalStage.MY_DRIVE_FILES,
        completion_map=ThreadSafeDict(
            {
                _USER: StageCompletion(
                    stage=DriveRetrievalStage.MY_DRIVE_FILES,
                    completed_until=0,
                )
            }
        ),
    )


def _drain(
    checkpoint: GoogleDriveCheckpoint, files: list[RetrievedDriveFile]
) -> list[RetrievedDriveFile]:
    connector = GoogleDriveConnector(include_my_drives=True)

    def retrieval_method(
        field_type: DriveFileFieldType,  # noqa: ARG001
        checkpoint: GoogleDriveCheckpoint,  # noqa: ARG001
        start: float | None = None,  # noqa: ARG001
        end: float | None = None,  # noqa: ARG001
    ) -> Iterator[RetrievedDriveFile]:
        yield from files

    return list(
        connector._checkpointed_retrieval(
            retrieval_method=retrieval_method,
            field_type=DriveFileFieldType.STANDARD,
            checkpoint=checkpoint,
            start=None,
            end=None,
        )
    )


def test_dedup_key_is_the_drive_file_id() -> None:
    checkpoint = _checkpoint()
    _drain(checkpoint, [_file("abc123")])

    # The document URL is ~159 bytes per entry under deep_getsizeof against ~119
    # for the id, and the id is the natural key.
    assert checkpoint.retrieved_drive_file_ids == {"abc123"}


def test_repeated_file_is_yielded_once() -> None:
    checkpoint = _checkpoint()
    yielded = _drain(checkpoint, [_file("abc123"), _file("abc123"), _file("def456")])

    assert [f.drive_file["id"] for f in yielded] == ["abc123", "def456"]


def test_files_past_the_cap_are_still_yielded() -> None:
    checkpoint = _checkpoint()
    with patch.object(connector_mod, "MAX_DEDUP_DRIVE_FILE_IDS", 2):
        yielded = _drain(checkpoint, [_file(f"f{i}") for i in range(5)])

    # Every file reaches the caller; only the tracking stops.
    assert [f.drive_file["id"] for f in yielded] == ["f0", "f1", "f2", "f3", "f4"]
    assert checkpoint.retrieved_drive_file_ids == {"f0", "f1"}


def test_uncapped_duplicate_passes_through_after_cap() -> None:
    checkpoint = _checkpoint()
    with patch.object(connector_mod, "MAX_DEDUP_DRIVE_FILE_IDS", 1):
        yielded = _drain(checkpoint, [_file("f0"), _file("f1"), _file("f1")])

    # f1 was never recorded, so its duplicate is re-yielded rather than dropped.
    assert [f.drive_file["id"] for f in yielded] == ["f0", "f1", "f1"]


def test_old_checkpoint_field_name_is_not_reused() -> None:
    """A checkpoint written before the rename held document URLs, not file ids.

    Pydantic ignores the unknown field, so the run restarts dedup from empty
    instead of comparing ids against URLs and re-yielding everything.
    """
    old = GoogleDriveCheckpoint(
        has_more=True,
        retrieved_folder_and_drive_ids=set(),
        completion_stage=DriveRetrievalStage.MY_DRIVE_FILES,
        completion_map=ThreadSafeDict(),
    ).model_dump()
    old["all_retrieved_file_ids"] = {"https://docs.google.com/document/d/abc123/edit"}

    restored = GoogleDriveCheckpoint.model_validate(old)

    assert restored.retrieved_drive_file_ids == set()
