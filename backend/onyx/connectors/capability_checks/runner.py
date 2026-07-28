import time
from collections.abc import Callable, Sequence

from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
    CapabilityCheckResult,
    CapabilityCheckStatus,
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
# Its sole purpose is to stop a wedged probe from pinning a worker thread
# forever. Known-slow probes override it via ``CapabilityCheck.timeout_seconds``.
CAPABILITY_CHECK_TIMEOUT_SECONDS = 600

_SKIP_NEEDS_INSTANCE_MESSAGE = (
    "Requires a connector instance -- will re-run automatically "
    "when the connector is configured."
)
_SKIP_NEEDS_CONFIG_MESSAGE = (
    "Requires connector configuration -- will re-run automatically "
    "when the connector is configured."
)
_TIMEOUT_MESSAGE = (
    "Check timed out; the source may be slow -- try re-running the checks."
)

# Status, message, error_type, duration_ms of one executed check.
_CheckOutcome = tuple[CapabilityCheckStatus, str, str | None, int | None]


def _build_result(
    check: CapabilityCheck,
    status: CapabilityCheckStatus,
    message: str = "",
    error_type: str | None = None,
    duration_ms: int | None = None,
) -> CapabilityCheckResult:
    return CapabilityCheckResult(
        capability=check.capability,
        check_id=check.check_id,
        display_name=check.display_name,
        required=check.required,
        status=status,
        message=message,
        error_type=error_type,
        is_fallback=check.is_fallback,
        remediation=check.remediation,
        docs_link=check.docs_link,
        duration_ms=duration_ms,
    )


def _execute_check(
    check: CapabilityCheck, context: CapabilityCheckContext
) -> _CheckOutcome:
    """Executes one check under its hang guard and maps the outcome to a status.

    A timeout maps to INDETERMINATE, never FAILED: a slow source is not proof
    of a broken credential.
    """
    timeout_seconds = check.timeout_seconds or CAPABILITY_CHECK_TIMEOUT_SECONDS
    start = time.monotonic()

    def elapsed_ms() -> int:
        return int((time.monotonic() - start) * 1000)

    try:
        run_with_timeout(timeout_seconds, check.run, context)
    except ConnectorValidationError as e:
        return CapabilityCheckStatus.FAILED, str(e), type(e).__name__, elapsed_ms()
    except TimeoutError as e:
        return (
            CapabilityCheckStatus.INDETERMINATE,
            _TIMEOUT_MESSAGE,
            type(e).__name__,
            elapsed_ms(),
        )
    except UnexpectedValidationError as e:
        return (
            CapabilityCheckStatus.INDETERMINATE,
            str(e),
            type(e).__name__,
            elapsed_ms(),
        )
    except Exception as e:
        logger.warning(
            "Capability check %s raised an unexpected error: %s",
            check.check_id,
            e,
        )
        return (
            CapabilityCheckStatus.INDETERMINATE,
            str(e),
            type(e).__name__,
            elapsed_ms(),
        )
    return CapabilityCheckStatus.PASSED, "", None, elapsed_ms()


def run_capability_checks(
    checks: Sequence[CapabilityCheck],
    context: CapabilityCheckContext,
) -> list[CapabilityCheckResult]:
    """Runs checks sequentially and maps their outcomes to statuses.

    Sequential on purpose: source APIs (e.g. Slack) rate limit aggressively,
    so concurrent probes against the same credential are counterproductive.
    Check failures become result rows; this function never raises for them.

    Checks sharing one run callable (the perm-sync fallback registered under
    both sync capabilities) execute once; the outcome mirrors onto each result.
    """
    results: list[CapabilityCheckResult] = []
    outcome_by_run_callable: dict[
        Callable[[CapabilityCheckContext], None], _CheckOutcome
    ] = {}
    for check in checks:
        if (
            check.requires_connector_config
            and context.connector_specific_config is None
        ):
            results.append(
                _build_result(
                    check, CapabilityCheckStatus.SKIPPED, _SKIP_NEEDS_CONFIG_MESSAGE
                )
            )
            continue
        if check.requires_connector_instance and context.connector is None:
            results.append(
                _build_result(
                    check, CapabilityCheckStatus.SKIPPED, _SKIP_NEEDS_INSTANCE_MESSAGE
                )
            )
            continue

        if check.run not in outcome_by_run_callable:
            outcome_by_run_callable[check.run] = _execute_check(check, context)
        status, message, error_type, duration_ms = outcome_by_run_callable[check.run]
        results.append(_build_result(check, status, message, error_type, duration_ms))
    return results
