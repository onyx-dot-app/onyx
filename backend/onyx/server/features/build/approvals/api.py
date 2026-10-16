"""Approval read + decision endpoints.

Concurrent writes are arbitrated by the conditional UPDATE in
`action_approval.try_record_decision`. After a successful write the API
wakes the parked proxy via the `approval:wake:{id}` channel; a missed
wake just falls back to the proxy's wait timeout.
"""

from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import AliasPath, BaseModel, ConfigDict, Field, computed_field
from sqlalchemy.orm import Session

from onyx.auth.permissions import require_permission
from onyx.cache.factory import get_cache_backend
from onyx.cache.interface import CACHE_TRANSIENT_ERRORS, CacheBackend
from onyx.db import action_approval
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import ApprovalDecidedVia, ApprovalDecision, GatedAppKind, Permission
from onyx.db.models import ActionApproval, User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.external_apps.matching.engine import (
    WHOLE_DOMAIN_ACTION_TYPE,
    MatchedAction,
    actions_requiring_approval,
)
from onyx.external_apps.presentation.decode import decode_payload
from onyx.sandbox_proxy import approval_cache
from onyx.server.features.build.configs import SANDBOX_APPROVAL_WAIT_TIMEOUT_SECONDS
from onyx.server.features.build.db.build_session import get_build_session
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()


router = APIRouter(prefix="/approvals")


class ApprovalChoice(StrEnum):
    APPROVE_ONCE = "approve_once"
    APPROVE_SESSION = "approve_session"
    REJECT = "reject"


class DecisionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: ApprovalChoice


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
    target_kind: GatedAppKind | None = Field(
        default=None, validation_alias=AliasPath("gated_app", "kind"), exclude=True
    )

    @computed_field
    @property
    def can_approve_for_session(self) -> bool:
        if self.target_kind is None or not actions_requiring_approval(self.actions):
            return False
        return not (
            self.target_kind == GatedAppKind.EXTERNAL_APP
            and any(a.action_type == WHOLE_DOMAIN_ACTION_TYPE for a in self.actions)
        )

    @computed_field
    @property
    def display_payload(self) -> dict[str, Any]:
        """`payload` decoded for the reviewer (e.g. Gmail base64url MIME →
        To/Subject/Body), or `payload` itself when nothing decodes it."""
        action_type = self.actions[0].action_type if self.actions else ""
        return decode_payload(action_type, self.payload)

    @computed_field
    @property
    def expires_at(self) -> datetime:
        """Display cutoff for the existing proxy wait; no stored approval deadline."""
        return self.created_at + timedelta(
            seconds=SANDBOX_APPROVAL_WAIT_TIMEOUT_SECONDS
        )

    @computed_field
    @property
    def is_live(self) -> bool:
        if self.decision is not None:
            return False
        return self.expires_at >= datetime.now(timezone.utc)


class ApprovalStatusView(BaseModel):
    """Small polling response; full request payloads stay in the history read."""

    approval_id: UUID
    decision: ApprovalDecision | None
    is_live: bool


class ApprovalListResponse(BaseModel):
    items: list[ApprovalView]


def _row_target(row: ActionApproval) -> tuple[GatedAppKind, int] | None:
    """The gated target ``(kind, id)`` a row is attributed to, or ``None`` when
    its ``gated_app`` was cleared (parent app/server deleted — SET NULL)."""
    return row.gated_app.target_key if row.gated_app is not None else None


def _existing_decision_response(
    row: ActionApproval, requested: ApprovalDecision, *, for_session: bool
) -> ApprovalView:
    """A retry must match both the decision and its scope."""
    if row.decision == requested and (
        requested == ApprovalDecision.REJECTED
        or (row.decided_via == ApprovalDecidedVia.SESSION_GRANT) == for_session
    ):
        return ApprovalView.model_validate(row)
    existing = row.decision.value if row.decision is not None else "pending"
    raise OnyxError(
        OnyxErrorCode.CONFLICT,
        f"approval request cannot accept this decision ({existing})",
    )


@router.get("/sessions/{session_id}")
def list_session_approvals(
    session_id: UUID,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> ApprovalListResponse:
    if get_build_session(session_id, user.id, db_session) is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "session not found")
    return ApprovalListResponse(
        items=[
            ApprovalView.model_validate(row)
            for row in action_approval.list_session_action_approvals(
                db_session,
                session_id,
                created_after=datetime.now(timezone.utc)
                - timedelta(seconds=SANDBOX_APPROVAL_WAIT_TIMEOUT_SECONDS),
            )
        ]
    )


