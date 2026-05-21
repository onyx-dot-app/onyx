"""User-facing approval decision + audit API.

Mounted under the existing ``/build`` prefix, which already applies
``require_onyx_craft_enabled`` and ``Permission.BASIC_ACCESS``.

The conditional ``WHERE decision IS NULL`` UPDATE in
``server/features/build/db/action_approval.py`` is the single
arbiter for concurrent decisions. The endpoint handles three cases:

1. Row not found / wrong owner → ``NOT_FOUND`` (existence not leaked).
2. Decision already recorded with the same value → idempotent 200.
3. Decision already recorded with a different value → ``CONFLICT``.

After a successful write, the API signals the waiting proxy via the
``approval:wake:{id}`` channel — best-effort, swallowed on cache blip;
the proxy's timeout + read-back path handles a lost wakeup.
"""

from datetime import datetime
from typing import Any
from typing import Literal
from uuid import UUID

from fastapi import APIRouter
from fastapi import Depends
from pydantic import BaseModel
from pydantic import ConfigDict
from sqlalchemy.orm import Session

from onyx.auth.permissions import require_permission
from onyx.cache.factory import get_cache_backend
from onyx.cache.interface import CACHE_TRANSIENT_ERRORS
from onyx.cache.interface import CacheBackend
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import ApprovalDecision
from onyx.db.enums import Permission
from onyx.db.models import ActionApproval
from onyx.db.models import User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.sandbox_proxy import approval_cache
from onyx.server.features.build.db import action_approval
from onyx.server.features.build.db.build_session import get_build_session
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()


router = APIRouter(prefix="/approvals")


# ---------------------------------------------------------------------------
# Pydantic shapes
# ---------------------------------------------------------------------------


class DecisionBody(BaseModel):
    """Body of ``POST /approvals/{approval_id}/decision``.

    Only APPROVED / REJECTED accepted from clients — EXPIRED is a
    server-only terminal state set by the proxy on timeout.
    """

    model_config = ConfigDict(extra="forbid")
    decision: Literal[ApprovalDecision.APPROVED, ApprovalDecision.REJECTED]


class ApprovalView(BaseModel):
    """Serialised ``ActionApproval`` row for API consumers."""

    approval_id: UUID
    session_id: UUID
    action_type: str
    payload: dict[str, Any]
    created_at: datetime
    decision: ApprovalDecision | None
    decided_at: datetime | None
    is_live: bool


class ApprovalListResponse(BaseModel):
    items: list[ApprovalView]


