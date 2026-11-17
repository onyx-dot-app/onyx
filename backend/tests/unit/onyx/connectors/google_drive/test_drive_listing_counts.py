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


@pytest.mark.parametrize(
    "include_my_drives, partial",
    # Without My Drives, the failed user only lists shared drives, which
    # other users list.
    [(True, True), (False, False)],
)
def test_a_user_whose_my_drive_was_not_listed_makes_the_count_partial(
    include_my_drives: bool, partial: bool
) -> None:
    connector = GoogleDriveConnector(
        include_shared_drives=True, include_my_drives=include_my_drives
    )
    checkpoint = connector.build_dummy_checkpoint()
    checkpoint.listing = DriveListingState(window_t0=0, window_t1=1)
    checkpoint.user_emails = ["a@co.com", "B@co.com"]
    checkpoint.failed_impersonation_emails = {"b@co.com"}

    counts = connector.listing_counts(checkpoint)

    assert counts is not None
    assert counts.partial is partial
