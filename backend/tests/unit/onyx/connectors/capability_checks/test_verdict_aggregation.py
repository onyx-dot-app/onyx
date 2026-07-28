from onyx.connectors.capability_checks.models import (
    CapabilityCheckResult,
    CapabilityCheckStatus,
    CapabilityVerdict,
    CredentialCapability,
    aggregate_capability_verdict,
    compute_capability_verdicts,
)


def _result(
    status: CapabilityCheckStatus,
    required: bool = True,
    capability: CredentialCapability = CredentialCapability.INDEXING,
) -> CapabilityCheckResult:
    return CapabilityCheckResult(
        capability=capability,
        check_id="check",
        display_name="Check",
        required=required,
        status=status,
    )


def test_not_applicable_wins_over_all_results() -> None:
    """
    Verifies that an inapplicable capability is NOT_APPLICABLE regardless of
    results.
    """
    # Precondition.
    results = [_result(CapabilityCheckStatus.FAILED)]

    # Under test and postcondition.
    assert (
        aggregate_capability_verdict(False, results) == CapabilityVerdict.NOT_APPLICABLE
    ), "Inapplicable capabilities must ignore check results."


def test_required_failure_fails_the_capability() -> None:
    """Verifies that any required failure yields FAILED even among passes."""
    # Precondition.
    results = [
        _result(CapabilityCheckStatus.PASSED),
        _result(CapabilityCheckStatus.FAILED, required=True),
        _result(CapabilityCheckStatus.FAILED, required=False),
        _result(CapabilityCheckStatus.INDETERMINATE),
    ]

    # Under test and postcondition.
    assert aggregate_capability_verdict(True, results) == CapabilityVerdict.FAILED


def test_only_optional_failures_pass_with_warnings() -> None:
    """Verifies that non-required failures downgrade to PASSED_WITH_WARNINGS."""
    # Precondition.
    results = [
        _result(CapabilityCheckStatus.PASSED),
        _result(CapabilityCheckStatus.FAILED, required=False),
    ]

    # Under test and postcondition.
    assert (
        aggregate_capability_verdict(True, results)
        == CapabilityVerdict.PASSED_WITH_WARNINGS
    )


def test_required_indeterminate_outranks_optional_failure() -> None:
    """
    Verifies that an unverified required check blocks any PASSED claim, even
    when a non-required check produced a definite warning.
    """
    # Precondition.
    results = [
        _result(CapabilityCheckStatus.FAILED, required=False),
        _result(CapabilityCheckStatus.INDETERMINATE, required=True),
    ]

    # Under test and postcondition.
    assert (
        aggregate_capability_verdict(True, results) == CapabilityVerdict.INDETERMINATE
    )


def test_optional_failure_outranks_optional_indeterminate() -> None:
    """
    Verifies that with the required core verified, a definite warning outranks
    a transient non-required indeterminate.
    """
    # Precondition.
    results = [
        _result(CapabilityCheckStatus.PASSED, required=True),
        _result(CapabilityCheckStatus.FAILED, required=False),
        _result(CapabilityCheckStatus.INDETERMINATE, required=False),
    ]

    # Under test and postcondition.
    assert (
        aggregate_capability_verdict(True, results)
        == CapabilityVerdict.PASSED_WITH_WARNINGS
    )


def test_indeterminate_without_failures() -> None:
    """
    Verifies that a transient error yields INDETERMINATE when nothing failed.
    """
    # Precondition.
    results = [
        _result(CapabilityCheckStatus.PASSED),
        _result(CapabilityCheckStatus.INDETERMINATE),
    ]

    # Under test and postcondition.
    assert (
        aggregate_capability_verdict(True, results) == CapabilityVerdict.INDETERMINATE
    )


def test_all_skipped_yields_skipped() -> None:
    """Verifies that a run with only skipped checks is SKIPPED, not PASSED."""
    # Precondition.
    results = [
        _result(CapabilityCheckStatus.SKIPPED),
        _result(CapabilityCheckStatus.SKIPPED),
    ]

    # Under test and postcondition.
    assert aggregate_capability_verdict(True, results) == CapabilityVerdict.SKIPPED


def test_empty_results_yield_skipped() -> None:
    """Verifies that an applicable capability with zero checks is SKIPPED."""
    # Under test and postcondition.
    assert aggregate_capability_verdict(True, []) == CapabilityVerdict.SKIPPED


def test_skipped_mixed_with_passed_yields_passed() -> None:
    """Verifies that partial skips do not mask passing required checks."""
    # Precondition.
    results = [
        _result(CapabilityCheckStatus.PASSED),
        _result(CapabilityCheckStatus.SKIPPED),
    ]

    # Under test and postcondition.
    assert aggregate_capability_verdict(True, results) == CapabilityVerdict.PASSED


def test_all_passed_yields_passed() -> None:
    """Verifies the all-green case."""
    # Precondition.
    results = [_result(CapabilityCheckStatus.PASSED)]

    # Under test and postcondition.
    assert aggregate_capability_verdict(True, results) == CapabilityVerdict.PASSED


def test_compute_capability_verdicts_slack_shaped_scenario() -> None:
    """Verifies per-capability grouping for a Slack-shaped report."""
    # Precondition.
    # Indexing passes, doc perm sync has a required failure, and group sync is
    # not applicable (Slack has none by design).
    results = [
        _result(CapabilityCheckStatus.PASSED, capability=CredentialCapability.INDEXING),
        _result(
            CapabilityCheckStatus.FAILED,
            capability=CredentialCapability.DOC_PERMISSION_SYNC,
        ),
    ]
    applicable = {
        CredentialCapability.INDEXING,
        CredentialCapability.DOC_PERMISSION_SYNC,
    }

    # Under test.
    verdicts = compute_capability_verdicts(applicable, results)

    # Postcondition.
    assert verdicts == {
        CredentialCapability.INDEXING: CapabilityVerdict.PASSED,
        CredentialCapability.DOC_PERMISSION_SYNC: CapabilityVerdict.FAILED,
        CredentialCapability.EXTERNAL_GROUP_SYNC: CapabilityVerdict.NOT_APPLICABLE,
    }
