"""Read-only API over stored credential capability reports.

The blocking-validation recorder writes these rows today; the granular
check-runner task will write them too once it exists. Reports are advisory:
nothing here gates connector creation or indexing.
"""

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from onyx.auth.permissions import has_global_permission, require_permission
from onyx.configs.constants import DocumentSource
from onyx.connectors.capability_checks.models import CredentialCapabilityReport
from onyx.db.connector_credential_pair import (
    get_connector_credential_pair_for_user,
    get_connector_credential_pairs_for_user,
)
from onyx.db.credential_capability import (
    get_capability_report_row,
    get_capability_report_rows_for_source,
)
from onyx.db.credentials import (
    fetch_credential_by_id_for_user,
    fetch_credentials_by_source_for_user,
)
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import CapabilityCheckTrigger, CapabilityReportRunStatus, Permission
from onyx.db.models import CredentialCapabilityReportRow, User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError

router = APIRouter(prefix="/manage")


class CapabilityReportSnapshot(BaseModel):
    """One stored report row; ``report`` is the last completed run's content."""

    credential_id: int
    connector_id: int | None
    source: DocumentSource
    trigger: CapabilityCheckTrigger
    run_status: CapabilityReportRunStatus
    run_started_at: datetime | None
    connector_config_hash: str | None
    report: CredentialCapabilityReport | None
    time_updated: datetime

    @classmethod
    def from_row(cls, row: CredentialCapabilityReportRow) -> "CapabilityReportSnapshot":
        return cls(
            credential_id=row.credential_id,
            connector_id=row.connector_id,
            source=row.source,
            trigger=row.trigger,
            run_status=row.run_status,
            run_started_at=row.run_started_at,
            connector_config_hash=row.connector_config_hash,
            report=(
                CredentialCapabilityReport.model_validate(row.report)
                if row.report is not None
                else None
            ),
            time_updated=row.time_updated,
        )


def _connector_pairing_visible(
    db_session: Session, connector_id: int, credential_id: int, user: User
) -> bool:
    """GATE 2 for the connector scope: pairing outcomes are cc-pair data.

    Global managers see every pairing, including failed-creation orphans whose
    cc-pair was never created (a support surface). Scoped managers see only
    pairings inside groups they belong to, per the cc-pair read filter.
    """
    if has_global_permission(user, Permission.MANAGE_CONNECTORS):
        return True
    return (
        get_connector_credential_pair_for_user(
            db_session,
            connector_id=connector_id,
            credential_id=credential_id,
            user=user,
            get_editable=False,
        )
        is not None
    )


@router.get("/admin/credential/{credential_id}/capability-report")
def get_capability_report(
    credential_id: int,
    connector_id: int | None = None,
    user: User = Depends(
        require_permission(Permission.MANAGE_CONNECTORS, allow_scope=True)
    ),
    db_session: Session = Depends(get_session),
) -> CapabilityReportSnapshot | None:
    """Returns the stored report row for one scope, or None before any run.

    ``connector_id`` selects the connector-scoped row; without it the
    config-less credential-scoped row is returned. A connector-scoped row the
    caller may not see reads as absent.
    """
    # GATE 2 for ``allow_scope``: the user-filtered fetch is the visibility
    # check, and an unknown credential is indistinguishable from an
    # inaccessible one.
    credential = fetch_credential_by_id_for_user(credential_id, user, db_session)
    if credential is None:
        raise OnyxError(
            OnyxErrorCode.CREDENTIAL_NOT_FOUND,
            f"Credential {credential_id} does not exist or is not accessible.",
        )
    row = get_capability_report_row(db_session, credential_id, connector_id)
    if row is None:
        return None
    if connector_id is not None and not _connector_pairing_visible(
        db_session, connector_id, credential_id, user
    ):
        # Same shape as no row at all: pairing existence must not leak.
        return None
    return CapabilityReportSnapshot.from_row(row)


@router.get("/admin/credential/capability-reports")
def list_capability_reports_for_source(
    source: DocumentSource,
    user: User = Depends(
        require_permission(Permission.MANAGE_CONNECTORS, allow_scope=True)
    ),
    db_session: Session = Depends(get_session),
) -> list[CapabilityReportSnapshot]:
    """Returns the report rows for a source's visible credentials, newest first."""
    # GATE 2 for ``allow_scope``: only rows of credentials the caller can see,
    # via the same user-filtered fetch the credential listings use.
    visible_credential_ids = {
        credential.id
        for credential in fetch_credentials_by_source_for_user(
            db_session=db_session,
            user=user,
            document_source=source,
        )
    }
    rows = [
        row
        for row in get_capability_report_rows_for_source(db_session, source)
        if row.credential_id in visible_credential_ids
    ]
    # GATE 2 for the connector scope, mirroring the single-report endpoint:
    # scoped managers only see connector rows for pairings in their groups.
    if not has_global_permission(user, Permission.MANAGE_CONNECTORS):
        visible_pairings = {
            (pair.connector_id, pair.credential_id)
            for pair in get_connector_credential_pairs_for_user(
                db_session=db_session,
                user=user,
                get_editable=False,
                source=source,
                # Every pairing counts as visibility truth, whatever its mode.
                processing_mode=None,
            )
        }
        rows = [
            row
            for row in rows
            if row.connector_id is None
            or (row.connector_id, row.credential_id) in visible_pairings
        ]
    return [CapabilityReportSnapshot.from_row(row) for row in rows]
