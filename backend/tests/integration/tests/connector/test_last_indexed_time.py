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
4. COMPLETED_WITH_ERRORS counts as a success for last_indexed purposes.
"""

from datetime import datetime
from datetime import timedelta
from datetime import timezone

from onyx.db.models import IndexingStatus
from onyx.server.documents.models import CCPairFullInfo
from onyx.server.documents.models import ConnectorIndexingStatusLite
from tests.integration.common_utils.managers.cc_pair import CCPairManager
from tests.integration.common_utils.managers.connector import ConnectorManager
from tests.integration.common_utils.managers.credential import CredentialManager
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
        base_time=datetime.now(tz=timezone.utc),
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
    """Perform an actual credential swap: create connector + cred1 (cc_pair_1),
    wait for success, then associate a new cred2 with the same connector
    (cc_pair_2), wait for that to succeed, and inject failures on cc_pair_2.

    cc_pair_2's last_indexed must reflect cc_pair_2's own success, not
    cc_pair_1's older one. Both the detail page and listing page must agree.
    """
    admin = UserManager.create(name="admin_cred_swap")

    connector = ConnectorManager.create(user_performing_action=admin)
    cred1 = CredentialManager.create(user_performing_action=admin)
    cc_pair_1 = CCPairManager.create(
        connector_id=connector.id,
        credential_id=cred1.id,
        user_performing_action=admin,
    )
    _wait_for_real_success(cc_pair_1, admin)

    cred2 = CredentialManager.create(user_performing_action=admin, name="swapped-cred")
    cc_pair_2 = CCPairManager.create(
        connector_id=connector.id,
        credential_id=cred2.id,
        user_performing_action=admin,
    )
    _wait_for_real_success(cc_pair_2, admin)

    listing_after_swap = _get_listing(cc_pair_2.id, admin)
    assert listing_after_swap.last_success is not None

    IndexAttemptManager.create_test_index_attempts(
        num_attempts=10,
        cc_pair_id=cc_pair_2.id,
        status=IndexingStatus.FAILED,
        error_msg="credential expired",
        base_time=datetime.now(tz=timezone.utc),
    )

    detail = _get_detail(cc_pair_2.id, admin)
    listing = _get_listing(cc_pair_2.id, admin)

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

    now = datetime.now(tz=timezone.utc)

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


def test_last_indexed_completed_with_errors(reset: None) -> None:  # noqa: ARG001
    """COMPLETED_WITH_ERRORS is treated as a successful attempt (matching
    IndexingStatus.is_successful()). When it is the most recent "success"
    and later attempts all failed, both surfaces should reflect its time."""
    admin = UserManager.create(name="admin_completed_errors")
    cc_pair = CCPairManager.create_from_scratch(user_performing_action=admin)
    _wait_for_real_success(cc_pair, admin)

    now = datetime.now(tz=timezone.utc)

    # COMPLETED_WITH_ERRORS 2 hours ago
    IndexAttemptManager.create_test_index_attempts(
        num_attempts=1,
        cc_pair_id=cc_pair.id,
        status=IndexingStatus.COMPLETED_WITH_ERRORS,
        base_time=now - timedelta(hours=2),
    )

    # 10 failures after — push everything else off page 1
    IndexAttemptManager.create_test_index_attempts(
        num_attempts=10,
        cc_pair_id=cc_pair.id,
        status=IndexingStatus.FAILED,
        error_msg="post-partial failure",
        base_time=now,
    )

    detail = _get_detail(cc_pair.id, admin)
    listing = _get_listing(cc_pair.id, admin)

    assert (
        detail.last_indexed is not None
    ), "COMPLETED_WITH_ERRORS should count as a success for last_indexed"
    assert (
        listing.last_success is not None
    ), "COMPLETED_WITH_ERRORS should count as a success for last_success"

    assert detail.last_indexed == listing.last_success, (
        f"Detail last_indexed={detail.last_indexed} != "
        f"listing last_success={listing.last_success}"
    )
