from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class ApprovalChoice(StrEnum):
    APPROVE_ONCE = "approve_once"
    # Also approves later requests of the action in the same session.
    APPROVE_SESSION = "approve_session"
    # Only for an app request of a command in a chat's VM: also approves the
    # command's later requests of the action, until the command exits.
    APPROVE_COMMAND = "approve_command"
    REJECT = "reject"


class DecisionBody(BaseModel):
    """The user's decision on an action that waits for approval, in Craft or
    in chat."""

    model_config = ConfigDict(extra="forbid")
    decision: ApprovalChoice
