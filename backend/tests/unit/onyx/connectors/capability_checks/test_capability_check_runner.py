import time
from collections.abc import Callable
from typing import cast
from unittest.mock import MagicMock

from onyx.configs.constants import DocumentSource
from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
    CapabilityCheckStatus,
    CredentialCapability,
)
from onyx.connectors.capability_checks.runner import run_capability_checks
from onyx.connectors.exceptions import (
    InsufficientPermissionsError,
    UnexpectedValidationError,
)
from onyx.connectors.interfaces import BaseConnector


def _make_check(
    run: Callable[[CapabilityCheckContext], None],
    check_id: str = "dummy_check",
    required: bool = True,
    requires_connector_instance: bool = False,
    requires_connector_config: bool = False,
    capability: CredentialCapability = CredentialCapability.INDEXING,
    timeout_seconds: int | None = None,
    is_fallback: bool = False,
) -> CapabilityCheck:
    return CapabilityCheck(
        capability=capability,
        check_id=check_id,
        display_name="Dummy check",
        run=run,
        required=required,
        requires_connector_instance=requires_connector_instance,
        requires_connector_config=requires_connector_config,
        timeout_seconds=timeout_seconds,
        is_fallback=is_fallback,
    )


def _context(
    connector: BaseConnector | None = None,
    connector_specific_config: dict | None = None,
) -> CapabilityCheckContext:
    return CapabilityCheckContext(
        source=DocumentSource.SLACK,
        credential_json={},
        connector=connector,
        connector_specific_config=connector_specific_config,
    )


def test_passing_check_maps_to_passed() -> None:
    """Verifies that a check returning without raising is PASSED."""
    # Precondition.
    check = _make_check(lambda _context: None)

    # Under test.
    results = run_capability_checks([check], _context())

    # Postcondition.
    assert len(results) == 1
    assert results[0].status == CapabilityCheckStatus.PASSED
    assert results[0].message == ""
    assert results[0].error_type is None
    assert results[0].duration_ms is not None


def test_connector_validation_error_maps_to_failed() -> None:
    """Verifies that the ``ConnectorValidationError`` family is FAILED."""

    # Precondition.
    def run(_context: CapabilityCheckContext) -> None:
        raise InsufficientPermissionsError("Missing `channels:read`.")

    check = _make_check(run)

    # Under test.
    results = run_capability_checks([check], _context())

    # Postcondition.
    assert results[0].status == CapabilityCheckStatus.FAILED
    assert results[0].error_type == "InsufficientPermissionsError"
    assert "channels:read" in results[0].message


def test_unexpected_validation_error_maps_to_indeterminate() -> None:
    """Verifies that ``UnexpectedValidationError`` is transient, not FAILED."""

    # Precondition.
    def run(_context: CapabilityCheckContext) -> None:
        raise UnexpectedValidationError("Slack rate limited the check.")

    check = _make_check(run)

    # Under test.
    results = run_capability_checks([check], _context())

    # Postcondition.
    assert results[0].status == CapabilityCheckStatus.INDETERMINATE
    assert results[0].error_type == "UnexpectedValidationError"


def test_unknown_exception_maps_to_indeterminate() -> None:
    """Verifies that unrecognized exceptions never count as real failures."""

    # Precondition.
    def run(_context: CapabilityCheckContext) -> None:
        raise RuntimeError("Boom.")

    check = _make_check(run)

    # Under test.
    results = run_capability_checks([check], _context())

    # Postcondition.
    assert results[0].status == CapabilityCheckStatus.INDETERMINATE
    assert results[0].error_type == "RuntimeError"


def test_skips_instance_requiring_check_without_connector() -> None:
    """Verifies the skip path for checks that need a connector instance."""
    # Precondition.
    run = MagicMock()
    check = _make_check(run, requires_connector_instance=True)

    # Under test.
    results = run_capability_checks([check], _context(connector=None))

    # Postcondition.
    assert results[0].status == CapabilityCheckStatus.SKIPPED
    run.assert_not_called()


