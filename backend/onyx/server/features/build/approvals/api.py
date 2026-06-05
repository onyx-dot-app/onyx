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
from onyx.external_apps.matching.engine import ActionMatch
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
    actions: list[ActionMatch]
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


@router.get("/sessions/{session_id}")
def list_session_approvals(
    session_id: UUID,
    decision: ApprovalDecision | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> ApprovalListResponse:
    """Audit query for a session. Non-owners get NOT_FOUND (no existence leak)."""
    if get_build_session(session_id, user.id, db_session) is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "session not found")

    rows = action_approval.list_session_action_approvals(
        db_session,
        session_id,
        decision=decision,
        since=since,
        until=until,
    )
    return ApprovalListResponse(
        items=[ApprovalView.model_validate(row) for row in rows]
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

    try:
        cache = get_cache_backend(tenant_id=get_current_tenant_id())
        approval_cache.send_wake(approval_id, body.decision, cache)
    except CACHE_TRANSIENT_ERRORS as e:
        logger.warning(
            "approval.wake_failed approval_id=%s error=%s",
            approval_id,
            str(e),
        )

    return ApprovalView.model_validate(decided)