def _to_view(row: ActionApproval, *, is_live: bool) -> ApprovalView:
    return ApprovalView(
        approval_id=row.approval_id,
        session_id=row.session_id,
        action_type=row.action_type,
        payload=row.payload,
        created_at=row.created_at,
        decision=row.decision,
        decided_at=row.decided_at,
        is_live=is_live,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/sessions/{session_id}/live")
def list_live_approvals(
    session_id: UUID,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> ApprovalListResponse:
    """Return the session's currently-actionable approvals.

    "Actionable" = the DB row is undecided AND the Redis liveness key
    is present (i.e. some proxy is still parked on the wait). Orphan
    rows from a hard proxy crash are filtered out.
    """
    parent = get_build_session(session_id, user.id, db_session)
    if parent is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "session not found")

    pending_rows = action_approval.list_session_pending_action_approvals(
        db_session, session_id
    )
    cache = get_cache_backend(tenant_id=get_current_tenant_id())
    live = [_to_view(row, is_live=True) for row in pending_rows if _is_live(row, cache)]
    return ApprovalListResponse(items=live)


@router.get("/sessions/{session_id}")
def list_session_approvals(
    session_id: UUID,
    decision: ApprovalDecision | None = None,
    from_dt: datetime | None = None,
    to_dt: datetime | None = None,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> ApprovalListResponse:
    """Audit query for a single session.

    Caller must own the parent build_session — non-owners get
    ``NOT_FOUND`` (existence not leaked). ``decision=None`` returns
    every row including ``decision IS NULL`` (orphan attempts).
    """
    parent = get_build_session(session_id, user.id, db_session)
    if parent is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "session not found")

    rows = action_approval.list_session_action_approvals(
        db_session,
        session_id,
        decision=decision,
        from_dt=from_dt,
        to_dt=to_dt,
    )

    cache = get_cache_backend(tenant_id=get_current_tenant_id())
    items = [_to_view(row, is_live=_is_live(row, cache)) for row in rows]
    return ApprovalListResponse(items=items)


@router.post("/{approval_id}/decision")
def submit_decision(
    approval_id: UUID,
    body: DecisionBody,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> ApprovalView:
    """Record the caller's decision on a pending approval request."""
    request_row = action_approval.get_action_approval_for_user(
        db_session, approval_id, user.id
    )
    if request_row is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "approval request not found")

    # Idempotent double-click: same decision recorded → 200 with row.
    if request_row.decision is not None:
        if request_row.decision == body.decision:
            return _to_view(request_row, is_live=False)
        logger.info(
            "approval.decision_conflict approval_id=%s "
            "existing_decision=%s requested_decision=%s",
            approval_id,
            request_row.decision.value,
            body.decision.value,
        )
        raise OnyxError(
            OnyxErrorCode.CONFLICT,
            f"decision already recorded ({request_row.decision.value})",
        )

    updated = action_approval.record_decision(
        db_session, approval_id=approval_id, decision=body.decision
    )
    if updated is None:
        # Lost the race; expire the cached row so the re-read sees the
        # decision another session wrote (without this, SQLAlchemy's
        # identity map returns the stale request_row at decision=None).
        db_session.expire(request_row)
        fresh = action_approval.get_action_approval(db_session, approval_id)
        if fresh is None:
            # The row was deleted via FK cascade between the initial
            # read and the UPDATE — surface as NOT_FOUND rather than
            # CONFLICT so the client distinguishes the cases.
            raise OnyxError(OnyxErrorCode.NOT_FOUND, "approval request not found")
        if fresh.decision == body.decision:
            return _to_view(fresh, is_live=False)
        # record_decision returned None only because a different
        # decision is already recorded — fresh.decision is set here.
        # Explicit check (not `assert`) so `python -O` doesn't strip it.
        if fresh.decision is None:
            raise OnyxError(
                OnyxErrorCode.INTERNAL_ERROR,
                "approval row reverted to pending unexpectedly",
            )
        existing = fresh.decision.value
        logger.info(
            "approval.decision_conflict approval_id=%s lost_race=true "
            "existing_decision=%s requested_decision=%s",
            approval_id,
            existing,
            body.decision.value,
        )
        raise OnyxError(
            OnyxErrorCode.CONFLICT,
            f"decision already recorded ({existing})",
        )
    db_session.commit()

    logger.info(
        "approval.decision_recorded approval_id=%s session_id=%s "
        "user_id=%s decision=%s",
        approval_id,
        request_row.session_id,
        user.id,
        body.decision.value,
    )

    try:
        cache = get_cache_backend(tenant_id=get_current_tenant_id())
        approval_cache.finalize(approval_id, body.decision, cache)
    except CACHE_TRANSIENT_ERRORS as e:
        logger.warning(
            "approval.cache_signal_failed approval_id=%s error=%s",
            approval_id,
            str(e),
        )

    return _to_view(updated, is_live=False)


# ---------------------------------------------------------------------------
# is_live computation
# ---------------------------------------------------------------------------


def _is_live(row: ActionApproval, cache: CacheBackend) -> bool:
    """A row is live iff no decision is recorded AND the Redis
    liveness key still exists.

    Redis EXISTS is cheap (~sub-ms), so we hit it directly per row —
    no in-process memo. On a cache blip we default to "not live" so
    the card hides; the next refetch retries.
    """
    if row.decision is not None:
        return False
    try:
        return approval_cache.is_alive(row.approval_id, cache)
    except CACHE_TRANSIENT_ERRORS:
        return False
