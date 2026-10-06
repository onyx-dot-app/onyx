"""Connector edits: plan, confirm, apply.

The admin proposes the full state of a cc-pair. ``/edit/plan`` computes and
stores the plan; the admin reviews it (``GET``), may run the slow checks
(``/edit/checks``) and stage file uploads (``/edit/files``), and then
``/edit/apply`` writes the state and the confirmed steps in one transaction.

Authorization matches creation: MANAGE_CONNECTORS (scoped allowed), Editor on
every pair of the connector, a visible and usable new credential, the access
rules, and the GATE 2 scope rule for an access change. A plan is private to
the user who computed it.
"""

from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from onyx.auth.permissions import require_permission
from onyx.auth.scoped_permissions import assert_within_scope
from onyx.background.celery.versioned_apps.client import app as client_app
from onyx.background.indexing.attempt_restart import revoke_restarted_attempt_tasks
from onyx.configs.constants import OnyxCeleryPriority, OnyxCeleryTask
from onyx.connectors.capability_checks.draft_runs import (
    DraftCheckRunSnapshot,
    DraftRerunMode,
)
from onyx.connectors.edit_plan.apply import (
    apply_connector_edit,
    load_plan_for_user,
)
from onyx.connectors.edit_plan.constants import EDIT_PLAN_TTL_SECONDS
from onyx.connectors.edit_plan.models import (
    CurrentPairState,
    EditPlan,
    EditPlanChoices,
    EditStep,
    ProposedPairState,
    StoredEditPlan,
)
from onyx.connectors.edit_plan.orchestration import (
    plan_connector_edit,
    with_latest_dry_run_results,
)
from onyx.connectors.edit_plan.state import fetch_current_pair_state
from onyx.db.connector_credential_pair import (
    CCPairAccessLevel,
    get_connector_credential_pair_from_id_for_user,
    verify_user_can_edit_connector,
)
from onyx.db.credentials import (
    credential_usable_for_source,
    fetch_credential_by_id_for_user,
)
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import AccessType, ConnectorManageRole, Permission
from onyx.db.models import Credential, User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.redis.redis_tenant_work_gating import maybe_mark_tenant_active
from onyx.server.documents.capability_check_runs import (
    CapabilityRunEnqueueError,
    start_cc_pair_draft_check_run,
)
from onyx.server.documents.file_connector_staging import stage_file_connector_upload
from onyx.server.documents.models import FileUploadResponse
from onyx.server.utils_vector_db import require_vector_db
from onyx.utils.audit import (
    AuditAction,
    AuditOutcome,
    actor_from_user,
    emit_audit_event,
)
from onyx.utils.logger import setup_logger
from onyx.utils.variable_functionality import fetch_ee_implementation_or_noop
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()

router = APIRouter(prefix="/manage", dependencies=[Depends(require_vector_db)])

# The indexing beat runs every 15 s, so a late kick has no value.
_CHECK_FOR_INDEXING_EXPIRES_SECONDS = 60


class ConnectorEditProposal(BaseModel):
    """The full proposed state of the pair. Source and input type cannot
    change, so they are not part of it."""

    model_config = ConfigDict(extra="forbid")

    connector_specific_config: dict[str, Any]
    access_type: AccessType
    data_access_group_ids: list[int] = []
    credential_id: int
    indexing_start: datetime | None = None
    name: str
    refresh_freq: int | None = None
    prune_freq: int | None = None


class ConnectorEditPlanResponse(BaseModel):
    plan_id: UUID
    cc_pair_id: int
    created_at: datetime
    expires_at: datetime
    proposed: ProposedPairState
    # Steps, notes, the choices to make, validation, dry-run results and the
    # indexed document count.
    plan: EditPlan
    validation_blocks_apply: bool
    # POST here to run the slow checks on the proposed state, then GET the
    # plan again for their results.
    dry_run_checks_path: str

    @classmethod
    def from_stored(cls, stored: StoredEditPlan) -> "ConnectorEditPlanResponse":
        return cls(
            plan_id=stored.plan_id,
            cc_pair_id=stored.cc_pair_id,
            created_at=stored.created_at,
            expires_at=stored.created_at + timedelta(seconds=EDIT_PLAN_TTL_SECONDS),
            proposed=stored.proposed,
            plan=stored.plan,
            validation_blocks_apply=stored.plan.validation_blocks_apply,
            dry_run_checks_path=(
                f"/manage/admin/cc-pair/{stored.cc_pair_id}/edit/checks"
            ),
        )


class ConnectorEditApplyRequest(EditPlanChoices):
    model_config = ConfigDict(extra="forbid")

    plan_id: UUID


class ConnectorEditApplyResponse(BaseModel):
    cc_pair_id: int
    plan_id: UUID
    # The steps that ran or are requested, in apply order.
    steps: list[EditStep]
    # The pair was INVALID and the validation of the new state passed.
    reactivated: bool


class ConnectorEditChecksRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    connector_specific_config: dict[str, Any]
    access_type: AccessType
    # None keeps the pair's credential.
    credential_id: int | None = None
    rerun: DraftRerunMode = DraftRerunMode.NONE


def _authorize_pair_edit(db_session: Session, user: User, cc_pair_id: int) -> None:
    """GATE 2 on the pair and its connector: the config and frequencies live
    on the connector, so the user must be an Editor of every pair on it, as
    for a credential association."""
    cc_pair = get_connector_credential_pair_from_id_for_user(
        cc_pair_id, db_session, user, CCPairAccessLevel.EDIT
    )
    if cc_pair is None or not verify_user_can_edit_connector(
        cc_pair.connector_id, db_session, user
    ):
        raise OnyxError(
            OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
            "Connection not found for current user's permissions",
        )


def _fetch_new_credential(
    db_session: Session, user: User, current: CurrentPairState, credential_id: int
) -> Credential:
    """GATE 2 on a credential the edit moves the pair to: the user must see it,
    and the pair's source must be able to use it."""
    credential = fetch_credential_by_id_for_user(credential_id, user, db_session)
    if credential is None:
        raise OnyxError(
            OnyxErrorCode.CREDENTIAL_NOT_FOUND,
            f"Credential {credential_id} does not exist or does not belong to user",
        )
    if not credential_usable_for_source(credential, current.source):
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"Credential {credential_id} cannot be used by a "
            f"{current.source.value} connector.",
        )
    return credential


def _authorize_proposed_state(
    db_session: Session,
    user: User,
    current: CurrentPairState,
    proposed: ProposedPairState,
) -> None:
    """The creation gates that depend on the proposed state. The access rules
    themselves (``validate_pairing_access``) run in planning and in apply."""
    if proposed.credential_id != current.credential_id:
        _fetch_new_credential(db_session, user, current, proposed.credential_id)

    if (
        proposed.access_type == current.access_type
        and proposed.data_access_group_ids == current.data_access_group_ids
    ):
        return
    manage_roles: dict[int, ConnectorManageRole] = fetch_ee_implementation_or_noop(
        "onyx.db.connector_manage_access",
        "fetch_manage_roles_for_cc_pair",
        noop_return_value={},
    )(db_session, current.cc_pair_id)
    manage_group_ids = list(manage_roles)
    # As at creation: a groupless perm-synced pair mirrors the source's ACLs,
    # so there is no reach for a group to bound.
    if proposed.access_type.is_perm_synced() and not manage_group_ids:
        return
    # Both states must be non-public, so a scoped manager can neither publish
    # a pair nor take over a public one.
    assert_within_scope(
        user,
        db_session,
        permission=Permission.MANAGE_CONNECTORS,
        current_group_ids=manage_group_ids,
        requested_group_ids=[],
        is_non_public=(
            current.access_type != AccessType.PUBLIC
            and proposed.access_type != AccessType.PUBLIC
        ),
    )


def _proposed_state(
    current: CurrentPairState, proposal: ConnectorEditProposal
) -> ProposedPairState:
    return ProposedPairState(
        source=current.source,
        input_type=current.input_type,
        connector_specific_config=proposal.connector_specific_config,
        access_type=proposal.access_type,
        data_access_group_ids=proposal.data_access_group_ids,
        credential_id=proposal.credential_id,
        indexing_start=proposal.indexing_start,
        name=proposal.name,
        refresh_freq=proposal.refresh_freq,
        prune_freq=proposal.prune_freq,
    )


@router.post("/admin/cc-pair/{cc_pair_id}/edit/plan")
def plan_cc_pair_edit(
    cc_pair_id: int,
    proposal: ConnectorEditProposal,
    user: User = Depends(
        require_permission(Permission.MANAGE_CONNECTORS, allow_scope=True)
    ),
    db_session: Session = Depends(get_session),
) -> ConnectorEditPlanResponse:
    """Computes and stores the plan for moving the pair to the proposed state.
    Writes nothing to the pair. Runs the blocking validation (about 3 s) when
    the config, credential or access type changes."""
    _authorize_pair_edit(db_session, user, cc_pair_id)
    current = fetch_current_pair_state(db_session, cc_pair_id)
    proposed = _proposed_state(current, proposal)
    _authorize_proposed_state(db_session, user, current, proposed)
    stored = plan_connector_edit(
        db_session, cc_pair_id=cc_pair_id, proposed=proposed, user=user
    )
    return ConnectorEditPlanResponse.from_stored(stored)