def test_skips_config_requiring_check_even_with_connector() -> None:
    """Verifies that config-requiring checks skip when only an instance exists."""
    # Precondition.
    run = MagicMock()
    check = _make_check(run, requires_connector_config=True)
    connector = cast(BaseConnector, MagicMock())

    # Under test.
    results = run_capability_checks(
        [check], _context(connector=connector, connector_specific_config=None)
    )

    # Postcondition.
    assert results[0].status == CapabilityCheckStatus.SKIPPED
    run.assert_not_called()


def test_config_requiring_check_runs_with_config() -> None:
    """Verifies that a supplied config unlocks config-requiring checks."""
    # Precondition.
    run = MagicMock(return_value=None)
    check = _make_check(run, requires_connector_config=True)

    # Under test.
    results = run_capability_checks(
        [check], _context(connector_specific_config={"channels": ["general"]})
    )

    # Postcondition.
    assert results[0].status == CapabilityCheckStatus.PASSED
    run.assert_called_once()


def test_failure_does_not_stop_subsequent_checks() -> None:
    """Verifies that the runner continues past failing checks."""

    # Precondition.
    def failing_run(_context: CapabilityCheckContext) -> None:
        raise InsufficientPermissionsError("Missing scope.")

    checks = [
        _make_check(failing_run, check_id="failing_check"),
        _make_check(lambda _context: None, check_id="passing_check"),
    ]

    # Under test.
    results = run_capability_checks(checks, _context())

    # Postcondition.
    assert [result.status for result in results] == [
        CapabilityCheckStatus.FAILED,
        CapabilityCheckStatus.PASSED,
    ]
    assert [result.check_id for result in results] == [
        "failing_check",
        "passing_check",
    ]


def test_timeout_maps_to_indeterminate() -> None:
    """Verifies that the per-check hang guard yields INDETERMINATE, not FAILED."""

    # Precondition. The sleep must exceed the one-second guard.
    def slow_run(_context: CapabilityCheckContext) -> None:
        time.sleep(2)

    check = _make_check(slow_run, timeout_seconds=1)

    # Under test.
    results = run_capability_checks([check], _context())

    # Postcondition.
    assert results[0].status == CapabilityCheckStatus.INDETERMINATE
    assert results[0].error_type == "TimeoutError"
    assert "timed out" in results[0].message


def test_shared_run_callable_executes_once_and_mirrors() -> None:
    """Verifies the shared perm-sync fallback contract: one execution, two results."""
    # Precondition. One callable registered under both sync capabilities.
    call_count = 0

    def shared_run(_context: CapabilityCheckContext) -> None:
        nonlocal call_count
        call_count += 1
        raise InsufficientPermissionsError("Missing directory scope.")

    checks = [
        _make_check(
            shared_run,
            check_id="perm_sync",
            capability=CredentialCapability.DOC_PERMISSION_SYNC,
        ),
        _make_check(
            shared_run,
            check_id="perm_sync",
            capability=CredentialCapability.EXTERNAL_GROUP_SYNC,
        ),
    ]

    # Under test.
    results = run_capability_checks(checks, _context())

    # Postcondition. Both capabilities carry the mirrored outcome.
    assert call_count == 1
    assert [result.status for result in results] == [
        CapabilityCheckStatus.FAILED,
        CapabilityCheckStatus.FAILED,
    ]
    assert {result.capability for result in results} == {
        CredentialCapability.DOC_PERMISSION_SYNC,
        CredentialCapability.EXTERNAL_GROUP_SYNC,
    }
    assert all("directory scope" in result.message for result in results)


def test_distinct_callables_are_not_memoized_together() -> None:
    """Verifies memoization keys on callable identity, not check metadata."""
    # Precondition.
    first_run = MagicMock(return_value=None)
    second_run = MagicMock(return_value=None)
    checks = [
        _make_check(first_run, check_id="same_id"),
        _make_check(second_run, check_id="same_id"),
    ]

    # Under test.
    run_capability_checks(checks, _context())

    # Postcondition.
    first_run.assert_called_once()
    second_run.assert_called_once()


def test_is_fallback_propagates_to_result() -> None:
    """Verifies that result rows carry the fallback marker for FE labeling."""
    # Precondition.
    check = _make_check(lambda _context: None, is_fallback=True)

    # Under test.
    results = run_capability_checks([check], _context())

    # Postcondition.
    assert results[0].is_fallback is True
