import time
from collections.abc import Sequence

from pydantic import BaseModel

from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
    CapabilityCheckResult,
    CapabilityCheckStatus,
    CredentialCapability,
)
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    UnexpectedValidationError,
)
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import run_with_timeout

logger = setup_logger()

# Default per-check hang guard. Deliberately long: checks run async with no
# total budget, and a slow probe is vastly cheaper than a failed indexing run.
# Its sole purpose is to stop a stuck probe from blocking a worker thread
# forever. Known-slow probes override it via
# ``CapabilityCheck.timeout_seconds``.
CAPABILITY_CHECK_TIMEOUT_SECONDS = 600

_SKIP_NEEDS_INSTANCE_MESSAGE = (
    "Requires a connector instance -- will re-run automatically when the "
    "connector is instantiated."
)
_SKIP_NEEDS_CONFIG_MESSAGE = (
    "Requires connector configuration -- will re-run automatically when the "
    "connector is configured."
)
_TIMEOUT_MESSAGE = (
    "Check timed out; the source may be slow -- try re-running the checks."
)


class _CheckOutcome(BaseModel):
    """
    Outcome of one check execution, before it is joined with the check's
    metadata into a result row. Shared across checks with one check_id.
    """

    status: CapabilityCheckStatus
    message: str = ""
    error_type: str | None = None
    duration_ms: int | None = None


def _build_result(
    check: CapabilityCheck, outcome: _CheckOutcome
) -> CapabilityCheckResult:
    return CapabilityCheckResult(
        capability=check.capability,
        check_id=check.check_id,
        display_name=check.display_name,
        required=check.required,
        status=outcome.status,
        message=outcome.message,
        error_type=outcome.error_type,
        is_fallback=check.is_fallback,
        remediation=check.remediation,
        docs_link=check.docs_link,
        duration_ms=outcome.duration_ms,
    )


def _execute_check(
    check: CapabilityCheck, context: CapabilityCheckContext
) -> _CheckOutcome:
    """
    Executes one check under its hang guard and maps the outcome to a status.

    A timeout maps to INDETERMINATE, never FAILED; a slow source is not proof of
    a broken credential.
    """
    timeout_seconds = check.timeout_seconds or CAPABILITY_CHECK_TIMEOUT_SECONDS
    start = time.monotonic()

    def elapsed_ms() -> int:
        return int((time.monotonic() - start) * 1000)

    try:
        run_with_timeout(timeout_seconds, check.run, context)
    except ConnectorValidationError as e:
        return _CheckOutcome(
            status=CapabilityCheckStatus.FAILED,
            message=str(e),
            error_type=type(e).__name__,
            duration_ms=elapsed_ms(),
        )
    except TimeoutError as e:
        # ``run_with_timeout`` abandons the probe thread on timeout -- Python
        # has no safe thread cancellation -- so the probe may still have a
        # request in flight. Check bodies must keep per-request timeouts below
        # ``timeout_seconds`` so an abandoned probe dies with its current
        # request instead of running on.
        logger.warning(
            "Capability check %s timed out after %.0fs; its probe thread is "
            "abandoned and may still have a request in-flight.",
            check.check_id,
            timeout_seconds,
        )
        return _CheckOutcome(
            status=CapabilityCheckStatus.INDETERMINATE,
            message=_TIMEOUT_MESSAGE,
            error_type=type(e).__name__,
            duration_ms=elapsed_ms(),
        )
    except UnexpectedValidationError as e:
        return _CheckOutcome(
            status=CapabilityCheckStatus.INDETERMINATE,
            message=str(e),
            error_type=type(e).__name__,
            duration_ms=elapsed_ms(),
        )
    except Exception as e:
        logger.warning(
            "Capability check %s raised an unexpected error: %s",
            check.check_id,
            e,
        )
        return _CheckOutcome(
            status=CapabilityCheckStatus.INDETERMINATE,
            message=str(e),
            error_type=type(e).__name__,
            duration_ms=elapsed_ms(),
        )
    return _CheckOutcome(status=CapabilityCheckStatus.PASSED, duration_ms=elapsed_ms())


def run_capability_checks(
    checks: Sequence[CapabilityCheck],
    context: CapabilityCheckContext,
) -> list[CapabilityCheckResult]:
    """Runs checks sequentially and maps their outcomes to statuses.

    Sequential on purpose: source APIs can rate limit aggressively, so
    concurrent probes against the same credential are counterproductive. Check
    failures become result rows; this function never raises for them.

    Checks sharing one check_id (the perm-sync fallback registered under both
    sync capabilities) are one check surfaced per capability: they execute once
    and the outcome mirrors onto each result. Distinct check_ids always execute
    independently, even when they share an implementation.
    """
    # A check_id may repeat only as one check mirrored across capabilities;
    # anything else is a registration bug, caught before it silently collapses
    # distinct checks into one execution.
    check_class_by_id: dict[str, type[CapabilityCheck]] = {}
    seen_capability_ids: set[tuple[str, CredentialCapability]] = set()
    for check in checks:
        capability_id = (check.check_id, check.capability)
        assert capability_id not in seen_capability_ids, (
            f"Duplicate check_id {check.check_id!r} within capability "
            f"{check.capability.value}."
        )
        seen_capability_ids.add(capability_id)
        check_class = check_class_by_id.setdefault(check.check_id, type(check))
        assert check_class is type(check), (
            f"check_id {check.check_id!r} is shared by {check_class.__name__} "
            f"and {type(check).__name__}; mirrored checks must be one class."
        )

    results: list[CapabilityCheckResult] = []
    outcome_by_check_id: dict[str, _CheckOutcome] = {}
    for check in checks:
        skip_message: str | None = None
        if (
            check.requires_connector_config
            and context.connector_specific_config is None
        ):
            skip_message = _SKIP_NEEDS_CONFIG_MESSAGE
        elif check.requires_connector_instance and context.connector is None:
            skip_message = _SKIP_NEEDS_INSTANCE_MESSAGE
        if skip_message is not None:
            results.append(
                _build_result(
                    check,
                    _CheckOutcome(
                        status=CapabilityCheckStatus.SKIPPED,
                        message=skip_message,
                    ),
                )
            )
            continue

        if check.check_id not in outcome_by_check_id:
            outcome_by_check_id[check.check_id] = _execute_check(check, context)
        results.append(_build_result(check, outcome_by_check_id[check.check_id]))
    return results
