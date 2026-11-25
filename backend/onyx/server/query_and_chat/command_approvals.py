"""The user's decision on an app request of a command in the chat's VM.

The egress proxy holds the request and waits on its `action_approval` row
(`sandbox_proxy/addons/gate.py`); the call that waits on the command shows
the card (`tools/tool_implementations/sandbox/command_approvals.py`). The
decision is written through `try_record_decision` and wakes the proxy. No
run waits for it, so no response continues.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from onyx.cache.factory import get_cache_backend
from onyx.cache.interface import CACHE_TRANSIENT_ERRORS, CacheBackend
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


def decide_command_approval(
    db_session: Session, row: ActionApproval, choice: ApprovalChoice
) -> ApprovalDecisionResponse:
    """Approve the request once or for the rest of its command, or reject
    it. Approving for the command also approves the command's other waiting
    requests that the grant covers. Repeating a saved decision returns it;
    a different one, or a request that no longer waits, is a conflict."""
    command_id = row.command_id
    if row.chat_session_id is None or command_id is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Approval request not found")
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
    cache: CacheBackend | None = None
    try:
        cache = get_cache_backend(tenant_id=get_current_tenant_id())
        if for_command and integration_id is not None:
            # Saved before the decision, so a recorded command grant is one
            # the proxy can honor, and before the scan: a request that misses
            # the grant in the cache committed its row before that check.
            approval_cache.grant_command_actions(
                command_id, integration_id, granted, cache
            )
    except CACHE_TRANSIENT_ERRORS as error:
        # The proxy would refuse a grant that is not saved: approve once.
        logger.warning(
            "command_approval_grant_failed approval_id=%s error=%s",
            row.approval_id,
            error,
        )
        for_command = False
    decision = (
        ApprovalDecision.REJECTED
        if choice == ApprovalChoice.REJECT
        else ApprovalDecision.APPROVED
    )
    decided_via = (
        ApprovalDecidedVia.COMMAND_GRANT if for_command else ApprovalDecidedVia.USER
    )
    cutoff = datetime.now(timezone.utc) - timedelta(
        seconds=SANDBOX_APPROVAL_WAIT_TIMEOUT_SECONDS
    )
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
            return _response(row, decided_via)
        raise OnyxError(
            OnyxErrorCode.CONFLICT,
            "This request was already decided or is no longer waiting",
        )

    # Commit before the scan below locks other rows of the command, so two
    # decisions of one command never wait on each other's rows.
    db_session.commit()

    approved_ids = [row.approval_id]

    def covered(required: list[str]) -> bool:
        """The command's grants, this one with the earlier ones, cover the
        Ask actions of a waiting request, as the proxy checks them."""
        if not required or integration_id is None:
            return False
        try:
            return cache is not None and approval_cache.command_grants_cover(
                command_id, integration_id, required, cache
            )
        except CACHE_TRANSIENT_ERRORS:
            return False

    if for_command and integration_id is not None:
        for other in action_approval.list_pending_command_action_approvals(
            db_session,
            chat_session_id=row.chat_session_id,
            command_id=command_id,
            created_after=cutoff,
        ):
            if other.integration_id != integration_id or not covered(
                approval_cache.command_grant_actions(other.actions)
            ):
                continue
            if action_approval.try_record_decision(
                db_session,
                approval_id=other.approval_id,
                decision=ApprovalDecision.APPROVED,
                decided_via=ApprovalDecidedVia.COMMAND_GRANT,
                created_after=cutoff,
            ):
                approved_ids.append(other.approval_id)
        # Commit the decisions before the proxy wakes and reads them.
        db_session.commit()

    try:
        if cache is not None:
            for approval_id in approved_ids:
                approval_cache.send_wake(approval_id, decision, cache)
    except CACHE_TRANSIENT_ERRORS as error:
        # A missed wake leaves the proxy to its wait timeout.
        logger.warning(
            "command_approval_wake_failed approval_id=%s error=%s",
            row.approval_id,
            error,
        )
    logger.info(
        "command_approval_decided approval_id=%s command_id=%s decision=%s "
        "decided_via=%s covered=%s",
        row.approval_id,
        command_id,
        decision.value,
        decided_via.value,
        len(approved_ids) - 1,
    )
    return _response(decided, decided_via)
