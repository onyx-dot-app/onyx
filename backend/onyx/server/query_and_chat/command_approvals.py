"""The user's decision on an app request of a command in the chat's VM.

The egress proxy holds the request and waits on its `action_approval` row
(`sandbox_proxy/addons/gate.py`); the call that waits on the command shows
the card (`tools/tool_implementations/sandbox/command_approvals.py`). The
decision is written through `action_approval.try_record_decision` and wakes
the proxy. No
run waits for it, so no response continues.
"""

from datetime import datetime
from typing import Literal
from uuid import UUID

from sqlalchemy.orm import Session

from onyx.cache.factory import get_cache_backend
from onyx.cache.interface import CACHE_TRANSIENT_ERRORS, CacheBackend
from onyx.db import action_approval
from onyx.db.enums import ApprovalDecidedVia, ApprovalDecision
from onyx.db.models import ActionApproval
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.external_apps.matching.engine import actions_requiring_approval
from onyx.integrations.models import EffectivePolicy
from onyx.integrations.policy import (
    ApprovalRecheck,
    current_chat_action_policies,
    recheck_approval,
)
from onyx.sandbox_proxy import approval_cache
from onyx.server.features.action_policies.models import ApprovalChoice
from onyx.server.query_and_chat.models import ApprovalDecisionResponse
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()


def saved_answer_or_conflict(
    choice: ApprovalChoice,
    decision: ApprovalDecision | None,
    decided_via: ApprovalDecidedVia | None,
) -> tuple[
    Literal[ApprovalDecision.APPROVED, ApprovalDecision.REJECTED],
    ApprovalDecidedVia,
]:
    """The saved decision that answers a repeated choice (see
    `ApprovalChoice.saved_answer`); any other one is a conflict."""
    answer = choice.saved_answer(decision, decided_via)
    if answer is None:
        raise OnyxError(
            OnyxErrorCode.CONFLICT,
            "This request was already decided or is no longer waiting",
        )
    return answer


def _action_keys(rows: list[ActionApproval]) -> set[str]:
    return {
        action["action_type"]
        for row in rows
        for action in row.actions
        if isinstance(action.get("action_type"), str)
    }


def _recheck(
    row: ActionApproval, policies: dict[str, EffectivePolicy] | None
) -> ApprovalRecheck:
    """The proxy's final check of the request of `row` now. A command grant
    covers only the Ask actions of the row, so the proxy refuses a granted
    request with a new Ask action (`gate.py:_recheck_approval`)."""
    return recheck_approval(
        policies, _action_keys([row]), set(actions_requiring_approval(row.actions))
    )


def _command_choice(
    db_session: Session, row: ActionApproval, choice: ApprovalChoice, user_id: UUID
) -> tuple[ApprovalChoice, bool]:
    """The choice that the proxy can take for a waiting `row`, and whether the
    current policies block it."""
    if choice == ApprovalChoice.REJECT or row.chat_session_id is None:
        return choice, False
    recheck = _recheck(
        row,
        current_chat_action_policies(
            db_session,
            integration_id=row.integration_id,
            action_keys=_action_keys([row]),
            user_id=user_id,
            chat_session_id=row.chat_session_id,
        ),
    )
    if recheck is ApprovalRecheck.BLOCKED:
        return choice, True
    if choice == ApprovalChoice.APPROVE_SESSION:
        # Clients that know no command scope offer a chat approval; the proxy
        # keeps no chat grants, so it is a single approval.
        return ApprovalChoice.APPROVE_ONCE, False
    if (
        choice == ApprovalChoice.APPROVE_COMMAND
        and recheck is ApprovalRecheck.ASKS_MORE
    ):
        # The proxy refuses a command grant that misses a current Ask action,
        # so the request is approved once and grants nothing.
        return ApprovalChoice.APPROVE_ONCE, False
    return choice, False


def _save_command_grant(
    approval_id: UUID,
    command_id: UUID,
    chat_session_id: UUID,
    integration_id: int,
    granted: list[str],
    cache: CacheBackend,
) -> None:
    try:
        # A request that misses the grant committed its row before the scan
        # of the command's other requests reads it.
        approval_cache.grant_command_actions(
            command_id, chat_session_id, integration_id, granted, cache
        )
    except CACHE_TRANSIENT_ERRORS as error:
        # Later requests of the command ask again.
        logger.warning(
            "command_approval_grant_failed approval_id=%s error=%s",
            approval_id,
            error,
        )


