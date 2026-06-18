"""Approval read + decision endpoints.

Concurrent writes are arbitrated by the conditional UPDATE in
`action_approval.try_record_decision`. After a successful write the API
wakes the parked proxy via the `approval:wake:{id}` channel; a missed
wake just falls back to the proxy's wait timeout.
"""

from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import Any
from typing import Literal
from uuid import UUID

from fastapi import APIRouter
from fastapi import Depends
from pydantic import BaseModel
from pydantic import computed_field
from pydantic import ConfigDict
from sqlalchemy.orm import Session

from onyx.auth.permissions import require_permission
from onyx.cache.factory import get_cache_backend
from onyx.cache.interface import CACHE_TRANSIENT_ERRORS
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import ApprovalDecidedVia
from onyx.db.enums import ApprovalDecision
from onyx.db.enums import Permission
from onyx.db.models import User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.external_apps.matching.engine import actions_requiring_approval
from onyx.external_apps.matching.engine import MatchedAction
from onyx.external_apps.presentation.decode import decode_payload
from onyx.sandbox_proxy import approval_cache
from onyx.server.features.build.db import action_approval
from onyx.server.features.build.db.build_session import get_build_session
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()


router = APIRouter(prefix="/approvals")


class DecisionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # EXPIRED is server-only (set by the proxy on timeout).
    decision: Literal[ApprovalDecision.APPROVED, ApprovalDecision.REJECTED]


class ApprovalView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    approval_id: UUID
    session_id: UUID
    # Non-empty by construction; sorted strictest-policy-first.
    actions: list[MatchedAction]
    app_name: str
    payload: dict[str, Any]
    created_at: datetime
    decision: ApprovalDecision | None
    decided_at: datetime | None

    @computed_field
    @property
    def display_payload(self) -> dict[str, Any]:
        """`payload` decoded for the reviewer (e.g. Gmail base64url MIME →
        To/Subject/Body), or `payload` itself when nothing decodes it."""
        action_type = self.actions[0].action_type if self.actions else ""
        return decode_payload(action_type, self.payload)

    @computed_field
    @property
    def is_live(self) -> bool:
        if self.decision is not None:
            return False
        cutoff = datetime.now(timezone.utc) - timedelta(
            seconds=approval_cache.WAIT_TIMEOUT_S
        )
        return self.created_at >= cutoff


class ApprovalListResponse(BaseModel):
    items: list[ApprovalView]


def _send_wake_best_effort(approval_id: UUID, decision: ApprovalDecision) -> None:
    try:
        cache = get_cache_backend(tenant_id=get_current_tenant_id())
        approval_cache.send_wake(approval_id, decision, cache)
    except CACHE_TRANSIENT_ERRORS as e:
        logger.warning(
            "approval.wake_failed approval_id=%s error=%s",
            approval_id,
            str(e),
        )


def _existing_decision_response(
    view: ApprovalView, requested: ApprovalDecision, approval_id: UUID
) -> ApprovalView:
    """Same decision is idempotent; a different one is a CONFLICT."""
    if view.decision == requested:
        return view
    existing = view.decision.value if view.decision is not None else "unknown"
    logger.info(
        "approval.decision_conflict approval_id=%s "
        "existing_decision=%s requested_decision=%s",
        approval_id,
        existing,
        requested.value,
    )
    raise OnyxError(
        OnyxErrorCode.CONFLICT,
        f"decision already recorded ({existing})",
    )


@router.get("/sessions/{session_id}/live")
def list_live_approvals(
    session_id: UUID,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> ApprovalListResponse:
    """Pending approvals created within the proxy's wait window.

    Older undecided rows are treated as orphaned (proxy gone) and excluded.
    """
    if get_build_session(session_id, user.id, db_session) is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "session not found")

    cutoff = datetime.now(timezone.utc) - timedelta(
        seconds=approval_cache.WAIT_TIMEOUT_S
    )
    pending_rows = action_approval.list_session_pending_action_approvals(
        db_session, session_id, created_after=cutoff
    )
    return ApprovalListResponse(
        items=[ApprovalView.model_validate(row) for row in pending_rows]
    )


@router.post("/{approval_id}/decision")
def submit_decision(
    approval_id: UUID,
    body: DecisionBody,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> ApprovalView:
    """Record the caller's decision on a pending approval request."""
    current = action_approval.get_action_approval_for_user(
        db_session, approval_id, user.id
    )
    if current is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "approval request not found")

    if current.decision is not None:
        return _existing_decision_response(
            ApprovalView.model_validate(current), body.decision, approval_id
        )

    decided = action_approval.try_record_decision(
        db_session,
        approval_id=approval_id,
        decision=body.decision,
        decided_via=ApprovalDecidedVia.USER,
    )
    if decided is None:
        # Lost the race. Expire the cached row — SQLAlchemy's identity
        # map would otherwise hand back the pre-UPDATE `current`.
        db_session.expire(current)
        winner = action_approval.get_action_approval(db_session, approval_id)
        if winner is None:
            # FK cascade dropped the row between our two reads.
            raise OnyxError(OnyxErrorCode.NOT_FOUND, "approval request not found")
        if winner.decision is None:
            raise OnyxError(
                OnyxErrorCode.INTERNAL_ERROR,
                "approval row reverted to pending unexpectedly",
            )
        return _existing_decision_response(
            ApprovalView.model_validate(winner), body.decision, approval_id
        )

    db_session.commit()
    logger.info(
        "approval.decision_recorded approval_id=%s session_id=%s "
        "user_id=%s decision=%s",
        approval_id,
        current.session_id,
        user.id,
        body.decision.value,
    )

    _send_wake_best_effort(approval_id, body.decision)

    return ApprovalView.model_validate(decided)


