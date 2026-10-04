"""API over stored credential capability reports.

The blocking-validation recorder and the granular check-runner task write the
rows; these endpoints read them and trigger runs. Reports are advisory: nothing
here gates connector creation or indexing, and check failures are report
content, never an HTTP error.
"""

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from onyx.auth.permissions import has_global_permission, require_permission
from onyx.configs.constants import (
    DocumentSource,
)
from onyx.connectors.capability_checks.draft_runs import (
    DraftCheckRunSnapshot,
    DraftRerunMode,
    read_draft_run_for_user,
)
from onyx.connectors.capability_checks.models import CredentialCapabilityReport
from onyx.connectors.credential_families import is_credential_usable_for_source
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.factory import (
    CredentialBindingFieldError,
    credential_binding_field_errors,
    validate_connector_config,
    validate_credential_binding,
)
from onyx.connectors.registry import CONNECTOR_CLASS_MAP
from onyx.db.connector import fetch_connector_by_id
from onyx.db.connector_credential_pair import (
    CCPairAccessLevel,
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
from onyx.db.enums import (
    AccessType,
    CapabilityCheckTrigger,
    CapabilityReportRunStatus,
    Permission,
)
from onyx.db.models import Credential, CredentialCapabilityReportRow, User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.documents.capability_check_runs import (
    CapabilityRunEnqueueError,
    start_capability_check_run,
    start_draft_capability_check_run,
)
from onyx.server.utils_vector_db import require_vector_db
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Lite (no vector DB) has no connectors, so there is nothing to probe or report,
# and the celery machinery the trigger relies on is absent there.
router = APIRouter(prefix="/manage", dependencies=[Depends(require_vector_db)])


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
    pairings they may operate: the read filter
    (``CCPairAccessLevel.READ``) would admit every public and sync pair, and is
    skipped outright for READ_CONNECTORS holders, so it must not authorize
    report internals.
    """
    return has_global_permission(user, Permission.MANAGE_CONNECTORS) or (
        get_connector_credential_pair_for_user(
            db_session,
            connector_id=connector_id,
            credential_id=credential_id,
            user=user,
            access_level=CCPairAccessLevel.OPERATE,
        )
        is not None
    )


def _validate_credential_usable_for_source(
    credential: Credential, source: DocumentSource
) -> None:
    if not is_credential_usable_for_source(
        credential.source,
        (
            credential.credential_json.get_value(apply_mask=False)
            if credential.credential_json
            else {}
        ),
        source,
    ):
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"Credential {credential.id} cannot be used by a {source.value} connector.",
        )


def _fetch_credential_usable_for_source(
    credential_id: int, source: DocumentSource, user: User, db_session: Session
) -> Credential:
    """The credential, for an unsaved form of ``source``. GATE 2 for
    ``allow_scope``: the caller must see the credential. An unknown credential
    is indistinguishable from an inaccessible one."""
    credential = fetch_credential_by_id_for_user(credential_id, user, db_session)
    if credential is None:
        raise OnyxError(
            OnyxErrorCode.CREDENTIAL_NOT_FOUND,
            f"Credential {credential_id} does not exist or is not accessible.",
        )
    _validate_credential_usable_for_source(credential, source)
    return credential


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
    # A connector-scoped run checks the connector's source, which a family
    # credential may not share.
    run_source = credential.source
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
        _validate_credential_usable_for_source(credential, connector.source)
        run_source = connector.source
        if request.connector_specific_config is not None:
            try:
                validate_connector_config(
                    connector.source, request.connector_specific_config
                )
            except ValueError as e:
                raise OnyxError(OnyxErrorCode.INVALID_INPUT, str(e)) from e
    try:
        row = start_capability_check_run(
            db_session,
            credential_id=credential_id,
            connector_id=request.connector_id,
            source=run_source,
            trigger=CapabilityCheckTrigger.MANUAL,
            connector_specific_config=request.connector_specific_config,
        )
    except CapabilityRunEnqueueError as e:
        # No run was enqueued: FAILED_TO_RUN is the truth pollers read, and it
        # does not block an immediate re-trigger.
        raise OnyxError(
            OnyxErrorCode.SERVICE_UNAVAILABLE,
            "Could not enqueue the capability check run; try again shortly.",
        ) from e
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
    return CapabilityReportSnapshot.from_row(row)


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
                access_level=CCPairAccessLevel.OPERATE,
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


class CredentialBindingCheckRequest(BaseModel):
    """Body of the binding-check endpoint. Only the credential-bound fields of
    ``connector_specific_config`` are read; other keys are ignored."""

    model_config = ConfigDict(extra="forbid")

    source: DocumentSource
    connector_specific_config: dict[str, Any]


class CredentialBindingRejectionCode(str, Enum):
    BINDING_REJECTED = "binding_rejected"


class CredentialBindingRejection(BaseModel):
    code: CredentialBindingRejectionCode
    # English text from the source's binding rule, e.g. which site the
    # credential is for. Clients show their own message for ``code`` and may
    # add this as detail.
    detail: str


class CredentialBindingCheckResponse(BaseModel):
    """The bound fields are valid with the credential when both fields are
    empty. Clients map ``kind`` and ``code`` to their own messages; the
    English ``detail`` texts are for what no client message covers."""

    # Bound field name to its error.
    field_errors: dict[str, CredentialBindingFieldError]
    # Set when the credential cannot be used with valid bound fields.
    rejection: CredentialBindingRejection | None


@router.post("/admin/credential/{credential_id}/binding-check")
def check_credential_binding(
    credential_id: int,
    request: CredentialBindingCheckRequest,
    user: User = Depends(
        require_permission(Permission.MANAGE_CONNECTORS, allow_scope=True)
    ),
    db_session: Session = Depends(get_session),
) -> CredentialBindingCheckResponse:
    """Checks the bound fields of an unsaved connector form against the
    credential, as pairing does. Does no I/O to the source. A rejected binding
    is response content, not an HTTP error."""
    if request.source not in CONNECTOR_CLASS_MAP:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"{request.source.value} has no connector configuration.",
        )
    credential = _fetch_credential_usable_for_source(
        credential_id, request.source, user, db_session
    )
    field_errors = credential_binding_field_errors(
        request.source, request.connector_specific_config
    )
    if field_errors:
        return CredentialBindingCheckResponse(field_errors=field_errors, rejection=None)
    try:
        validate_credential_binding(
            request.source, request.connector_specific_config, credential
        )
    except ConnectorValidationError as e:
        return CredentialBindingCheckResponse(
            field_errors={},
            rejection=CredentialBindingRejection(
                code=CredentialBindingRejectionCode.BINDING_REJECTED, detail=str(e)
            ),
        )
    return CredentialBindingCheckResponse(field_errors={}, rejection=None)


class DraftCheckRunRequest(BaseModel):
    """Body of the draft run endpoint: an unsaved connector form."""

    model_config = ConfigDict(extra="forbid")

    source: DocumentSource
    credential_id: int
    access_type: AccessType | None = None
    # Client-chosen id of one form session. A new run for the same key
    # supersedes the earlier one.
    draft_key: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    form_state: dict[str, Any]
    # Cached results to ignore. The client sends FAILED when the admin asks to
    # create, so a fix made at the source is seen, and ALL to re-run every check.
    rerun: DraftRerunMode = DraftRerunMode.NONE


@router.post("/admin/connector-checks/runs")
def start_draft_check_run(
    request: DraftCheckRunRequest,
    user: User = Depends(
        require_permission(Permission.MANAGE_CONNECTORS, allow_scope=True)
    ),
    db_session: Session = Depends(get_session),
) -> DraftCheckRunSnapshot:
    """Starts the capability checks for an unsaved connector form.

    Checks that cannot run yet resolve at once (waiting, not applicable), and
    fresh cached results fill others; one task runs the rest. The caller polls
    the GET with the returned ``run_id``. Never writes a stored report.
    """
    mapping = CONNECTOR_CLASS_MAP.get(request.source)
    if mapping is None:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"{request.source.value} has no connector configuration.",
        )
    credential = _fetch_credential_usable_for_source(
        request.credential_id, request.source, user, db_session
    )
    try:
        return start_draft_capability_check_run(
            user_id=user.id,
            credential=credential,
            source=request.source,
            config_class=mapping.config_class,
            access_type=request.access_type,
            draft_key=request.draft_key,
            form_values=request.form_state,
            rerun=request.rerun,
        )
    except CapabilityRunEnqueueError as e:
        raise OnyxError(
            OnyxErrorCode.SERVICE_UNAVAILABLE,
            "Could not enqueue the capability check run; try again shortly.",
        ) from e


@router.get("/admin/connector-checks/runs/{run_id}")
def get_draft_check_run(
    run_id: UUID,
    user: User = Depends(
        require_permission(Permission.MANAGE_CONNECTORS, allow_scope=True)
    ),
    db_session: Session = Depends(get_session),
) -> DraftCheckRunSnapshot:
    """Returns a draft run's per-check progress. Only the user who started the
    run may read it, and only while they can still see its credential."""
    snapshot = read_draft_run_for_user(run_id, user.id)
    # GATE 2 again: the check messages come from the credential.
    if (
        snapshot is None
        or fetch_credential_by_id_for_user(snapshot.credential_id, user, db_session)
        is None
    ):
        raise OnyxError(
            OnyxErrorCode.NOT_FOUND,
            f"Capability check run {run_id} does not exist or has expired.",
        )
    return snapshot
