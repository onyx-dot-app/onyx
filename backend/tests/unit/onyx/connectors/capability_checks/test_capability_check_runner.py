import time
from collections.abc import Callable
from typing import cast
from unittest.mock import MagicMock

import pytest

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


class _CallableCheck(CapabilityCheck):
    """Concrete check that delegates ``run`` to an injected callable."""

    def __init__(
        self,
        run: Callable[[CapabilityCheckContext], None],
        check_id: str = "dummy_check",
        required: bool = True,
        requires_connector_instance: bool = False,
        requires_connector_config: bool = False,
        capability: CredentialCapability = CredentialCapability.INDEXING,
        timeout_seconds: float | None = None,
        is_fallback: bool = False,
    ) -> None:
        super().__init__(
            capability=capability,
            check_id=check_id,
            display_name="Dummy check",
            required=required,
            requires_connector_instance=requires_connector_instance,
            requires_connector_config=requires_connector_config,
            timeout_seconds=timeout_seconds,
            is_fallback=is_fallback,
        )
        self._run = run

    def run(self, context: CapabilityCheckContext) -> None:
        self._run(context)


class _OtherCallableCheck(_CallableCheck):
    """Second concrete class, for the mirrored-check class-identity guard."""


def _context(
    connector: BaseConnector | None = None,
    connector_specific_config: dict | None = None,
    instantiation_error: Exception | None = None,
) -> CapabilityCheckContext:
    return CapabilityCheckContext(
        source=DocumentSource.SLACK,
        credential_json={},
        connector=connector,
        connector_specific_config=connector_specific_config,
        instantiation_error=instantiation_error,
    )


def test_passing_check_maps_to_passed() -> None:
    """Verifies that a check returning without raising is PASSED."""
    # Precondition.
    check = _CallableCheck(lambda _context: None)

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

    check = _CallableCheck(run)

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

    check = _CallableCheck(run)

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

    check = _CallableCheck(run)

    # Under test.
    results = run_capability_checks([check], _context())

    # Postcondition.
    assert results[0].status == CapabilityCheckStatus.INDETERMINATE
    assert results[0].error_type == "RuntimeError"


def test_skips_instance_requiring_check_without_connector() -> None:
    """Verifies the skip path for checks that need a connector instance."""
    # Precondition.
    run = MagicMock()
    check = _CallableCheck(run, requires_connector_instance=True)

    # Under test.
    results = run_capability_checks([check], _context(connector=None))

    # Postcondition.
    assert results[0].status == CapabilityCheckStatus.SKIPPED
    run.assert_not_called()


def test_validation_instantiation_error_fails_instance_checks() -> None:
    """
    Verifies a validation-family construction failure is FAILED, not SKIPPED.
    """
    # Precondition.
    run = MagicMock()
    check = _CallableCheck(run, requires_connector_instance=True)
    context = _context(
        connector=None,
        instantiation_error=InsufficientPermissionsError("Token lacks scopes."),
    )

    # Under test.
    results = run_capability_checks([check], context)

    # Postcondition.
    assert results[0].status == CapabilityCheckStatus.FAILED
    assert results[0].error_type == "InsufficientPermissionsError"
    assert "Token lacks scopes." in results[0].message
    run.assert_not_called()


def test_unexpected_instantiation_error_is_indeterminate() -> None:
    """
    Verifies an unrecognized construction failure maps to INDETERMINATE.
    """
    # Precondition.
    check = _CallableCheck(MagicMock(), requires_connector_instance=True)
    context = _context(
        connector=None, instantiation_error=RuntimeError("Redis unreachable.")
    )

    # Under test.
    results = run_capability_checks([check], context)

    # Postcondition.
    assert results[0].status == CapabilityCheckStatus.INDETERMINATE
    assert results[0].error_type == "RuntimeError"


