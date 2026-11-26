"""Open and answer chat tool calls that wait for the user's approval.

Tool construction materializes each tool's action policy: a tool whose policy
asks carries a `ToolApprovalScope`, and the runtime gates its calls. A
built-in tool carries a scope with no integration (`onyx:<operation>`), and no
policy blocks it. The store of the run that calls, the root's or a
subagent's, asks the tool what the call's card shows
(`Tool.approval_details`; a call that needs no approval runs) and opens each
request here (`ChatRunStore.request_approval`). The request row holds what the
card shows. A run whose waits are all on people, on its requests or on runs
that wait the same way, hands off: its checkpoint is saved and its pod is
free. The user decides through the decision API, which saves the decision;
once no request of the response waits, dispatch resumes the run on any pod
(`ChatRunStore.resume`), which answers each waiting call from its saved
decision. The user's Stop of a live
turn saves a rejection of the requests that the turn's runs wait on and
gives it to those runs (`ChatRunStore.reject_waiting_inputs`). The store
closes the requests of a run that ends when it releases the run. A saved
request gives the same answer to its call, and to its record in the saved
response.
"""

from uuid import UUID

from pydantic import JsonValue
from sqlalchemy.orm import Session

from onyx.agents.tool_execution import UNAVAILABLE_CALL_MESSAGE
from onyx.agents.tools import (
    HumanToolAnswer,
    InputDecision,
    InputMode,
    PendingToolInput,
)
from onyx.chat.models import SavedToolApproval, ToolApprovalDenial
from onyx.db.approval_request import (
    create_approval_request__no_commit,
    lock_session_grants__no_commit,
)
from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.enums import ApprovalDecidedVia, ApprovalDecision
from onyx.db.integration import get_integration_by_id
from onyx.db.integration_policy import get_session_granted_actions
from onyx.integrations.models import EffectivePolicy
from onyx.integrations.policy import (
    integration_action_always_asks,
    resolve_chat_action_policies,
)
from onyx.llm.models import ToolResult
from onyx.tools.models import (
    ToolApprovalDetails,
    ToolApprovalScope,
    is_builtin_action,
)


def open_tool_approval(
    *,
    tenant_id: str,
    chat_session_id: UUID,
    response_id: int,
    user_id: UUID,
    tool_call_id: str,
    tool_name: str,
    details: ToolApprovalDetails,
    arguments: dict[str, JsonValue],
    scope: ToolApprovalScope,
    signed_out: bool,
) -> PendingToolInput | ToolResult | None:
    """A request for the call to wait for, an error result for a call that
    cannot run or wait, or None when a session grant approves the action.
    `arguments` are the call's, as its card shows them when the details give
    no payload.

    `tool_call_id` is the call of the response's step that the request
    belongs to: the call that waits, or the call whose tool made it."""
    with get_session_with_tenant(tenant_id=tenant_id) as db_session:
        lock_session_grants__no_commit(db_session, chat_session_id)
        can_approve_for_chat = not integration_action_always_asks(
            db_session, scope.integration_id, scope.action_id
        )
        if can_approve_for_chat and scope.action_id in get_session_granted_actions(
            db_session, chat_session_id, scope.integration_id
        ):
            # A grant does not outlast a policy that now blocks the action.
            if not action_now_blocked(
                db_session,
                integration_id=scope.integration_id,
                action_id=scope.action_id,
                user_id=user_id,
                chat_session_id=chat_session_id,
            ):
                return None
            return _disabled_result(tool_name)
        if signed_out:
            # An anonymous user cannot decide.
            return ToolResult(
                content=f"The {tool_name} call needs the user's approval, and the "
                "user must sign in to Onyx to approve it, so it did not run.",
                is_error=True,
            )
        approval_id = create_approval_request__no_commit(
            db_session,
            chat_session_id=chat_session_id,
            chat_message_id=response_id,
            integration_id=scope.integration_id,
            action_id=scope.action_id,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            display_name=details.display_name,
            arguments=arguments if details.payload is None else details.payload,
        )
        db_session.commit()
    return PendingToolInput(
        request_id=str(approval_id),
        prompt=f"Allow {tool_name} to run?",
        mode=InputMode.EXECUTE,
        display_name=details.display_name,
        display_arguments=details.payload,
        can_approve_for_chat=can_approve_for_chat,
    )


def action_now_blocked(
    db_session: Session,
    *,
    integration_id: int | None,
    action_id: str,
    user_id: UUID,
    chat_session_id: UUID,
) -> bool:
    """True when the current policies block the action for the chat's agent,
    or its integration is gone or turned off. No policy covers a built-in
    action."""
    if is_builtin_action(integration_id, action_id):
        return False
    integration = (
        get_integration_by_id(integration_id, db_session)
        if integration_id is not None
        else None
    )
    if integration is None or not integration.enabled:
        return True
    return (
        resolve_chat_action_policies(
            db_session,
            integration=integration,
            action_keys=[action_id],
            user_id=user_id,
            chat_session_id=chat_session_id,
        )[action_id]
        is EffectivePolicy.BLOCKED
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
    None is a request whose row was deleted, such as with its chat;
    it and a request that ended undecided give the call no tool."""
    request_id = str(approval_id)
    if approval is None or approval.decision == ApprovalDecision.EXPIRED:
        return HumanToolAnswer(
            request_id=request_id,
            decision=InputDecision.DENY,
            result=ToolResult(
                content=UNAVAILABLE_CALL_MESSAGE,
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
    else:
        result = ToolResult(
            content=f"The user rejected this {name} call, so it did not run.",
            is_error=True,
            metadata=ToolApprovalDenial(outcome="rejected"),
        )
    return HumanToolAnswer(
        request_id=request_id, decision=InputDecision.DENY, result=result
    )


def ended_answer(approval: SavedToolApproval) -> HumanToolAnswer | None:
    """How a request ended for its call: the answer of its decision, or None
    when its call stopped waiting first (undecided, or EXPIRED)."""
    if approval.decision in (None, ApprovalDecision.EXPIRED):
        return None
    return tool_answer(approval.id, approval)
