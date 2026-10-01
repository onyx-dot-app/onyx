"""Named capability checks when a cc-pair is created or its credential swapped.

For a source with named checks, this replaces the legacy blocking validation
(``validate_connector_settings`` and ``validate_perm_sync``). It runs the
source's checks synchronously for the pairing's access type and stores the full
report. A fresh result of a draft run on the same form is reused, so the check
does not run again. Only a failed required check blocks the pairing:
INDETERMINATE is transient, and skipped checks do not apply.
"""

from datetime import timedelta
from typing import Any
from uuid import UUID

from onyx.configs.constants import DocumentSource
from onyx.connectors.capability_checks.applicability import (
    get_applicable_capabilities,
)
from onyx.connectors.capability_checks.draft_runs import (
    CachedDraftResult,
    DraftCheckStateKind,
    cached_check_result,
    draft_result_cache_key,
    get_cached_draft_result,
)
from onyx.connectors.capability_checks.form_state import validate_form_state
from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckStatus,
    compute_capability_verdicts,
    compute_connector_config_hash,
)
from onyx.connectors.capability_checks.registry import get_capability_checks
from onyx.connectors.capability_checks.runner import generate_capability_report
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.models import InputType
from onyx.connectors.registry import CONNECTOR_CLASS_MAP
from onyx.db.credential_capability import (
    mark_capability_report_running,
    mark_capability_run_failed,
    upsert_completed_capability_report,
)
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import AccessType, CapabilityCheckTrigger
from onyx.db.models import Credential
from onyx.utils.logger import setup_logger

logger = setup_logger()

_TRIGGER = CapabilityCheckTrigger.CC_PAIR_VALIDATION


def _fresh_draft_results(
    checks: list[CapabilityCheck[Any]],
    *,
    credential: Credential,
    source: DocumentSource,
    access_type: AccessType,
    connector_specific_config: dict[str, Any],
) -> dict[str, CachedDraftResult]:
    """check_id to its cached draft result, for the checks a draft run already
    ran with this credential, access type and form values. A cached FAILED
    result is left out, so the check runs again: the source may have been
    fixed since, and a client without a draft run cannot ask for a re-run."""
    form_values = validate_form_state(
        CONNECTOR_CLASS_MAP[source].config_class, connector_specific_config
    ).values
    fresh: dict[str, CachedDraftResult] = {}
    for check in checks:
        cached = get_cached_draft_result(
            draft_result_cache_key(
                credential_id=credential.id,
                credential_updated_at=credential.time_updated,
                source=source,
                access_type=access_type,
                check=check,
                form_values=form_values,
            )
        )
        if cached is not None and cached.state != DraftCheckStateKind.FAILED:
            fresh[check.check_id] = cached
    return fresh


def _mark_running(
    *, credential_id: int, connector_id: int, source: DocumentSource
) -> UUID | None:
    """Claims the pairing's report row for this run, also from a run in flight.
    This run decides the pairing, so its report is the one to keep; the fence
    drops the terminal writes of the replaced run."""
    with get_session_with_current_tenant() as db_session:
        row = mark_capability_report_running(
            db_session,
            credential_id=credential_id,
            connector_id=connector_id,
            source=source,
            trigger=_TRIGGER,
            active_within=timedelta(0),
        )
        db_session.commit()
        return row.run_id if row is not None else None


def validate_pairing_with_named_checks(
    *,
    connector_id: int,
    source: DocumentSource,
    input_type: InputType | None,
    connector_specific_config: dict[str, Any],
    credential: Credential,
    access_type: AccessType,
    enforce_creation: bool,
) -> bool:
    """Runs the source's named checks for a new pairing and stores the report.

    Returns False when a required check failed and ``enforce_creation`` is
    False; True otherwise.

    Raises:
        ConnectorValidationError: A required check failed and
            ``enforce_creation`` is True. The message names each failed check.
    """
    checks = get_capability_checks(source)
    reused = _fresh_draft_results(
        checks,
        credential=credential,
        source=source,
        access_type=access_type,
        connector_specific_config=connector_specific_config,
    )
    run_id = _mark_running(
        credential_id=credential.id, connector_id=connector_id, source=source
    )
    # Every write after the claim is in this block, so a failure anywhere
    # retires the RUNNING mark instead of leaving it until the stale sweep.
    try:
        report = generate_capability_report(
            credential,
            source=source,
            connector_specific_config=connector_specific_config,
            connector_id=connector_id,
            input_type=input_type,
            trigger=_TRIGGER,
            access_type=access_type,
            check_ids=frozenset(
                check.check_id for check in checks if check.check_id not in reused
            ),
        )
        ran = {
            (result.check_id, result.capability): result
            for result in report.check_results
        }
        results = [
            (
                cached_check_result(check, cached)
                if (cached := reused.get(check.check_id)) is not None
                else ran[(check.check_id, check.capability)]
            )
            for check in checks
        ]
        report = report.model_copy(
            update={
                "check_results": results,
                "verdicts": compute_capability_verdicts(
                    get_applicable_capabilities(source), results
                ),
            }
        )
        if run_id is None:
            logger.info(
                "A capability run for connector %s, credential %s started in the "
                "same instant; it writes the report.",
                connector_id,
                credential.id,
            )
        else:
            with get_session_with_current_tenant() as db_session:
                upsert_completed_capability_report(
                    db_session,
                    credential_id=credential.id,
                    connector_id=connector_id,
                    source=source,
                    trigger=_TRIGGER,
                    report=report,
                    connector_config_hash=compute_connector_config_hash(
                        connector_specific_config
                    ),
                    run_id=run_id,
                )
                db_session.commit()
    except Exception:
        if run_id is not None:
            with get_session_with_current_tenant() as db_session:
                mark_capability_run_failed(
                    db_session,
                    credential_id=credential.id,
                    connector_id=connector_id,
                    run_id=run_id,
                )
                db_session.commit()
        raise

    failed = [
        result
        for result in results
        if result.required and result.status == CapabilityCheckStatus.FAILED
    ]
    if not failed:
        return True
    if not enforce_creation:
        return False
    raise ConnectorValidationError(
        "Required capability checks failed: "
        + "; ".join(f"{result.display_name}: {result.message}" for result in failed)
    )