def test_skips_config_requiring_check_even_with_connector() -> None:
    """
    Verifies that config-requiring checks skip when only an instance exists.
    """
    # Precondition.
    run = MagicMock()
    check = _CallableCheck(run, requires_connector_config=True)
    connector = cast(BaseConnector, MagicMock(spec=BaseConnector))

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
    check = _CallableCheck(run, requires_connector_config=True)

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
        _CallableCheck(failing_run, check_id="failing_check"),
        _CallableCheck(lambda _context: None, check_id="passing_check"),
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
    """
    Verifies that the per-check hang guard yields INDETERMINATE, not FAILED.
    """
    # Precondition.
    # The sleep must exceed the timeout.
    timeout_seconds = 0.5
    slow_run_duration_seconds = 1
    assert slow_run_duration_seconds > timeout_seconds

    def slow_run(_context: CapabilityCheckContext) -> None:
        time.sleep(slow_run_duration_seconds)

    check = _CallableCheck(slow_run, timeout_seconds=timeout_seconds)

    # Under test.
    results = run_capability_checks([check], _context())

    # Postcondition.
    assert results[0].status == CapabilityCheckStatus.INDETERMINATE
    assert results[0].error_type == "TimeoutError"
    assert "timed out" in results[0].message


def test_shared_check_id_executes_once_and_mirrors() -> None:
    """
    Verifies the shared perm-sync fallback contract: one execution, two results.
    """
    # Precondition.
    # One check_id registered under both sync capabilities.
    call_count = 0

    def shared_run(_context: CapabilityCheckContext) -> None:
        nonlocal call_count
        call_count += 1
        raise InsufficientPermissionsError("Missing directory scope.")

    checks = [
        _CallableCheck(
            shared_run,
            check_id="perm_sync",
            capability=CredentialCapability.DOC_PERMISSION_SYNC,
        ),
        _CallableCheck(
            shared_run,
            check_id="perm_sync",
            capability=CredentialCapability.EXTERNAL_GROUP_SYNC,
        ),
    ]

    # Under test.
    results = run_capability_checks(checks, _context())

    # Postcondition.
    # Both capabilities carry the mirrored outcome.
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


def test_shared_callable_with_distinct_check_ids_runs_independently() -> None:
    """
    Verifies distinct checks are never collapsed by a shared implementation.
    """
    # Precondition.
    shared_run = MagicMock(return_value=None)
    checks = [
        _CallableCheck(shared_run, check_id="first_check"),
        _CallableCheck(shared_run, check_id="second_check"),
    ]

    # Under test.
    run_capability_checks(checks, _context())

    # Postcondition.
    assert shared_run.call_count == 2


def test_duplicate_check_id_within_a_capability_is_rejected() -> None:
    """Verifies a reused check_id within one capability is a hard error."""
    # Precondition.
    checks = [
        _CallableCheck(MagicMock(return_value=None), check_id="same_id"),
        _CallableCheck(MagicMock(return_value=None), check_id="same_id"),
    ]

    # Under test and postcondition.
    with pytest.raises(AssertionError, match="Duplicate check_id"):
        run_capability_checks(checks, _context())


def test_mirrored_check_id_across_classes_is_rejected() -> None:
    """Verifies cross-capability check_id reuse requires a single class."""
    # Precondition.
    checks = [
        _CallableCheck(
            MagicMock(return_value=None),
            check_id="perm_sync",
            capability=CredentialCapability.DOC_PERMISSION_SYNC,
        ),
        _OtherCallableCheck(
            MagicMock(return_value=None),
            check_id="perm_sync",
            capability=CredentialCapability.EXTERNAL_GROUP_SYNC,
        ),
    ]

    # Under test and postcondition.
    with pytest.raises(AssertionError, match="must be one class"):
        run_capability_checks(checks, _context())


def test_is_fallback_propagates_to_result() -> None:
    """Verifies that result rows carry the fallback marker for FE labeling."""
    # Precondition.
    check = _CallableCheck(lambda _context: None, is_fallback=True)

    # Under test.
    results = run_capability_checks([check], _context())

    # Postcondition.
    assert results[0].is_fallback is True