@router.get("/admin/cc-pair/{cc_pair_id}/edit/plan/{plan_id}")
def get_cc_pair_edit_plan(
    cc_pair_id: int,
    plan_id: UUID,
    user: User = Depends(
        require_permission(Permission.MANAGE_CONNECTORS, allow_scope=True)
    ),
    db_session: Session = Depends(get_session),
) -> ConnectorEditPlanResponse:
    """A stored plan of the caller's, with the latest results of the pair's
    dry runs for its proposed state."""
    _authorize_pair_edit(db_session, user, cc_pair_id)
    stored = load_plan_for_user(plan_id, cc_pair_id, user)
    return ConnectorEditPlanResponse.from_stored(
        with_latest_dry_run_results(db_session, stored)
    )


@router.post("/admin/cc-pair/{cc_pair_id}/edit/apply")
def apply_cc_pair_edit(
    cc_pair_id: int,
    request: ConnectorEditApplyRequest,
    user: User = Depends(
        require_permission(Permission.MANAGE_CONNECTORS, allow_scope=True)
    ),
    db_session: Session = Depends(get_session),
) -> ConnectorEditApplyResponse:
    """Applies a plan the caller computed, with their choices. The plan is
    single use. A pair that changed after planning gives 409 EDIT_PLAN_STALE;
    a failed validation of the proposed state writes nothing."""
    tenant_id = get_current_tenant_id()
    _authorize_pair_edit(db_session, user, cc_pair_id)
    stored = load_plan_for_user(request.plan_id, cc_pair_id, user)
    current = fetch_current_pair_state(db_session, cc_pair_id)
    _authorize_proposed_state(db_session, user, current, stored.proposed)

    applied = apply_connector_edit(
        db_session,
        stored=stored,
        choices=EditPlanChoices(
            reconciliation=request.reconciliation,
            credential_path=request.credential_path,
            added_steps=request.added_steps,
            dropped_steps=request.dropped_steps,
        ),
        user=user,
    )

    revoke_restarted_attempt_tasks(client_app, applied.restarted_task_ids)
    # Lets the work-gated beats see the pair at once (indexing, and the perm
    # sync of a pair that entered sync).
    maybe_mark_tenant_active(tenant_id, caller="connector_edit")
    client_app.send_task(
        OnyxCeleryTask.CHECK_FOR_INDEXING,
        kwargs={"tenant_id": tenant_id},
        priority=OnyxCeleryPriority.HIGH,
        expires=_CHECK_FOR_INDEXING_EXPIRES_SECONDS,
    )
    emit_audit_event(
        AuditAction.CC_PAIR_UPDATE,
        AuditOutcome.SUCCESS,
        actor=actor_from_user(user),
        resource_type="cc_pair",
        resource_id=cc_pair_id,
        extra=applied.audit.model_dump(mode="json"),
    )
    return ConnectorEditApplyResponse(
        cc_pair_id=cc_pair_id,
        plan_id=stored.plan_id,
        steps=applied.steps,
        reactivated=applied.reactivated,
    )


@router.post("/admin/cc-pair/{cc_pair_id}/edit/checks")
def start_cc_pair_edit_checks(
    cc_pair_id: int,
    request: ConnectorEditChecksRequest,
    user: User = Depends(
        require_permission(Permission.MANAGE_CONNECTORS, allow_scope=True)
    ),
    db_session: Session = Depends(get_session),
) -> DraftCheckRunSnapshot:
    """Starts a dry run of the capability checks on a proposed state. Poll it
    with GET /manage/admin/connector-checks/runs/{run_id}. Writes no report."""
    _authorize_pair_edit(db_session, user, cc_pair_id)
    current = fetch_current_pair_state(db_session, cc_pair_id)
    credential = (
        _fetch_new_credential(db_session, user, current, request.credential_id)
        if request.credential_id is not None
        and request.credential_id != current.credential_id
        else None
    )
    try:
        return start_cc_pair_draft_check_run(
            db_session,
            user_id=user.id,
            cc_pair_id=cc_pair_id,
            proposed_credential=credential,
            access_type=request.access_type,
            connector_specific_config=request.connector_specific_config,
            rerun=request.rerun,
        )
    except CapabilityRunEnqueueError as e:
        raise OnyxError(
            OnyxErrorCode.SERVICE_UNAVAILABLE,
            "Could not enqueue the capability check run; try again shortly.",
        ) from e


@router.post("/admin/cc-pair/{cc_pair_id}/edit/files")
def stage_cc_pair_edit_files(
    cc_pair_id: int,
    files: list[UploadFile] = File(...),
    draft_zip_metadata_file_id: str | None = Form(None),
    user: User = Depends(
        require_permission(Permission.MANAGE_CONNECTORS, allow_scope=True)
    ),
    db_session: Session = Depends(get_session),
) -> FileUploadResponse:
    """Stages uploads for a file connector edit. Only an applied plan that
    names them indexes them. Pass the draft's metadata file id so a second
    zip in the same edit merges into it; the response gives the staged file
    ids and the merged metadata file id."""
    _authorize_pair_edit(db_session, user, cc_pair_id)
    return stage_file_connector_upload(
        db_session, cc_pair_id, files, draft_zip_metadata_file_id
    )
