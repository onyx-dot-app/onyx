"""The user's decision on an app request of a command in the chat's VM.

The egress proxy holds the request and waits on its `action_approval` row
(`sandbox_proxy/addons/gate.py`); the call that waits on the command shows
the card (`tools/tool_implementations/sandbox/command_approvals.py`). The
decision is written through `try_record_decision` and wakes the proxy. No
run waits for it, so no response continues.
"""

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy.orm import Session

from onyx.cache.factory import get_cache_backend
from onyx.cache.interface import CACHE_TRANSIENT_ERRORS, CacheBackend
from onyx.chat.tool_approvals import action_now_blocked
from onyx.db import action_approval
from onyx.db.enums import ApprovalDecidedVia, ApprovalDecision
from onyx.db.models import ActionApproval
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.sandbox_proxy import approval_cache
from onyx.server.features.action_policies.models import ApprovalChoice
from onyx.server.features.build.configs import SANDBOX_APPROVAL_WAIT_TIMEOUT_SECONDS
from onyx.server.query_and_chat.models import ApprovalDecisionResponse
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()


def _response(
    row: ActionApproval, decided_via: ApprovalDecidedVia
) -> ApprovalDecisionResponse:
    decision = row.decision
    if decision not in (ApprovalDecision.APPROVED, ApprovalDecision.REJECTED):
        raise OnyxError(OnyxErrorCode.CONFLICT, "This request is no longer waiting")
    return ApprovalDecisionResponse(
        approval_id=row.approval_id, decision=decision, decided_via=decided_via
    )


def _wake(
    approval_ids: list[UUID], decision: ApprovalDecision, cache: CacheBackend
) -> None:
    """Wake the parked proxies. A missed wake leaves a proxy to its wait
    timeout."""
    for approval_id in approval_ids:
        try:
            approval_cache.send_wake(approval_id, decision, cache)
        except CACHE_TRANSIENT_ERRORS as error:
            logger.warning(
                "command_approval_wake_failed approval_id=%s error=%s",
                approval_id,
                error,
            )


def _now_blocked(
    db_session: Session, row: ActionApproval, chat_session_id: UUID, user_id: UUID
) -> bool:
    """True when the current policies block one of the request's actions,
    as the proxy's final check finds."""
    return any(
        action_now_blocked(
            db_session,
            integration_id=row.integration_id,
            action_id=action["action_type"],
            user_id=user_id,
            chat_session_id=chat_session_id,
        )
        for action in row.actions
        if isinstance(action.get("action_type"), str)
    )


def decide_command_approval(
    db_session: Session, row: ActionApproval, choice: ApprovalChoice, user_id: UUID
) -> ApprovalDecisionResponse:
    """Approve the request once or for the rest of its command, or reject
    it. Approving for the command also approves the command's other waiting
    requests that the grant covers. Approving a request that the current
    policies block saves a rejection by the policy. Repeating a saved
    decision returns it; a different one, or a request that no longer waits,
    is a conflict."""
    command_id = row.command_id
    chat_session_id = row.chat_session_id
    if chat_session_id is None or command_id is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Approval request not found")
    blocked = choice != ApprovalChoice.REJECT and _now_blocked(
        db_session, row, chat_session_id, user_id
    )
    if blocked:
        choice = ApprovalChoice.REJECT
    if choice == ApprovalChoice.APPROVE_SESSION:
        # Clients that know no command scope offer a chat approval; the proxy
        # keeps no chat grants, so it is a single approval.
        choice = ApprovalChoice.APPROVE_ONCE
    for_command = choice == ApprovalChoice.APPROVE_COMMAND
    granted = approval_cache.command_grant_actions(row.actions) if for_command else []
    if for_command and not granted:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "This request cannot be approved for the rest of the command",
        )
    integration_id = row.integration_id
    decision = (
        ApprovalDecision.REJECTED
        if choice == ApprovalChoice.REJECT
        else ApprovalDecision.APPROVED
    )
    cutoff = datetime.now(timezone.utc) - timedelta(
        seconds=SANDBOX_APPROVAL_WAIT_TIMEOUT_SECONDS
    )
    decided_via = (
        ApprovalDecidedVia.POLICY
        if blocked
        else ApprovalDecidedVia.COMMAND_GRANT
        if for_command
        else ApprovalDecidedVia.USER
    )
    cache = get_cache_backend(tenant_id=get_current_tenant_id())
    decided = action_approval.try_record_decision(
        db_session,
        approval_id=row.approval_id,
        decision=decision,
        decided_via=decided_via,
        created_after=cutoff,
    )
    if decided is None:
        db_session.refresh(row)
        if row.decision == decision and row.decided_via == decided_via:
            # A retry also sends a wake that the first call missed.
            _wake([row.approval_id], decision, cache)
            return _response(row, decided_via)
        raise OnyxError(
            OnyxErrorCode.CONFLICT,
            "This request was already decided or is no longer waiting",
        )
    if for_command and integration_id is not None:
        try:
            # Saved before the commit: the proxy checks the grant of a
            # COMMAND_GRANT row, and a request that misses the grant in the
            # cache committed its row before the scan below reads it.
            approval_cache.grant_command_actions(
                command_id, chat_session_id, integration_id, granted, cache
            )
        except CACHE_TRANSIENT_ERRORS as error:
            # The request goes as approved once; later requests of the
            # command ask again.
            logger.warning(
                "command_approval_grant_failed approval_id=%s error=%s",
                row.approval_id,
                error,
            )
            for_command = False
            decided_via = decided.decided_via = ApprovalDecidedVia.USER
    # Commit before the scan below locks other rows of the command, so two
    # decisions of one command never wait on each other's rows.
    db_session.commit()
    _wake([row.approval_id], decision, cache)

    covered_ids: list[UUID] = []
    if for_command and integration_id is not None:
        for other in action_approval.list_pending_command_action_approvals(
            db_session,
            chat_session_id=chat_session_id,
            command_id=command_id,
            created_after=cutoff,
        ):
            # This grant with the earlier ones, as the proxy checks them.
            try:
                covered = (
                    other.integration_id == integration_id
                    and approval_cache.command_grants_cover(
                        command_id,
                        chat_session_id,
                        integration_id,
                        approval_cache.command_grant_actions(other.actions),
                        cache,
                    )
                )
            except CACHE_TRANSIENT_ERRORS:
                covered = False
            if covered and action_approval.try_record_decision(
                db_session,
                approval_id=other.approval_id,
                decision=ApprovalDecision.APPROVED,
                decided_via=ApprovalDecidedVia.COMMAND_GRANT,
                created_after=cutoff,
            ):
                covered_ids.append(other.approval_id)
        # Commit the decisions before the proxy wakes and reads them.
        db_session.commit()
        _wake(covered_ids, decision, cache)

    logger.info(
        "command_approval_decided approval_id=%s command_id=%s decision=%s "
        "decided_via=%s covered=%s",
        row.approval_id,
        command_id,
        decision.value,
        decided_via.value,
        len(covered_ids),
    )
    return _response(decided, decided_via)
