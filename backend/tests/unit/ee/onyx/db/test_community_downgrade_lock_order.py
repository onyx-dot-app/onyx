"""The downgrade takes the group-membership lock before any connector pair row,
the order a connector access edit uses, so the two cannot deadlock."""

from unittest.mock import MagicMock, patch

from ee.onyx.db.community_downgrade import make_all_cc_pairs_public__no_commit


def test_membership_lock_comes_before_the_pair_row_locks() -> None:
    db_session = MagicMock()
    db_session.scalars.return_value = []
    calls = MagicMock()
    calls.attach_mock(db_session.scalars, "lock_pair_rows")

    with patch("ee.onyx.db.community_downgrade.lock_group_membership") as lock:
        calls.attach_mock(lock, "lock_membership")
        make_all_cc_pairs_public__no_commit(db_session)

    assert [call[0] for call in calls.mock_calls][:2] == [
        "lock_membership",
        "lock_pair_rows",
    ]
