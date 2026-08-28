"""API over stored credential capability reports.

The blocking-validation recorder and the granular check-runner task write the
rows; these endpoints read them and trigger runs. Reports are advisory: nothing
here gates connector creation or indexing, and check failures are report
content, never an HTTP error.
"""

from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from onyx.auth.permissions import has_global_permission, require_permission
from onyx.background.celery.versioned_apps.client import app as client_app
from onyx.configs.constants import (
    DocumentSource,
    OnyxCeleryPriority,
    OnyxCeleryQueues,
    OnyxCeleryTask,
)
from onyx.connectors.capability_checks.models import CredentialCapabilityReport
from onyx.connectors.capability_checks.runner import (
    CAPABILITY_CHECK_RUN_STALENESS_SECONDS,
)
from onyx.db.connector import fetch_connector_by_id
from onyx.db.connector_credential_pair import (
    get_connector_credential_pair_for_user,
    get_connector_credential_pairs_for_user,
)
from onyx.db.credential_capability import (
    get_capability_report_row,
    get_capability_report_rows_for_source,
    mark_capability_report_running,
    mark_capability_run_failed,
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
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()

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


class CapabilityCheckRunRequest(BaseModel):
    """Body of the trigger endpoint: which scope to run against.

    Both fields absent is the config-less credential-scoped run.
    ``connector_specific_config`` overrides the connector's stored config (a
    not-yet-saved edit) and is only meaningful with ``connector_id``.
    """

    # Both fields are optional, so a typoed field name would otherwise silently
    # select the wrong scope.
    model_config = ConfigDict(extra="forbid")

    connector_id: int | None = None
    connector_specific_config: dict[str, Any] | None = None


@router.post("/admin/credential/{credential_id}/capability-check")
def trigger_capability_check(
    credential_id: int,
    request: CapabilityCheckRunRequest,
    user: User = Depends(
        require_permission(Permission.MANAGE_CONNECTORS, allow_scope=True)
    ),
    db_session: Session = Depends(get_session),
) -> CapabilityReportSnapshot:
    """Marks the scope RUNNING, enqueues the check run, and returns the row.

    Accepted-style: the run happens on a worker and the caller polls the GET;
    the previous report stays readable meanwhile. A run already RUNNING within
    the staleness bound makes this a no-op returning the standing row. A
    connector-scoped trigger requires the pairing to be visible to the caller.
    """
    # GATE 2 for ``allow_scope``, mirroring the report reads: credential
    # visibility authorizes the credential scope; pairing visibility authorizes
    # the connector scope on its own, so a pairing manager triggers its run even
    # when the credential is outside their credential visibility. An unknown
    # credential is indistinguishable from an inaccessible one.
    pairing_visible = request.connector_id is not None and _connector_pairing_visible(
        db_session, request.connector_id, credential_id, user
    )
    credential = fetch_credential_by_id_for_user(credential_id, user, db_session)
    if credential is None and pairing_visible:
        # The run needs the credential row itself; the unfiltered fetch also
        # keeps an unknown credential a 404 for global managers, whose pairing
        # shortcut checks nothing.
        credential = fetch_credential_by_id(credential_id, db_session)
    if credential is None:
        raise OnyxError(
            OnyxErrorCode.CREDENTIAL_NOT_FOUND,
            f"Credential {credential_id} does not exist or is not accessible.",
        )
    if request.connector_specific_config is not None and request.connector_id is None:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "connector_specific_config requires connector_id: the "
            "credential-scoped run is config-less by definition.",
        )
    if request.connector_id is not None:
        connector = fetch_connector_by_id(request.connector_id, db_session)
        # One shape for missing and inaccessible, so neither connector existence
        # nor pairing membership leaks. The source check stays behind it.
        if connector is None or not pairing_visible:
            raise OnyxError(
                OnyxErrorCode.CONNECTOR_NOT_FOUND,
                f"Connector {request.connector_id} does not exist or is not "
                "accessible.",
            )
        if connector.source != credential.source:
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                f"Connector {request.connector_id} is a "
                f"{connector.source.value} connector; credential "
                f"{credential_id} is for {credential.source.value}.",
            )
    row = mark_capability_report_running(
        db_session,
        credential_id=credential_id,
        connector_id=request.connector_id,
        source=credential.source,
        trigger=CapabilityCheckTrigger.MANUAL,
        active_within=timedelta(seconds=CAPABILITY_CHECK_RUN_STALENESS_SECONDS),
    )
    if row is None:
        # An unexpired run is in flight; return its row without re-enqueueing.
        standing = get_capability_report_row(
            db_session, credential_id, request.connector_id
        )
        if standing is None:
            # The blocking row vanished between the two statements: the
            # credential (or the paired connector) was deleted concurrently and
            # its report rows cascaded away.
            raise OnyxError(
                OnyxErrorCode.CREDENTIAL_NOT_FOUND,
                f"Credential {credential_id} or its paired connector was "
                "deleted while the request was in flight.",
            )
        return CapabilityReportSnapshot.from_row(standing)
    snapshot = CapabilityReportSnapshot.from_row(row)
    # Commit before enqueueing so the worker can only observe the RUNNING mark.
    db_session.commit()
    try:
        client_app.send_task(
            OnyxCeleryTask.RUN_CAPABILITY_CHECKS,
            kwargs=dict(
                credential_id=credential_id,
                connector_id=request.connector_id,
                connector_specific_config=request.connector_specific_config,
                tenant_id=get_current_tenant_id(),
            ),
            queue=OnyxCeleryQueues.CAPABILITY_CHECKS,
            priority=OnyxCeleryPriority.HIGH,
            # The queued run and its RUNNING mark go stale together, so an
            # expired task never strands an unmarkable scope.
            expires=CAPABILITY_CHECK_RUN_STALENESS_SECONDS,
        )
    except Exception:
        # The 503 handler logs no traceback, so record the cause here (broker
        # down and a bad task payload must stay distinguishable in the logs).
        logger.exception(
            "Capability check enqueue failed for credential %s, connector %s.",
            credential_id,
            request.connector_id,
        )
        # No run was enqueued: FAILED_TO_RUN is the truth pollers should read,
        # and it does not block an immediate re-trigger.
        mark_capability_run_failed(
            db_session,
            credential_id=credential_id,
            connector_id=request.connector_id,
        )
        db_session.commit()
        raise OnyxError(
            OnyxErrorCode.SERVICE_UNAVAILABLE,
            "Could not enqueue the capability check run; try again shortly.",
        )
    return snapshot


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
