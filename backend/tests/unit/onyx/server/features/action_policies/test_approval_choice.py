import pytest

from onyx.db.enums import ApprovalDecidedVia, ApprovalDecision
from onyx.integrations.models import EffectivePolicy
from onyx.integrations.policy import ApprovalRecheck, recheck_approval
from onyx.server.features.action_policies.models import ApprovalChoice

APPROVED = ApprovalDecision.APPROVED
REJECTED = ApprovalDecision.REJECTED


@pytest.mark.parametrize(
    ("choice", "blocked", "expected"),
    [
        (ApprovalChoice.APPROVE_ONCE, False, (APPROVED, ApprovalDecidedVia.USER)),
        (
            ApprovalChoice.APPROVE_SESSION,
            False,
            (APPROVED, ApprovalDecidedVia.SESSION_GRANT),
        ),
        (
            ApprovalChoice.APPROVE_COMMAND,
            False,
            (APPROVED, ApprovalDecidedVia.COMMAND_GRANT),
        ),
        (ApprovalChoice.REJECT, False, (REJECTED, ApprovalDecidedVia.USER)),
        (ApprovalChoice.APPROVE_ONCE, True, (REJECTED, ApprovalDecidedVia.POLICY)),
        (ApprovalChoice.APPROVE_SESSION, True, (REJECTED, ApprovalDecidedVia.POLICY)),
        (ApprovalChoice.APPROVE_COMMAND, True, (REJECTED, ApprovalDecidedVia.POLICY)),
        (ApprovalChoice.REJECT, True, (REJECTED, ApprovalDecidedVia.USER)),
    ],
)
def test_a_choice_saves_one_decision(
    choice: ApprovalChoice,
    blocked: bool,
    expected: tuple[ApprovalDecision, ApprovalDecidedVia],
) -> None:
    assert choice.outcome(blocked=blocked) == expected


@pytest.mark.parametrize(
    ("choice", "decision", "decided_via", "answers"),
    [
        (ApprovalChoice.APPROVE_ONCE, APPROVED, ApprovalDecidedVia.SESSION_GRANT, True),
        (ApprovalChoice.APPROVE_COMMAND, APPROVED, ApprovalDecidedVia.USER, True),
        (ApprovalChoice.REJECT, REJECTED, ApprovalDecidedVia.USER, True),
        (ApprovalChoice.APPROVE_SESSION, REJECTED, ApprovalDecidedVia.POLICY, True),
        (ApprovalChoice.REJECT, REJECTED, ApprovalDecidedVia.POLICY, True),
        (ApprovalChoice.REJECT, APPROVED, ApprovalDecidedVia.USER, False),
        (ApprovalChoice.APPROVE_ONCE, REJECTED, ApprovalDecidedVia.USER, False),
        (ApprovalChoice.APPROVE_ONCE, None, None, False),
        (
            ApprovalChoice.REJECT,
            ApprovalDecision.EXPIRED,
            ApprovalDecidedVia.USER,
            False,
        ),
    ],
)
def test_a_repeated_choice_gets_the_saved_decision_or_a_conflict(
    choice: ApprovalChoice,
    decision: ApprovalDecision | None,
    decided_via: ApprovalDecidedVia | None,
    answers: bool,
) -> None:
    answer = choice.saved_answer(decision, decided_via)
    assert answer == ((decision, decided_via) if answers else None)


def test_only_a_session_approval_upgrades_a_single_user_approval() -> None:
    assert ApprovalChoice.APPROVE_SESSION.upgrades(APPROVED, ApprovalDecidedVia.USER)
    assert not ApprovalChoice.APPROVE_ONCE.upgrades(APPROVED, ApprovalDecidedVia.USER)
    assert not ApprovalChoice.APPROVE_SESSION.upgrades(
        REJECTED, ApprovalDecidedVia.USER
    )
    assert not ApprovalChoice.APPROVE_SESSION.upgrades(
        APPROVED, ApprovalDecidedVia.SESSION_GRANT
    )


@pytest.mark.parametrize(
    ("policies", "expected"),
    [
        (None, ApprovalRecheck.BLOCKED),
        (
            {"a": EffectivePolicy.ASK, "b": EffectivePolicy.BLOCKED},
            ApprovalRecheck.BLOCKED,
        ),
        (
            {"a": EffectivePolicy.ASK, "b": EffectivePolicy.ASK},
            ApprovalRecheck.ASKS_MORE,
        ),
        (
            {"a": EffectivePolicy.ASK, "b": EffectivePolicy.ALLOW},
            ApprovalRecheck.UNCHANGED,
        ),
        ({"a": EffectivePolicy.ALLOW}, ApprovalRecheck.UNCHANGED),
    ],
)
def test_the_recheck_finds_a_blocked_or_a_new_ask_action(
    policies: dict[str, EffectivePolicy] | None, expected: ApprovalRecheck
) -> None:
    assert recheck_approval(policies, ["a", "b"], asked=["a"]) is expected
