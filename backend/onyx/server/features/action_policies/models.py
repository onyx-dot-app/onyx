from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict

from onyx.db.enums import ApprovalDecidedVia, ApprovalDecision


class ApprovalChoice(StrEnum):
    APPROVE_ONCE = "approve_once"
    # Also approves later requests of the action in the same session.
    APPROVE_SESSION = "approve_session"
    # Only for an app request of a command in a chat's VM: also approves the
    # command's later requests of the action, until the command exits.
    APPROVE_COMMAND = "approve_command"
    REJECT = "reject"

    @property
    def decision(
        self,
    ) -> Literal[ApprovalDecision.APPROVED, ApprovalDecision.REJECTED]:
        return (
            ApprovalDecision.REJECTED
            if self is ApprovalChoice.REJECT
            else ApprovalDecision.APPROVED
        )

    def outcome(
        self, *, blocked: bool
    ) -> tuple[
        Literal[ApprovalDecision.APPROVED, ApprovalDecision.REJECTED],
        ApprovalDecidedVia,
    ]:
        """The decision that this choice saves on a chat request. An approval
        of an action that the current policies block is a rejection by the
        policy."""
        if self is ApprovalChoice.REJECT:
            return ApprovalDecision.REJECTED, ApprovalDecidedVia.USER
        if blocked:
            return ApprovalDecision.REJECTED, ApprovalDecidedVia.POLICY
        if self is ApprovalChoice.APPROVE_SESSION:
            return ApprovalDecision.APPROVED, ApprovalDecidedVia.SESSION_GRANT
        if self is ApprovalChoice.APPROVE_COMMAND:
            return ApprovalDecision.APPROVED, ApprovalDecidedVia.COMMAND_GRANT
        return ApprovalDecision.APPROVED, ApprovalDecidedVia.USER

    def upgrades(
        self, decision: ApprovalDecision | None, decided_via: ApprovalDecidedVia | None
    ) -> bool:
        """This choice turns the user's single approval into a session grant."""
        return (
            self is ApprovalChoice.APPROVE_SESSION
            and decision == ApprovalDecision.APPROVED
            and decided_via == ApprovalDecidedVia.USER
        )

    def saved_answer(
        self, decision: ApprovalDecision | None, decided_via: ApprovalDecidedVia | None
    ) -> (
        tuple[
            Literal[ApprovalDecision.APPROVED, ApprovalDecision.REJECTED],
            ApprovalDecidedVia,
        ]
        | None
    ):
        """The saved decision when it answers this choice, so a retry returns
        it, also after the policies change: an approval answers each approve
        choice, and a rejection by the policy answers each choice. None, a
        conflict, for a request that still waits, ended undecided, or has a
        different decision."""
        if decided_via is None:
            return None
        expected = (
            ApprovalDecision.REJECTED
            if self is ApprovalChoice.REJECT or decided_via == ApprovalDecidedVia.POLICY
            else ApprovalDecision.APPROVED
        )
        return (expected, decided_via) if decision == expected else None


class DecisionBody(BaseModel):
    """The user's decision on an action that waits for approval, in Craft or
    in chat."""

    model_config = ConfigDict(extra="forbid")
    decision: ApprovalChoice
