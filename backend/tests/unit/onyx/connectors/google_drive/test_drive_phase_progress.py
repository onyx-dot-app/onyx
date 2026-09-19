"""Phase and partition cursor semantics for the redesigned Drive retrieval.

Resuming has to land on the partition that was in flight, and must never
re-list a partition that already finished. This is the state that replaces the
per-document seen-set, so it also has to stay proportional to drives and users.
"""

from onyx.connectors.google_drive.models import (
    DriveRetrievalPhase,
    DriveRetrievalStage,
    GoogleDriveCheckpoint,
    PhaseProgress,
    next_phase,
)
from onyx.utils.threadpool_concurrency import ThreadSafeDict


def _progress(keys: list[str], index: int = 0) -> PhaseProgress:
    return PhaseProgress(
        phase=DriveRetrievalPhase.SHARED_DRIVES,
        partition_keys=keys,
        partition_index=index,
    )


def test_shared_drives_run_before_my_drives() -> None:
    """Ordering is load-bearing: it lets later phases drop files from drives
    already covered, instead of tracking every file id."""
    phase = DriveRetrievalPhase.INVENTORY
    seen = [phase]
    while phase is not DriveRetrievalPhase.DONE:
        phase = next_phase(phase)
        seen.append(phase)

    assert seen.index(DriveRetrievalPhase.SHARED_DRIVES) < seen.index(
        DriveRetrievalPhase.MY_DRIVES
    )
    assert seen[-1] is DriveRetrievalPhase.DONE


def test_done_is_a_fixed_point() -> None:
    assert next_phase(DriveRetrievalPhase.DONE) is DriveRetrievalPhase.DONE


def test_advancing_clears_the_within_partition_cursor() -> None:
    progress = _progress(["drive_a", "drive_b"])
    progress.next_page_token = "token"
    progress.completed_until = 1234.0

    progress.advance_partition()

    assert progress.current_partition == "drive_b"
    # A page token from the previous drive would be rejected by the new listing.
    assert progress.next_page_token is None
    assert progress.completed_until == 0


def test_phase_completes_after_the_last_partition() -> None:
    progress = _progress(["drive_a"])
    assert progress.is_complete is False

    progress.advance_partition()

    assert progress.is_complete is True
    assert progress.current_partition is None
    assert progress.remaining_partitions == []


def test_finished_partitions_are_not_revisited() -> None:
    progress = _progress(["a", "b", "c"], index=2)

    assert progress.remaining_partitions == ["c"]


def test_resume_keeps_partition_and_page_token() -> None:
    checkpoint = GoogleDriveCheckpoint(
        has_more=True,
        retrieved_folder_and_drive_ids=set(),
        completion_stage=DriveRetrievalStage.START,
        completion_map=ThreadSafeDict(),
        phase_progress=PhaseProgress(
            phase=DriveRetrievalPhase.SHARED_DRIVES,
            partition_keys=["drive_a", "drive_b"],
            partition_index=1,
            next_page_token="page_2",
            completed_until=99.0,
        ),
    )

    restored = GoogleDriveCheckpoint.model_validate_json(checkpoint.model_dump_json())

    assert restored.phase_progress is not None
    assert restored.phase_progress.current_partition == "drive_b"
    assert restored.phase_progress.next_page_token == "page_2"
    assert restored.phase_progress.completed_until == 99.0


def test_organizer_map_and_incomplete_drives_round_trip() -> None:
    checkpoint = GoogleDriveCheckpoint(
        has_more=True,
        retrieved_folder_and_drive_ids=set(),
        completion_stage=DriveRetrievalStage.START,
        completion_map=ThreadSafeDict(),
        organizer_email_by_drive_id={"drive_a": "boss@example.com"},
        incomplete_drive_ids={"drive_b"},
    )

    restored = GoogleDriveCheckpoint.model_validate_json(checkpoint.model_dump_json())

    assert restored.organizer_email_by_drive_id == {"drive_a": "boss@example.com"}
    # Absence from a drive listed without an organizer must not drive a prune.
    assert restored.incomplete_drive_ids == {"drive_b"}
