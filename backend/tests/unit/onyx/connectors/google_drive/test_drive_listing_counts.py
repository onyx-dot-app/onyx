"""The corpus count of a Drive listing is partial when the listing missed
files: a shared drive listed only in part, or a requested target that no user
could reach."""

import pytest

from onyx.connectors.google_drive.connector import GoogleDriveConnector
from onyx.connectors.google_drive.models import DriveListingState


@pytest.mark.parametrize(
    "incomplete_drive_ids, unreachable_target_ids, partial",
    [
        (set(), set(), False),
        ({"drive-1"}, set(), True),
        (set(), {"folder-1"}, True),
    ],
)
def test_a_count_with_missed_files_is_partial(
    incomplete_drive_ids: set[str], unreachable_target_ids: set[str], partial: bool
) -> None:
    connector = GoogleDriveConnector(include_shared_drives=True)
    checkpoint = connector.build_dummy_checkpoint()
    checkpoint.listing = DriveListingState(window_t0=0, window_t1=1)
    checkpoint.incomplete_drive_ids = incomplete_drive_ids
    checkpoint.unreachable_target_ids = unreachable_target_ids

    counts = connector.listing_counts(checkpoint)

    assert counts is not None
    assert counts.partial is partial