def _grant_command_to_pending_requests(
    db_session: Session,
    command_id: UUID,
    chat_session_id: UUID,
    integration_id: int,
    user_id: UUID,
    cutoff: datetime,
    cache: CacheBackend,
) -> tuple[list[UUID], list[UUID]]:
    """Decide the command's other waiting requests that its grants cover, and
    commit. Returns the approved and the policy-rejected IDs."""
    covered_rows: list[ActionApproval] = []
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
        if covered:
            covered_rows.append(other)
    # The grant covers only the Ask actions, and an admin may have blocked
    # another action of a request, or made it ask, while it waited. A request
    # with a new Ask action keeps its card.
    policies = (
        current_chat_action_policies(
            db_session,
            integration_id=integration_id,
            action_keys=_action_keys(covered_rows),
            user_id=user_id,
            chat_session_id=chat_session_id,
        )
        if covered_rows
        else None
    )
    approved_ids: list[UUID] = []
    blocked_ids: list[UUID] = []
    for other in covered_rows:
        recheck = _recheck(other, policies)
        if recheck is ApprovalRecheck.ASKS_MORE:
            continue
        blocked = recheck is ApprovalRecheck.BLOCKED
        decision, decided_via = ApprovalChoice.APPROVE_COMMAND.outcome(blocked=blocked)
        if action_approval.try_record_decision(
            db_session,
            approval_id=other.approval_id,
            decision=decision,
            decided_via=decided_via,
            created_after=cutoff,
        ):
            (blocked_ids if blocked else approved_ids).append(other.approval_id)
    # Commit the decisions before the proxy wakes and reads them.
    db_session.commit()
    return approved_ids, blocked_ids


def _record_command_decision(
    db_session: Session,
    row: ActionApproval,
    choice: ApprovalChoice,
    user_id: UUID,
    cutoff: datetime,
) -> tuple[
    Literal[ApprovalDecision.APPROVED, ApprovalDecision.REJECTED],
    ApprovalDecidedVia,
    list[str] | None,
]:
    """Save the decision on a waiting `row`. Returns the decision and the
    actions that it grants for the command, or None for them when the row
    no longer waits and nothing was saved."""
    command_choice, blocked = (
        _command_choice(db_session, row, choice, user_id)
        if row.decision is None
        else (choice, False)
    )
    decision, decided_via = command_choice.outcome(blocked=blocked)
    if row.decision is not None:
        return decision, decided_via, None
    granted = (
        approval_cache.command_grant_actions(row.actions)
        if decided_via == ApprovalDecidedVia.COMMAND_GRANT
        else []
    )
    if decided_via == ApprovalDecidedVia.COMMAND_GRANT and not granted:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "This request cannot be approved for the rest of the command",
        )
    recorded = action_approval.try_record_decision(
        db_session,
        approval_id=row.approval_id,
        decision=decision,
        decided_via=decided_via,
        created_after=cutoff,
    )
    return decision, decided_via, None if recorded is None else granted


def decide_command_approval(
    db_session: Session, row: ActionApproval, choice: ApprovalChoice, user_id: UUID
) -> ApprovalDecisionResponse:
    """Approve the request once or for the rest of its command, or reject
    it. Approving for the command also approves the command's other waiting
    requests that the grant covers. Approving a request that the current
    policies block, or whose integration is deleted, saves a rejection by the
    policy, also for a covered one. Approving for the command a request with
    an action that asks now but did not ask when it arrived approves it once,
    since the proxy refuses such a grant. Repeating a saved decision returns
    it, also after the policies change, and repeats its wakes and scan; a
    different one, or a request that no longer waits, is a conflict."""
    command_id = row.command_id
    chat_session_id = row.chat_session_id
    integration_id = row.integration_id
    if chat_session_id is None or command_id is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Approval request not found")
    cache = get_cache_backend(tenant_id=get_current_tenant_id())
    cutoff = action_approval.waiting_cutoff()

    decision, decided_via, granted = _record_command_decision(
        db_session, row, choice, user_id, cutoff
    )
    if granted is None:
        # A retry repeats the wakes and the scan that the first call may have
        # missed, and keeps the grant that it saved.
        db_session.refresh(row)
        decision, decided_via = saved_answer_or_conflict(
            choice, row.decision, row.decided_via
        )
    else:
        # A grant is saved only for a committed approval. The commit also
        # comes before the scan below locks other rows of the command, so two
        # decisions of one command never wait on each other's rows.
        db_session.commit()
        if granted and integration_id is not None:
            _save_command_grant(
                row.approval_id,
                command_id,
                chat_session_id,
                integration_id,
                granted,
                cache,
            )
    approval_cache.send_wakes([row.approval_id], decision, cache)

    approved_ids: list[UUID] = []
    blocked_ids: list[UUID] = []
    if decided_via == ApprovalDecidedVia.COMMAND_GRANT and integration_id is not None:
        approved_ids, blocked_ids = _grant_command_to_pending_requests(
            db_session,
            command_id,
            chat_session_id,
            integration_id,
            user_id,
            cutoff,
            cache,
        )
        approval_cache.send_wakes(approved_ids, decision, cache)
        approval_cache.send_wakes(blocked_ids, ApprovalDecision.REJECTED, cache)

    logger.info(
        "command_approval_decided approval_id=%s command_id=%s decision=%s "
        "decided_via=%s covered=%s blocked=%s",
        row.approval_id,
        command_id,
        decision.value,
        decided_via.value,
        len(approved_ids),
        len(blocked_ids),
    )
    return ApprovalDecisionResponse(
        approval_id=row.approval_id, decision=decision, decided_via=decided_via
    )
