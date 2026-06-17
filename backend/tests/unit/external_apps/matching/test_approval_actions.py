from onyx.db.enums import EndpointPolicy
from onyx.external_apps.matching.engine import actions_requiring_approval
from onyx.external_apps.matching.engine import MatchedAction


def _action(action_type: str, policy: EndpointPolicy) -> MatchedAction:
    return MatchedAction(
        action_type=action_type,
        display_name=action_type,
        description="description",
        policy=policy,
    )


def test_actions_requiring_approval_from_live_matched_actions() -> None:
    actions = [
        _action("slack.messages.write", EndpointPolicy.ASK),
        _action("slack.channels.read", EndpointPolicy.ALWAYS),
        _action("slack.messages.write", EndpointPolicy.ASK),
    ]

    assert actions_requiring_approval(actions) == ["slack.messages.write"]


def test_actions_requiring_approval_from_persisted_action_dicts() -> None:
    actions = [
        {"action_type": "slack.files.upload", "policy": "ASK"},
        {"action_type": "slack.channels.read", "policy": "ALWAYS"},
        {"action_type": "slack.messages.write", "policy": EndpointPolicy.ASK},
        {"action_type": "slack.invalid", "policy": "UNKNOWN"},
        {"policy": "ASK"},
    ]

    assert actions_requiring_approval(actions) == [
        "slack.files.upload",
        "slack.messages.write",
    ]