@router.get("/sessions/{session_id}/status")
def list_session_approval_status(
    session_id: UUID,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> list[ApprovalStatusView]:
    if get_build_session(session_id, user.id, db_session) is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "session not found")
    cutoff = datetime.now(timezone.utc) - timedelta(
        seconds=SANDBOX_APPROVAL_WAIT_TIMEOUT_SECONDS
    )
    return [
        ApprovalStatusView(
            approval_id=row.approval_id,
            decision=row.decision,
            is_live=row.decision is None and row.created_at >= cutoff,
        )
        for row in action_approval.list_session_action_approvals(
            db_session, session_id, created_after=cutoff, status_only=True
        )
    ]


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
        seconds=SANDBOX_APPROVAL_WAIT_TIMEOUT_SECONDS
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
    decision = (
        ApprovalDecision.REJECTED
        if body.decision == ApprovalChoice.REJECT
        else ApprovalDecision.APPROVED
    )
    for_session = body.decision == ApprovalChoice.APPROVE_SESSION
    current = action_approval.get_action_approval_for_user(
        db_session, approval_id, user.id, lock_session=for_session
    )
    if current is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "approval request not found")
    if current.decision is not None:
        return _existing_decision_response(current, decision, for_session=for_session)

    cutoff = datetime.now(timezone.utc) - timedelta(
        seconds=SANDBOX_APPROVAL_WAIT_TIMEOUT_SECONDS
    )
    if current.created_at < cutoff:
        raise OnyxError(OnyxErrorCode.CONFLICT, "approval request is no longer live")

    target = _row_target(current) if for_session else None
    if for_session and not ApprovalView.model_validate(current).can_approve_for_session:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT, "approval request has no grantable actions"
        )
    decided = action_approval.try_record_decision(
        db_session,
        approval_id=approval_id,
        decision=decision,
        decided_via=(
            ApprovalDecidedVia.SESSION_GRANT if for_session else ApprovalDecidedVia.USER
        ),
        created_after=cutoff,
    )
    if decided is None:
        db_session.expire(current)
        winner = action_approval.get_action_approval(db_session, approval_id)
        if winner is None:
            raise OnyxError(OnyxErrorCode.NOT_FOUND, "approval request not found")
        return _existing_decision_response(winner, decision, for_session=for_session)

    approved_ids = [approval_id]
    grant_source_rows: list[ActionApproval] = []
    if target is not None:
        grant_source_rows = action_approval.list_session_grant_action_approvals(
            db_session, session_id=current.session_id, gated_app_id=current.gated_app_id
        )
        granted_actions = {
            action
            for row in grant_source_rows
            for action in actions_requiring_approval(row.actions)
        }
        pending_rows = action_approval.list_session_pending_action_approvals(
            db_session, current.session_id, created_after=cutoff, load_target=True
        )
        for row in pending_rows:
            required = set(actions_requiring_approval(row.actions))
            if (
                _row_target(row) != target
                or not required
                or not required.issubset(granted_actions)
            ):
                continue
            approved = action_approval.try_record_decision(
                db_session,
                approval_id=row.approval_id,
                decision=ApprovalDecision.APPROVED,
                decided_via=ApprovalDecidedVia.SESSION_GRANT,
                created_after=cutoff,
            )
            if approved is not None:
                approved_ids.append(row.approval_id)

    # Commit all covered decisions before publishing grants or waking requests.
    db_session.commit()
    if target is not None:
        cache: CacheBackend | None = None
        try:
            cache = get_cache_backend(tenant_id=get_current_tenant_id())
        except CACHE_TRANSIENT_ERRORS:
            logger.warning(
                "approval.session_grant_cache_failed approval_id=%s", approval_id
            )
        approval_cache.hydrate_session_grants(
            session_id=current.session_id,
            kind=target[0],
            target_id=target[1],
            rows=grant_source_rows,
            cache=cache,
        )
    for decided_id in approved_ids:
        try:
            cache = get_cache_backend(tenant_id=get_current_tenant_id())
            approval_cache.send_wake(decided_id, decision, cache)
        except CACHE_TRANSIENT_ERRORS as error:
            logger.warning(
                "approval.wake_failed approval_id=%s error=%s", decided_id, error
            )
    logger.info(
        "approval.decision_recorded approval_id=%s session_id=%s decision=%s for_session=%s",
        approval_id,
        current.session_id,
        decision.value,
        for_session,
    )
    return ApprovalView.model_validate(decided)
