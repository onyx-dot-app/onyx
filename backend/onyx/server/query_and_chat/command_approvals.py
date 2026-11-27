"""The user's decision on an app request of a command in the chat's VM.

The egress proxy holds the request and waits on its `action_approval` row
(`sandbox_proxy/addons/gate.py`); the call that waits on the command shows
the card (`tools/tool_implementations/sandbox/command_approvals.py`). The
decision is written through `try_record_decision` and wakes the proxy. No
run waits for it, so no response continues.
"""

from uuid import UUID

from sqlalchemy.orm import Session

from onyx.cache.factory import get_cache_backend
from onyx.cache.interface import CACHE_TRANSIENT_ERRORS
from onyx.db import action_approval
from onyx.db.enums import ApprovalDecidedVia, ApprovalDecision
from onyx.db.integration import get_integration_by_id
from onyx.db.models import ActionApproval
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.external_apps.matching.engine import actions_requiring_approval
from onyx.integrations.models import EffectivePolicy
from onyx.integrations.policy import resolve_chat_action_policies
from onyx.sandbox_proxy import approval_cache
from onyx.server.features.action_policies.models import ApprovalChoice
from onyx.server.query_and_chat.models import ApprovalDecisionResponse
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()


def _current_policies(
    db_session: Session,
    rows: list[ActionApproval],
    integration_id: int | None,
    chat_session_id: UUID,
    user_id: UUID,
) -> dict[str, EffectivePolicy] | None:
    """The current policies of the actions of `rows`, or None when the
    integration is gone (a deleted one leaves the rows without one) or
    turned off."""
    integration = (
        None
        if integration_id is None
        else get_integration_by_id(integration_id, db_session)
    )
    if integration is None or not integration.enabled:
        return None
    return resolve_chat_action_policies(
        db_session,
        integration=integration,
        action_keys={
            action["action_type"]
            for row in rows
            for action in row.actions
            if isinstance(action.get("action_type"), str)
        },
        user_id=user_id,
        chat_session_id=chat_session_id,
    )


def _blocks(row: ActionApproval, policies: dict[str, EffectivePolicy] | None) -> bool:
    """The proxy's final check now refuses the request of `row`."""
    return policies is None or any(
        policies.get(action.get("action_type")) == EffectivePolicy.BLOCKED
        for action in row.actions
    )


def _asks_more(row: ActionApproval, policies: dict[str, EffectivePolicy]) -> bool:
    """An action of `row` asks now that did not ask when the request
    arrived. A command grant covers only the Ask actions of the row, so the
    proxy refuses such a request (`gate.py:_recheck_approval`)."""
    asked = set(actions_requiring_approval(row.actions))
    return any(
        policies.get(action.get("action_type")) == EffectivePolicy.ASK
        and action.get("action_type") not in asked
        for action in row.actions
    )


def decide_command_approval(
    db_session: Session, row: ActionApproval, choice: ApprovalChoice, user_id: UUID
) -> ApprovalDecisionResponse:
    """Approve the request once or for the rest of its command, or reject
    it. Approving for the command also approves the command's other waiting
    requests that the grant covers. Approving a request that the current
    policies block, or whose integration is deleted, saves a rejection by the
    policy, also for a covered one. Approving for the command a request with
    an action that asks now but did not ask when it arrived is refused, since
    the proxy would refuse it. Repeating a saved decision returns it; a
    different one, or a request that no longer waits, is a conflict."""
    command_id = row.command_id
    chat_session_id = row.chat_session_id
    integration_id = row.integration_id
    if chat_session_id is None or command_id is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Approval request not found")
    policies = (
        None
        if choice == ApprovalChoice.REJECT
        else _current_policies(
            db_session, [row], integration_id, chat_session_id, user_id
        )
    )
    blocked = choice != ApprovalChoice.REJECT and _blocks(row, policies)
    if blocked:
        choice = ApprovalChoice.REJECT
    if (
        choice == ApprovalChoice.APPROVE_COMMAND
        and policies is not None
        and _asks_more(row, policies)
    ):
        # The proxy refuses a command approval that misses an Ask action.
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "Another action of this request now needs approval. Approve it once or reject it.",
        )
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
    decision = (
        ApprovalDecision.REJECTED
        if choice == ApprovalChoice.REJECT
        else ApprovalDecision.APPROVED
    )
    cutoff = action_approval.waiting_cutoff()
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
        if row.decision != decision or row.decided_via != decided_via:
            raise OnyxError(
                OnyxErrorCode.CONFLICT,
                "This request was already decided or is no longer waiting",
            )
        # A retry repeats the wakes and the scan that the first call may
        # have missed, and keeps the grant that it saved.
    else:
        # A grant is saved only for a committed approval. The commit also
        # comes before the scan below locks other rows of the command, so two
        # decisions of one command never wait on each other's rows.
        db_session.commit()
        if for_command and integration_id is not None:
            try:
                # A request that misses the grant committed its row before
                # the scan below reads it.
                approval_cache.grant_command_actions(
                    command_id, chat_session_id, integration_id, granted, cache
                )
            except CACHE_TRANSIENT_ERRORS as error:
                # Later requests of the command ask again.
                logger.warning(
                    "command_approval_grant_failed approval_id=%s error=%s",
                    row.approval_id,
                    error,
                )
    approval_cache.send_wakes([row.approval_id], decision, cache)

    covered_ids: list[UUID] = []
    blocked_ids: list[UUID] = []
    if for_command and integration_id is not None:
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
        # The grant covers only the Ask actions, and an admin may have
        # blocked another action of a request, or made it ask, while it
        # waited. A request with a new Ask action keeps its card.
        policies = (
            _current_policies(
                db_session, covered_rows, integration_id, chat_session_id, user_id
            )
            if covered_rows
            else None
        )
        for other in covered_rows:
            other_blocked = _blocks(other, policies)
            if (
                not other_blocked
                and policies is not None
                and _asks_more(other, policies)
            ):
                continue
            if action_approval.try_record_decision(
                db_session,
                approval_id=other.approval_id,
                decision=ApprovalDecision.REJECTED
                if other_blocked
                else ApprovalDecision.APPROVED,
                decided_via=ApprovalDecidedVia.POLICY
                if other_blocked
                else ApprovalDecidedVia.COMMAND_GRANT,
                created_after=cutoff,
            ):
                (blocked_ids if other_blocked else covered_ids).append(
                    other.approval_id
                )
        # Commit the decisions before the proxy wakes and reads them.
        db_session.commit()
        approval_cache.send_wakes(covered_ids, decision, cache)
        approval_cache.send_wakes(blocked_ids, ApprovalDecision.REJECTED, cache)

    logger.info(
        "command_approval_decided approval_id=%s command_id=%s decision=%s "
        "decided_via=%s covered=%s blocked=%s",
        row.approval_id,
        command_id,
        decision.value,
        decided_via.value,
        len(covered_ids),
        len(blocked_ids),
    )
    return ApprovalDecisionResponse(
        approval_id=row.approval_id, decision=decision, decided_via=decided_via
    )
