"""Open and answer chat tool calls that wait for the user's approval.

Tool construction materializes each tool's action policy: a tool whose policy
asks carries a `ToolApprovalScope`, and the runtime gates its calls. The run's
store opens each request here (`ChatRunStore.request_approval`). The user
decides through the decision API, which saves the decision and wakes the
response's owner; the owner's control poll reads the decision and answers the
waiting call. The user's Stop saves a rejection of the requests that wait
(`ChatRunStore.reject_waiting_approvals`). A saved request gives the same
answer to its call, and to its record in the saved response.
"""

import datetime
import threading
from enum import Enum
from uuid import UUID

from onyx.agents.tools import (
    HumanToolAnswer,
    InputDecision,
    InputMode,
    PendingToolInput,
)
from onyx.chat.models import SavedToolApproval, ToolApprovalDenial
from onyx.db.action_policy import (
    current_action_policy,
    get_gated_app_id,
    get_or_create_gated_app_id,
)
from onyx.db.approval_request import (
    create_approval_request__no_commit,
    has_session_grant,
    lock_session_grants__no_commit,
)
from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.enums import ActionPolicy, ApprovalDecidedVia, ApprovalDecision
from onyx.llm.models import ToolResult
from onyx.tools.models import ToolApprovalScope

# Well below CHAT_EXECUTION_TIMEOUT_S, so one wait cannot use up the turn.
TOOL_APPROVAL_TIMEOUT = datetime.timedelta(minutes=10)


class ApprovalBlocker(str, Enum):
    """Why a call that needs approval cannot wait for the user's decision."""

    # An anonymous user cannot decide.
    SIGNED_OUT = "signed_out"
    # The run's events reach no listener, e.g. a background subagent.
    UNWATCHED_RUN = "unwatched_run"
    # The API server is shutting down, so nothing would receive the decision.
    SERVER_STOPPING = "server_stopping"


# What the model sees for a call that needs approval and cannot wait for it.
_CANNOT_ASK_MESSAGES = {
    ApprovalBlocker.SIGNED_OUT: (
        "The {name} call needs the user's approval, and the user must sign in "
        "to Onyx to approve it, so it did not run."
    ),
    ApprovalBlocker.UNWATCHED_RUN: (
        "The {name} call needs the user's approval, and only the agent that "
        "started you can ask the user for it, so it did not run. Ask that agent "
        "to handle this request. Do not retry this call until that agent "
        "confirms that the blocker is resolved."
    ),
    ApprovalBlocker.SERVER_STOPPING: (
        "The {name} call needs the user's approval, and the server is "
        "restarting, so it did not run."
    ),
}


# Set when the API server starts to shut down: runs that wait for approval
# end, so a deploy does not wait for the user. The server lifespan resets it.
_approval_waits_ending = threading.Event()


def end_approval_waits() -> None:
    _approval_waits_ending.set()


def reset_approval_waits() -> None:
    _approval_waits_ending.clear()


def approval_waits_ending() -> bool:
    return _approval_waits_ending.is_set()


def open_tool_approval(
    *,
    tenant_id: str,
    chat_session_id: UUID,
    response_id: int,
    user_id: UUID,
    tool_call_id: str,
    tool_name: str,
    display_name: str,
    scope: ToolApprovalScope,
    blocker: ApprovalBlocker | None,
) -> PendingToolInput | ToolResult | None:
    """A request for the call to wait for, an error result for a call that
    cannot run or wait, or None when a session grant approves the action.

    `tool_call_id` is the call of the response's step that the request
    belongs to: the call that waits, or the call whose tool made it."""
    with get_session_with_tenant(tenant_id=tenant_id) as db_session:
        lock_session_grants__no_commit(db_session, chat_session_id)
        gated_app_id = get_gated_app_id(db_session, scope.app_kind, scope.target_id)
        if gated_app_id is not None and has_session_grant(
            db_session, chat_session_id, gated_app_id, scope.action_id
        ):
            # A grant does not outlast a policy that now blocks the action.
            if (
                current_action_policy(
                    db_session,
                    user_id=user_id,
                    gated_app_id=gated_app_id,
                    action_id=scope.action_id,
                )
                != ActionPolicy.DENY
            ):
                return None
            return _disabled_result(tool_name)
        if blocker is not None:
            return ToolResult(
                content=_CANNOT_ASK_MESSAGES[blocker].format(name=tool_name),
                is_error=True,
            )
        approval_id, created_at = create_approval_request__no_commit(
            db_session,
            chat_session_id=chat_session_id,
            chat_message_id=response_id,
            gated_app_id=gated_app_id
            or get_or_create_gated_app_id(db_session, scope.app_kind, scope.target_id),
            action_id=scope.action_id,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            display_name=display_name,
        )
        db_session.commit()
    return PendingToolInput(
        request_id=str(approval_id),
        prompt=f"Allow {tool_name} to run?",
        mode=InputMode.EXECUTE,
        expires_at=created_at + TOOL_APPROVAL_TIMEOUT,
    )


def _disabled_result(tool_name: str) -> ToolResult:
    """The result of a call whose action the policies now disable."""
    return ToolResult(
        content=f"The {tool_name} tool is disabled, so this call did not run.",
        is_error=True,
        metadata=ToolApprovalDenial(outcome="disabled"),
    )


def tool_answer(
    approval_id: UUID, approval: SavedToolApproval | None
) -> HumanToolAnswer:
    """The answer that a decided request gives the call that waits for it.
    None is a request whose row was deleted, such as with its tool's server."""
    request_id = str(approval_id)
    if approval is None:
        return HumanToolAnswer(
            request_id=request_id,
            decision=InputDecision.DENY,
            result=ToolResult(
                content="This tool is no longer available, so this call did not run.",
                is_error=True,
                metadata=ToolApprovalDenial(outcome="disabled"),
            ),
        )
    name = approval.tool_name
    if approval.decision == ApprovalDecision.APPROVED:
        return HumanToolAnswer(
            request_id=request_id,
            decision=InputDecision.APPROVE,
            standing=approval.decided_via == ApprovalDecidedVia.SESSION_GRANT,
        )
    if approval.decided_via == ApprovalDecidedVia.POLICY:
        result = _disabled_result(name)
    elif approval.decision == ApprovalDecision.REJECTED:
        result = ToolResult(
            content=f"The user rejected this {name} call, so it did not run.",
            is_error=True,
            metadata=ToolApprovalDenial(outcome="rejected"),
        )
    else:
        result = ToolResult(
            content=(
                f"The approval request for this {name} call expired before the "
                "user answered, so it did not run."
            ),
            is_error=True,
            metadata=ToolApprovalDenial(outcome="expired"),
        )
    return HumanToolAnswer(
        request_id=request_id, decision=InputDecision.DENY, result=result
    )


def ended_answer(approval: SavedToolApproval) -> HumanToolAnswer | None:
    """How a request ended for its call: the answer of its decision, or None
    when it was not decided, or expired before its deadline because its call
    stopped waiting."""
    if approval.decision is None or (
        approval.decision == ApprovalDecision.EXPIRED
        and (
            approval.decided_at is None
            or approval.decided_at < approval.created_at + TOOL_APPROVAL_TIMEOUT
        )
    ):
        return None
    return tool_answer(approval.id, approval)
