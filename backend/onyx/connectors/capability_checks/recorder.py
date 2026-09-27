"""Best-effort persistence of blocking-validation outcomes.

The blocking paths (cc-pair validation, indexing-run start) already probe the
source; this module records what they found as a fallback-shaped capability
report, so reports accumulate before any check-running infrastructure exists. It
runs no checks of its own.

Deliberately import-light: the hook sites live in ``factory.py`` and the
docfetching hot path, so this module must not pull in the check registry (which
eagerly imports every migrated connector's check module) or the runner (which
imports ``factory``).
"""

from datetime import datetime, timezone
from typing import Any

from onyx.configs.constants import DocumentSource
from onyx.connectors.capability_checks.applicability import (
    get_applicable_capabilities,
)
from onyx.connectors.capability_checks.models import (
    CapabilityCheckResult,
    CapabilityCheckStatus,
    CredentialCapability,
    CredentialCapabilityReport,
    compute_capability_verdicts,
    compute_connector_config_hash,
)
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.db.credential_capability import (
    upsert_completed_capability_report_unless_granular,
)
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import CapabilityCheckTrigger
from onyx.utils.logger import setup_logger

logger = setup_logger()


def _outcome_status(error: Exception | None) -> CapabilityCheckStatus:
    """Maps a blocking validation's outcome per the check exception contract."""
    if error is None:
        return CapabilityCheckStatus.PASSED
    if isinstance(error, ConnectorValidationError):
        return CapabilityCheckStatus.FAILED
    # ``UnexpectedValidationError`` and unrecognized exceptions alike: never
    # proof of a broken credential.
    return CapabilityCheckStatus.INDETERMINATE


def _synthesize_results(
    source: DocumentSource,
    applicable: set[CredentialCapability],
    error: Exception | None,
    perm_sync_validated: bool,
) -> list[CapabilityCheckResult]:
    """Builds fallback-shaped results mirroring what the blocking path ran.

    Perm-sync rows appear only when the caller knows ``validate_perm_sync`` ran
    (the success path with sync access). On failure the outcome cannot be
    attributed between the settings and perm-sync probes, so only the INDEXING
    row carries it.
    """
    status = _outcome_status(error)
    message = str(error) if error is not None else ""
    error_type = type(error).__name__ if error is not None else None
    results = [
        CapabilityCheckResult(
            capability=CredentialCapability.INDEXING,
            check_id=f"{source.value}_connector_settings",
            display_name="Connector settings validation",
            required=True,
            status=status,
            message=message,
            error_type=error_type,
            is_fallback=True,
        )
    ]
    if perm_sync_validated:
        results.extend(
            CapabilityCheckResult(
                capability=capability,
                check_id=f"{source.value}_perm_sync",
                display_name="Permission sync validation",
                required=True,
                status=status,
                message=message,
                error_type=error_type,
                is_fallback=True,
            )
            for capability in applicable - {CredentialCapability.INDEXING}
        )
    return results


def record_blocking_validation_outcome(
    *,
    credential_id: int,
    connector_id: int,
    source: DocumentSource,
    trigger: CapabilityCheckTrigger,
    error: Exception | None,
    perm_sync_validated: bool,
    connector_specific_config: dict[str, Any] | None,
) -> None:
    """Persists one blocking validation's outcome; never raises.

    Uses its own session so the caller's in-flight transaction is untouched, and
    never overwrites a granular (named-checks) report with this coarse
    fallback-shaped record: the no-clobber guard is part of the upsert statement
    itself, so a concurrent granular write cannot race it.
    """
    try:
        applicable = get_applicable_capabilities(source)
        results = _synthesize_results(source, applicable, error, perm_sync_validated)
        report = CredentialCapabilityReport(
            credential_id=credential_id,
            source=source,
            connector_id=connector_id,
            checked_at=datetime.now(timezone.utc),
            trigger=trigger,
            verdicts=compute_capability_verdicts(applicable, results),
            check_results=results,
        )
        with get_session_with_current_tenant() as db_session:
            upsert_completed_capability_report_unless_granular(
                db_session,
                credential_id=credential_id,
                connector_id=connector_id,
                source=source,
                trigger=trigger,
                report=report,
                connector_config_hash=compute_connector_config_hash(
                    connector_specific_config
                ),
            )
            # The accessors leave the transaction to the caller, and the session
            # context manager closes without committing.
            db_session.commit()
    except Exception:
        logger.warning(
            "Failed to record a blocking validation outcome for credential %s.",
            credential_id,
            exc_info=True,
        )
