"""Holds a pair's first index attempt until its required capability checks
pass.

The attempt is created as usual, but its docfetching task is sent only when
no hold applies. The hold reads the pair's connector-scoped report (credential
+ connector):

- A run in flight holds.
- A dead run holds: FAILED_TO_RUN, or a RUNNING mark past the stale cutoff
  (the sweep retires it to FAILED_TO_RUN). The admin re-runs the checks. A
  stored report that cannot be read holds the same way.
- A required, applicable check that FAILED holds. INDETERMINATE and SKIPPED
  do not.

A pair with a dispatched index attempt, a pair without a report, and a source
without named checks are never held. Nothing is held while
CONNECTOR_CHECKS_ENABLED is off.
"""

from datetime import datetime, timedelta

from pydantic import ValidationError
from sqlalchemy.orm import Session

from onyx.configs.app_configs import CONNECTOR_CHECKS_ENABLED
from onyx.connectors.capability_checks.indexing_hold_models import (
    HeldCheck,
    IndexingHold,
    IndexingHoldReason,
)
from onyx.connectors.capability_checks.models import (
    CapabilityCheckStatus,
    CredentialCapabilityReport,
)
from onyx.connectors.capability_checks.registry import has_named_capability_checks
from onyx.connectors.capability_checks.runner import capability_check_run_stale_after
from onyx.db.credential_capability import get_capability_report_row
from onyx.db.engine.time_utils import get_db_current_time
from onyx.db.enums import CapabilityReportRunStatus
from onyx.db.index_attempt import cc_pair_has_dispatched_index_attempts
from onyx.db.models import ConnectorCredentialPair, CredentialCapabilityReportRow
from onyx.utils.logger import setup_logger

logger = setup_logger()


def decide_indexing_hold(
    row: CredentialCapabilityReportRow, *, now: datetime, stale_after: timedelta
) -> IndexingHold | None:
    """The hold that the report row puts on a pair's first index attempt."""
    if row.run_status == CapabilityReportRunStatus.RUNNING:
        if row.run_started_at is not None and row.run_started_at >= now - stale_after:
            return IndexingHold(reason=IndexingHoldReason.CHECKS_RUNNING)
        return IndexingHold(reason=IndexingHoldReason.CHECKS_FAILED_TO_RUN)
    if row.run_status == CapabilityReportRunStatus.FAILED_TO_RUN:
        return IndexingHold(reason=IndexingHoldReason.CHECKS_FAILED_TO_RUN)
    if row.report is None:
        return None
    try:
        report = CredentialCapabilityReport.model_validate(row.report)
    except ValidationError:
        # Fail closed: a report that cannot be read is treated as a dead run.
        logger.exception(
            "Unreadable capability report %s; it holds indexing as failed to run.",
            row.id,
        )
        return IndexingHold(reason=IndexingHoldReason.CHECKS_FAILED_TO_RUN)
    failed = [
        HeldCheck(
            check_id=result.check_id,
            capability=result.capability,
            display_name=result.display_name,
            message=result.message,
            remediation=result.remediation,
            docs_link=result.docs_link,
        )
        for result in report.check_results
        if result.required
        and result.applicable
        and result.status == CapabilityCheckStatus.FAILED
    ]
    if not failed:
        return None
    return IndexingHold(
        reason=IndexingHoldReason.REQUIRED_CHECKS_FAILED, failed_checks=failed
    )


def get_first_indexing_hold(
    db_session: Session, cc_pair: ConnectorCredentialPair
) -> IndexingHold | None:
    """The hold on the pair's first index attempt, or None when its docfetching
    task can be sent. With CONNECTOR_CHECKS_ENABLED off, nothing is held."""
    if not CONNECTOR_CHECKS_ENABLED:
        return None
    source = cc_pair.connector.source
    if not has_named_capability_checks(source):
        return None
    if cc_pair_has_dispatched_index_attempts(db_session, cc_pair.id):
        return None
    row = get_capability_report_row(
        db_session, cc_pair.credential_id, cc_pair.connector_id
    )
    if row is None:
        return None
    return decide_indexing_hold(
        row,
        now=get_db_current_time(db_session),
        stale_after=capability_check_run_stale_after(source),
    )
