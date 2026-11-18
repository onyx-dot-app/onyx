"""The corpus count of a Drive listing is partial when the listing missed
files: a shared drive listed only in part, a requested target that no user
could reach, or a user listing that Drive denied."""

from collections.abc import Iterator
from typing import Any, cast
from unittest.mock import MagicMock

import pytest

from onyx.connectors.google_drive.connector import GoogleDriveConnector
from onyx.connectors.google_drive.models import DriveListingState
from onyx.connectors.google_drive.source_operations import GoogleDriveHttpError
from tests.unit.onyx.connectors.google_drive.fake_drive import (
    DOMAIN,
    FakeTenant,
    drive_file,
    make_service_account_connector,
    run_to_completion,
)


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


def test_a_denied_my_drive_listing_makes_the_count_partial() -> None:
    """Drive denies the listing of one user's My Drive. The run goes on, and
    the corpus count must say that it missed that user's files."""
    admin, alice = f"admin@{DOMAIN}", f"alice@{DOMAIN}"
    tenant = FakeTenant(
        users=[admin, alice],
        my_drive={
            admin: [drive_file("admin-file", owner=admin)],
            alice: [drive_file("alice-file", owner=alice)],
        },
    )
    list_files = tenant.list_files

    def deny_alice(**kwargs: Any) -> Iterator[dict[str, Any] | str]:
        if kwargs.get("user_email") == alice:
            raise GoogleDriveHttpError(
                status_code=403,
                reasons=("insufficientFilePermissions",),
                access_denied=True,
                message="denied",
            )
        return list_files(**kwargs)

    connector = make_service_account_connector(include_my_drives=True)
    with tenant.patch(connector):
        cast(MagicMock, connector._ops).list_files.side_effect = deny_alice
        result = run_to_completion(connector)

    assert result.errors
    counts = connector.listing_counts(result.checkpoints[-1])
    assert counts is not None
    assert counts.partial is True