@router.post("/{approval_id}/session-grant")
def submit_session_grant(
    approval_id: UUID,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> ApprovalView:
    """Approve this request and similar app/action requests for the session."""
    current = action_approval.get_action_approval_for_user(
        db_session, approval_id, user.id
    )
    if current is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "approval request not found")
    session_id = current.session_id
    external_app_id = current.external_app_id
    if external_app_id is None:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "approval request cannot be granted for a session",
        )
    if current.decision is not None:
        raise OnyxError(
            OnyxErrorCode.CONFLICT,
            "approval request already resolved",
        )
    cutoff = datetime.now(timezone.utc) - timedelta(
        seconds=approval_cache.WAIT_TIMEOUT_S
    )
    if current.created_at < cutoff:
        raise OnyxError(
            OnyxErrorCode.CONFLICT,
            "approval request is no longer live",
        )

    grant_action_types = actions_requiring_approval(current.actions)
    if not grant_action_types:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "approval request has no grantable actions",
        )

    approved_ids: list[UUID] = []
    decided_current = action_approval.try_record_decision(
        db_session,
        approval_id=approval_id,
        decision=ApprovalDecision.APPROVED,
        decided_via=ApprovalDecidedVia.SESSION_GRANT,
    )
    if decided_current is None:
        db_session.expire(current)
        winner = action_approval.get_action_approval(db_session, approval_id)
        if winner is None:
            raise OnyxError(OnyxErrorCode.NOT_FOUND, "approval request not found")
        if winner.decision is None:
            raise OnyxError(
                OnyxErrorCode.INTERNAL_ERROR,
                "approval row reverted to pending unexpectedly",
            )
        existing = winner.decision.value
        raise OnyxError(
            OnyxErrorCode.CONFLICT,
            f"approval request already resolved ({existing})",
        )
    approved_ids.append(approval_id)

    db_session.commit()
    _send_wake_best_effort(approval_id, ApprovalDecision.APPROVED)

    grant_source_rows = action_approval.list_session_grant_action_approvals(
        db_session,
        session_id=session_id,
        external_app_id=external_app_id,
    )
    granted_action_types: set[str] = set()
    for grant_source_row in grant_source_rows:
        granted_action_types.update(
            actions_requiring_approval(grant_source_row.actions)
        )

    try:
        cache = get_cache_backend(tenant_id=get_current_tenant_id())
        for grant_source_row in grant_source_rows:
            approval_cache.cache_session_grant_actions(
                session_id=session_id,
                external_app_id=external_app_id,
                action_types=actions_requiring_approval(grant_source_row.actions),
                source_approval_id=grant_source_row.approval_id,
                cache=cache,
            )
    except CACHE_TRANSIENT_ERRORS as e:
        logger.warning(
            "approval.session_grant_cache_failed approval_id=%s session_id=%s error=%s",
            approval_id,
            session_id,
            str(e),
        )

    pending_rows = action_approval.list_session_pending_action_approvals(
        db_session, session_id, created_after=cutoff
    )
    for row in pending_rows:
        if row.approval_id == approval_id:
            continue
        if row.external_app_id != external_app_id:
            continue
        row_action_types = set(actions_requiring_approval(row.actions))
        covered = bool(row_action_types) and row_action_types.issubset(
            granted_action_types
        )
        if not covered:
            continue
        decided = action_approval.try_record_decision(
            db_session,
            approval_id=row.approval_id,
            decision=ApprovalDecision.APPROVED,
            decided_via=ApprovalDecidedVia.SESSION_GRANT,
        )
        if decided is not None:
            approved_ids.append(row.approval_id)

    db_session.commit()

    for approved_id in approved_ids:
        if approved_id == approval_id:
            continue
        _send_wake_best_effort(approved_id, ApprovalDecision.APPROVED)

    logger.info(
        "approval.session_grant_recorded approval_id=%s session_id=%s "
        "user_id=%s external_app_id=%s action_types=%s approved_count=%s",
        approval_id,
        session_id,
        user.id,
        external_app_id,
        grant_action_types,
        len(approved_ids),
    )

    return ApprovalView.model_validate(decided_current)
