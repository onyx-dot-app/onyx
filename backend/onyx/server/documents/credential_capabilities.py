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
    fetch_credential_by_id,
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
    """GATE 2 for the connector scope: pairing outcomes are management data.

    Global managers see every pairing, including failed-creation orphans whose
    cc-pair was never created (a support surface). Scoped managers see only
    pairings within their managed scope: the read filter
    (``get_editable=False``) would admit every public and sync pair, and is
    skipped outright for READ_CONNECTORS holders, so it must not authorize
    report internals.
    """
    return has_global_permission(user, Permission.MANAGE_CONNECTORS) or (
        get_connector_credential_pair_for_user(
            db_session,
            connector_id=connector_id,
            credential_id=credential_id,
            user=user,
            get_editable=True,
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
    # GATE 2 for ``allow_scope``: credential visibility authorizes the
    # credential scope; pairing visibility authorizes the connector scope on its
    # own, so a pairing manager reads its report even when the credential is
    # outside their credential visibility (admin-created for a scoped manager,
    # another user's private credential for a global one). An unknown credential
    # is indistinguishable from an inaccessible one.
    pairing_visible = connector_id is not None and _connector_pairing_visible(
        db_session, connector_id, credential_id, user
    )
    credential_visible = (
        fetch_credential_by_id_for_user(credential_id, user, db_session) is not None
    )
    if not credential_visible and (
        # The global-manager pairing shortcut checks nothing, so the unfiltered
        # fetch keeps an unknown credential a 404 for them too.
        not pairing_visible or fetch_credential_by_id(credential_id, db_session) is None
    ):
        raise OnyxError(
            OnyxErrorCode.CREDENTIAL_NOT_FOUND,
            f"Credential {credential_id} does not exist or is not accessible.",
        )
    row = get_capability_report_row(db_session, credential_id, connector_id)
    if row is None:
        return None
    if connector_id is not None and not pairing_visible:
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
    """Returns the source's report rows visible to the caller, newest first."""
    # GATE 2 for ``allow_scope``, mirroring the single-report endpoint:
    # credential-scoped rows follow credential visibility (the same
    # user-filtered fetch the credential listings use); connector-scoped rows
    # are pairing outcomes and follow pairing visibility alone, so a pairing
    # manager sees them even when the credential is outside their credential
    # visibility.
    visible_credential_ids = {
        credential.id
        for credential in fetch_credentials_by_source_for_user(
            db_session=db_session,
            user=user,
            document_source=source,
        )
    }
    # None: every pairing is visible (global managers, orphan rows included).
    visible_pairings: set[tuple[int, int]] | None = None
    if not has_global_permission(user, Permission.MANAGE_CONNECTORS):
        visible_pairings = {
            (pair.connector_id, pair.credential_id)
            for pair in get_connector_credential_pairs_for_user(
                db_session=db_session,
                user=user,
                get_editable=True,
                source=source,
                # Every pairing counts as visibility truth, whatever its mode.
                processing_mode=None,
            )
        }

    def is_visible(row: CredentialCapabilityReportRow) -> bool:
        if row.connector_id is None:
            return row.credential_id in visible_credential_ids
        return (
            visible_pairings is None
            or (row.connector_id, row.credential_id) in visible_pairings
        )

    return [
        CapabilityReportSnapshot.from_row(row)
        for row in get_capability_report_rows_for_source(db_session, source)
        if is_visible(row)
    ]
