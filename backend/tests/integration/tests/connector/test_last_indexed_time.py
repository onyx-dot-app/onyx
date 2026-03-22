"""
Integration tests for the "Last Indexed" time displayed on both the
per-connector detail page and the all-connectors listing page.

Expected behavior: "Last Indexed" = time_started of the most recent
successful index attempt for the cc pair, regardless of pagination.

Edge cases:
1. First page of index attempts is entirely errors — last_indexed should
   still reflect the older successful attempt beyond page 1.
2. Credential swap — successful attempts, then failures after a
   "credential change"; last_indexed should reflect the most recent
   successful attempt.
3. Mix of statuses — only the most recent successful attempt matters.
"""

from datetime import datetime
from datetime import timedelta
from datetime import timezone

from onyx.db.models import IndexingStatus
from onyx.server.documents.models import CCPairFullInfo
from onyx.server.documents.models import ConnectorIndexingStatusLite
from tests.integration.common_utils.managers.cc_pair import CCPairManager
from tests.integration.common_utils.managers.index_attempt import IndexAttemptManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.test_models import DATestCCPair
from tests.integration.common_utils.test_models import DATestUser


def _wait_for_real_success(
    cc_pair: DATestCCPair,
    admin: DATestUser,
) -> None:
    """Wait for the initial index attempt to complete successfully."""
    CCPairManager.wait_for_indexing_completion(
        cc_pair,
        after=datetime(2000, 1, 1, tzinfo=timezone.utc),
        user_performing_action=admin,
        timeout=120,
    )


def _get_detail(cc_pair_id: int, admin: DATestUser) -> CCPairFullInfo:
    result = CCPairManager.get_single(cc_pair_id, admin)
    assert result is not None
    return result


def _get_listing(cc_pair_id: int, admin: DATestUser) -> ConnectorIndexingStatusLite:
    result = CCPairManager.get_indexing_status_by_id(cc_pair_id, admin)
    assert result is not None
    return result


def test_last_indexed_first_page_all_errors(reset: None) -> None:  # noqa: ARG001
    """When the first page of index attempts is entirely errors but an
    older successful attempt exists, both the detail page and the listing
    page should still show the time of that successful attempt.

    The detail page UI uses page size 8. We insert 10 failed attempts
    more recent than the initial success to push the success off page 1.
    """
    admin = UserManager.create(name="admin_first_page_errors")
    cc_pair = CCPairManager.create_from_scratch(user_performing_action=admin)
    _wait_for_real_success(cc_pair, admin)

    # Baseline: last_success should be set from the initial successful run
    listing_before = _get_listing(cc_pair.id, admin)
    assert listing_before.last_success is not None

    # 10 recent failures push the success off page 1
    IndexAttemptManager.create_test_index_attempts(
        num_attempts=10,
        cc_pair_id=cc_pair.id,
        status=IndexingStatus.FAILED,
        error_msg="simulated failure",
        base_time=datetime.now(),
    )

    detail = _get_detail(cc_pair.id, admin)
    listing = _get_listing(cc_pair.id, admin)

    assert (
        detail.last_indexed is not None
    ), "Detail page last_indexed is None even though a successful attempt exists"
    assert (
        listing.last_success is not None
    ), "Listing page last_success is None even though a successful attempt exists"

    # Both surfaces must agree
    assert detail.last_indexed == listing.last_success, (
        f"Detail last_indexed={detail.last_indexed} != "
        f"listing last_success={listing.last_success}"
    )


def test_last_indexed_credential_swap_scenario(reset: None) -> None:  # noqa: ARG001
    """Simulate the reported bug: "Last Indexed" shows "1 month ago" when
    the most recent visible attempt is from a week ago.

    After real initial success, insert synthetic success 7 days ago,
    then 10 recent failures. The detail and listing pages must agree.
    """
    admin = UserManager.create(name="admin_cred_swap")
    cc_pair = CCPairManager.create_from_scratch(user_performing_action=admin)
    _wait_for_real_success(cc_pair, admin)

    now = datetime.now()

    # Synthetic success 7 days ago
    IndexAttemptManager.create_test_index_attempts(
        num_attempts=1,
        cc_pair_id=cc_pair.id,
        status=IndexingStatus.SUCCESS,
        base_time=now - timedelta(days=7),
    )

    # 10 recent failures filling page 1
    IndexAttemptManager.create_test_index_attempts(
        num_attempts=10,
        cc_pair_id=cc_pair.id,
        status=IndexingStatus.FAILED,
        error_msg="credential expired",
        base_time=now,
    )

    detail = _get_detail(cc_pair.id, admin)
    listing = _get_listing(cc_pair.id, admin)

    assert detail.last_indexed is not None
    assert listing.last_success is not None

    assert detail.last_indexed == listing.last_success, (
        f"Detail last_indexed={detail.last_indexed} != "
        f"listing last_success={listing.last_success}"
    )


def test_last_indexed_mixed_statuses(reset: None) -> None:  # noqa: ARG001
    """Mix of in_progress, failed, and successful attempts. Only the most
    recent successful attempt's time matters."""
    admin = UserManager.create(name="admin_mixed")
    cc_pair = CCPairManager.create_from_scratch(user_performing_action=admin)
    _wait_for_real_success(cc_pair, admin)

    now = datetime.now()

    # Success 5 hours ago
    IndexAttemptManager.create_test_index_attempts(
        num_attempts=1,
        cc_pair_id=cc_pair.id,
        status=IndexingStatus.SUCCESS,
        base_time=now - timedelta(hours=5),
    )

    # Failures 3 hours ago
    IndexAttemptManager.create_test_index_attempts(
        num_attempts=3,
        cc_pair_id=cc_pair.id,
        status=IndexingStatus.FAILED,
        error_msg="transient failure",
        base_time=now - timedelta(hours=3),
    )

    # In-progress 1 hour ago
    IndexAttemptManager.create_test_index_attempts(
        num_attempts=1,
        cc_pair_id=cc_pair.id,
        status=IndexingStatus.IN_PROGRESS,
        base_time=now - timedelta(hours=1),
    )

    detail = _get_detail(cc_pair.id, admin)
    listing = _get_listing(cc_pair.id, admin)

    assert detail.last_indexed is not None
    assert listing.last_success is not None

    assert detail.last_indexed == listing.last_success, (
        f"Detail last_indexed={detail.last_indexed} != "
        f"listing last_success={listing.last_success}"
    )
