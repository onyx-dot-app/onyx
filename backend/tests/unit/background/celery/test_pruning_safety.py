"""_prune_safety_violation: the guard that aborts a prune on an untrustworthy diff."""

from onyx.background.celery.tasks.pruning import tasks as pruning_tasks


def test_no_indexed_documents_never_aborts() -> None:
    assert (
        pruning_tasks._prune_safety_violation(
            indexed_count=0, listing_count=0, removal_count=0
        )
        is None
    )


def test_empty_listing_aborts_even_for_a_small_index() -> None:
    violation = pruning_tasks._prune_safety_violation(
        indexed_count=1, listing_count=0, removal_count=1
    )

    assert violation is not None
    assert "0 documents" in violation


def test_empty_listing_aborts_for_the_incident_shape() -> None:
    # The shape of the reported incident: one hierarchy node and no documents
    # came back from the listing while the index held the full connector set.
    violation = pruning_tasks._prune_safety_violation(
        indexed_count=189833, listing_count=0, removal_count=189833
    )

    assert violation is not None
    assert "189833" in violation


def test_small_diff_is_allowed() -> None:
    assert (
        pruning_tasks._prune_safety_violation(
            indexed_count=100, listing_count=90, removal_count=10
        )
        is None
    )


def test_diff_at_the_threshold_is_allowed() -> None:
    assert (
        pruning_tasks._prune_safety_violation(
            indexed_count=100,
            listing_count=50,
            removal_count=50,
        )
        is None
    )


def test_diff_above_the_threshold_aborts() -> None:
    violation = pruning_tasks._prune_safety_violation(
        indexed_count=100, listing_count=40, removal_count=60
    )

    assert violation is not None
    assert "60 of 100" in violation


def test_threshold_is_a_share_between_zero_and_one() -> None:
    assert 0 < pruning_tasks.MAX_PRUNE_REMOVAL_RATIO < 1
