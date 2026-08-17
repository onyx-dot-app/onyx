import time
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel
from sqlalchemy.orm import Session

from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
    CapabilityCheckResult,
    CapabilityCheckStatus,
    CapabilityCheckTrigger,
    CredentialCapability,
    CredentialCapabilityReport,
    compute_capability_verdicts,
)
from onyx.connectors.capability_checks.registry import (
    get_applicable_capabilities,
    get_capability_checks,
)
from onyx.connectors.credentials_provider import build_db_credentials_provider
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    UnexpectedValidationError,
)
from onyx.connectors.factory import identify_connector_class, instantiate_connector
from onyx.connectors.interfaces import BaseConnector
from onyx.connectors.models import InputType
from onyx.connectors.source_operations import (
    SourceOperations,
    get_source_operations_class,
)
from onyx.db.models import Credential
from onyx.utils.credential_audit import emit_credential_access
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


def _missing_instance_outcome(instantiation_error: Exception | None) -> _CheckOutcome:
    """
    Maps a missing connector instance to an outcome for an instance-requiring
    check.

    A config-less run skips: most connectors cannot be constructed without
    configuration, and that is not a credential problem. A construction failure
    with a supplied config is real signal and follows the check exception
    contract (``ConnectorValidationError`` is FAILED, anything else
    INDETERMINATE).
    """
    if instantiation_error is None:
        return _CheckOutcome(
            status=CapabilityCheckStatus.SKIPPED,
            message=_SKIP_NEEDS_INSTANCE_MESSAGE,
        )
    if isinstance(instantiation_error, ConnectorValidationError):
        return _CheckOutcome(
            status=CapabilityCheckStatus.FAILED,
            message=str(instantiation_error),
            error_type=type(instantiation_error).__name__,
        )
    return _CheckOutcome(
        status=CapabilityCheckStatus.INDETERMINATE,
        message=str(instantiation_error),
        error_type=type(instantiation_error).__name__,
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
        unrunnable_outcome: _CheckOutcome | None = None
        if (
            check.requires_connector_config
            and context.connector_specific_config is None
        ):
            unrunnable_outcome = _CheckOutcome(
                status=CapabilityCheckStatus.SKIPPED,
                message=_SKIP_NEEDS_CONFIG_MESSAGE,
            )
        elif check.requires_connector_instance and context.connector is None:
            unrunnable_outcome = _missing_instance_outcome(context.instantiation_error)
        if unrunnable_outcome is not None:
            results.append(_build_result(check, unrunnable_outcome))
            continue

        if check.check_id not in outcome_by_check_id:
            outcome_by_check_id[check.check_id] = _execute_check(check, context)
        results.append(_build_result(check, outcome_by_check_id[check.check_id]))
    return results


def generate_capability_report(
    db_session: Session,
    credential: Credential,
    connector_specific_config: dict[str, Any] | None = None,
    connector_id: int | None = None,
    input_type: InputType | None = None,
    trigger: CapabilityCheckTrigger = CapabilityCheckTrigger.MANUAL,
) -> CredentialCapabilityReport:
    """Runs every capability check for a credential and packages a report.

    Check failures are report content; this raises only for programmer errors
    (e.g. a source with no connector class). Without a
    ``connector_specific_config``, instantiation is attempted with an empty
    config; when construction raises, instance-requiring checks are SKIPPED.
    When a supplied config fails to instantiate, the failure is surfaced on
    instance-requiring checks instead (see ``_missing_instance_outcome``).
    Unlike ``validate_ccpair_for_user``, no source is exempted: MOCK_CONNECTOR
    must run so integration tests can exercise the full pipeline.
    """
    source = credential.source
    checks = get_capability_checks(source)
    # Fail loudly for programmer errors (a source with no connector class)
    # rather than degrading them to skips in the guarded instantiation below.
    identify_connector_class(source, input_type)

    # Config-less runs attempt instantiation with an empty config: some
    # connectors happen to construct with one, giving unmigrated sources a basic
    # credential-time probe. There is deliberately no per-connector extension
    # point for this.
    instantiation_config = (
        connector_specific_config if connector_specific_config is not None else {}
    )
    connector: BaseConnector | None = None
    instantiation_error: Exception | None = None
    try:
        connector = instantiate_connector(
            db_session=db_session,
            source=source,
            input_type=input_type,
            connector_specific_config=instantiation_config,
            credential=credential,
        )
    except Exception as e:
        # A config-less probe construction fails routinely and stays a skip; a
        # failure with the real config is actionable and is surfaced on
        # instance-requiring checks.
        if connector_specific_config is not None:
            instantiation_error = e
        logger.warning(
            "Could not instantiate %s connector for capability checks: %s",
            source,
            e,
        )

    # Migrated sources always get their gateway constructed: construction is
    # lazy (no client build or decrypt until an operation runs), and checks
    # treat a registered-but-missing gateway as a programmer error.
    source_operations: SourceOperations | None = None
    source_operations_class = get_source_operations_class(source)
    if source_operations_class is not None:
        source_operations = source_operations_class(
            credentials_provider=build_db_credentials_provider(source, credential.id),
            connector_specific_config=connector_specific_config,
        )

    if credential.credential_json:
        # Distinct decrypt site from ``instantiate_connector``'s paths (which
        # may not have decrypted at all when instantiation fails). Audit is
        # best-effort and never raises.
        emit_credential_access(
            credential_type="connector",
            provider=str(source),
            row_id=credential.id,
        )
    credential_json = (
        credential.credential_json.get_value(apply_mask=False)
        if credential.credential_json
        else {}
    )
    context = CapabilityCheckContext(
        source=source,
        credential_json=credential_json,
        connector=connector,
        # The supplied config only, never the empty instantiation config: checks
        # marked requires_connector_config must skip on config-less runs rather
        # than probe an empty dict.
        connector_specific_config=connector_specific_config,
        instantiation_error=instantiation_error,
        source_operations=source_operations,
    )
    results = run_capability_checks(checks, context)
    return CredentialCapabilityReport(
        credential_id=credential.id,
        source=source,
        connector_id=connector_id,
        checked_at=datetime.now(timezone.utc),
        trigger=trigger,
        verdicts=compute_capability_verdicts(
            get_applicable_capabilities(source), results
        ),
        check_results=results,
    )
