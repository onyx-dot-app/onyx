"""Open and answer chat tool calls that wait for the user's approval.

Tool construction materializes each tool's action policy: a tool whose policy
asks carries a `ToolApprovalScope`, and the runtime gates its calls. The run's
store opens each request here (`ChatRunStore.request_approval`). The user
decides through the decision API, which saves the decision and wakes the
response's owner; the owner's control poll reads the decision and answers the
waiting call.
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
from onyx.chat.models import ToolApprovalDenial
from onyx.db.action_policy import (
    current_action_policy,
    get_gated_app_id,
    get_or_create_gated_app_id,
)
from onyx.db.approval_request import (
    SavedDecision,
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


_CANNOT_ASK_MESSAGES = {
    ApprovalBlocker.SIGNED_OUT: (
        "The {name} tool needs the user's approval, and this conversation cannot "
        "ask for it because the user is not signed in. Tell the user to sign in "
        "to Onyx and make this request again."
    ),
    ApprovalBlocker.UNWATCHED_RUN: (
        "The {name} tool needs the user's approval, and this agent cannot ask for "
        "it. Report this to the agent that started you. Do not retry the call."
    ),
    ApprovalBlocker.SERVER_STOPPING: (
        "The {name} tool needs the user's approval, and the server is restarting, "
        "so this call did not run. Do not retry it. Tell the user to make this "
        "request again in a moment."
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
    call_name: str,
    scope: ToolApprovalScope,
    blocker: ApprovalBlocker | None,
) -> PendingToolInput | ToolResult | None:
    """A request for the call to wait for, an error result for a call that
    cannot run or wait, or None when a session grant approves the action."""
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
            return _disabled_result(scope.action_id)
        if blocker is not None:
            return ToolResult(
                content=_CANNOT_ASK_MESSAGES[blocker].format(name=call_name),
                is_error=True,
            )
        approval_id, created_at = create_approval_request__no_commit(
            db_session,
            chat_session_id=chat_session_id,
            chat_message_id=response_id,
            gated_app_id=gated_app_id
            or get_or_create_gated_app_id(db_session, scope.app_kind, scope.target_id),
            action_id=scope.action_id,
        )
        db_session.commit()
    return PendingToolInput(
        request_id=str(approval_id),
        prompt=f"Allow {call_name} to run?",
        mode=InputMode.EXECUTE,
        expires_at=created_at + TOOL_APPROVAL_TIMEOUT,
    )


def _disabled_result(action_id: str) -> ToolResult:
    """The result of a call whose action the policies now disable."""
    return ToolResult(
        content=(
            f"The {action_id} tool is disabled, so this call did not run. Do not retry "
            "it. Tell the user."
        ),
        is_error=True,
        metadata=ToolApprovalDenial(outcome="disabled"),
    )


def tool_answer(
    approval_id: UUID,
    saved: SavedDecision | None,
) -> HumanToolAnswer:
    """The answer that a saved decision, with how it was made and the action
    ID, gives the waiting call. None is a request whose row was deleted, such
    as with its tool's server."""
    if saved is None:
        return HumanToolAnswer(
            request_id=str(approval_id),
            decision=InputDecision.DENY,
            result=ToolResult(
                content=(
                    "This tool is no longer available, so this call did not run. "
                    "Do not retry it. Tell the user."
                ),
                is_error=True,
                metadata=ToolApprovalDenial(outcome="disabled"),
            ),
        )
    decision, decided_via, action_id = saved
    if decision == ApprovalDecision.APPROVED:
        return HumanToolAnswer(
            request_id=str(approval_id),
            decision=InputDecision.APPROVE,
            standing=decided_via == ApprovalDecidedVia.SESSION_GRANT,
        )
    if decided_via == ApprovalDecidedVia.POLICY:
        result = _disabled_result(action_id)
    elif decision == ApprovalDecision.REJECTED:
        result = ToolResult(
            content=(
                "The user rejected this call, so it did not run. Do not retry it "
                "or get the same result another way. Tell the user, and ask how "
                "to continue."
            ),
            is_error=True,
            metadata=ToolApprovalDenial(outcome="rejected"),
        )
    else:
        result = ToolResult(
            content=(
                "The user did not answer the approval request for this call in "
                "time, so it did not run. Do not assume the user refused. Tell "
                "the user that the action needs their approval, and do not retry "
                "it in this response."
            ),
            is_error=True,
            metadata=ToolApprovalDenial(outcome="expired"),
        )
    return HumanToolAnswer(
        request_id=str(approval_id), decision=InputDecision.DENY, result=result
    )
