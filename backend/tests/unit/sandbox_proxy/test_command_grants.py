"""The foreground mark and the "approve for this command" grants of a chat
VM command (`sandbox_proxy/approval_cache.py`)."""

from uuid import UUID, uuid4

from onyx.db.enums import ActionPolicy
from onyx.external_apps.matching.engine import MatchedAction
from onyx.sandbox_proxy import approval_cache
from tests.unit.fakes import FakeCache


def _action(action_type: str, policy: ActionPolicy) -> MatchedAction:
    return MatchedAction(
        action_type=action_type,
        display_name=action_type,
        description="",
        policy=policy,
    )


def test_a_grant_covers_its_actions_of_its_integration_and_chat_only() -> None:
    cache = FakeCache()
    command, other_command = uuid4(), uuid4()
    chat, other_chat = uuid4(), uuid4()

    approval_cache.grant_command_actions(command, chat, 7, ["issues.create"], cache)

    def covers(
        command_id: UUID, chat_id: UUID, integration: int, actions: list[str]
    ) -> bool:
        return approval_cache.command_grants_cover(
            command_id, chat_id, integration, actions, cache
        )

    assert covers(command, chat, 7, ["issues.create"])
    assert not covers(command, chat, 7, ["issues.create", "issues.delete"])
    assert not covers(command, chat, 8, ["issues.create"])
    assert not covers(other_command, chat, 7, ["issues.create"])
    assert not covers(command, other_chat, 7, ["issues.create"])
    assert not covers(command, chat, 7, [])


def test_dropping_the_grants_of_a_command_keeps_other_commands() -> None:
    cache = FakeCache()
    command, other_command, chat = uuid4(), uuid4(), uuid4()
    approval_cache.grant_command_actions(command, chat, 7, ["issues.create"], cache)
    approval_cache.grant_command_actions(
        other_command, chat, 7, ["issues.create"], cache
    )

    approval_cache.drop_command_grants(command, cache)

    assert not approval_cache.command_grants_cover(
        command, chat, 7, ["issues.create"], cache
    )
    assert approval_cache.command_grants_cover(
        other_command, chat, 7, ["issues.create"], cache
    )


def test_a_grant_covers_ask_actions_and_never_one_that_always_asks() -> None:
    assert approval_cache.command_grant_actions(
        [
            _action("issues.create", ActionPolicy.ASK),
            _action("issues.list", ActionPolicy.ALWAYS),
        ]
    ) == ["issues.create"]
    assert (
        approval_cache.command_grant_actions(
            [
                _action("issues.create", ActionPolicy.ASK),
                _action("unspecified", ActionPolicy.ASK),
            ]
        )
        == []
    )


def test_the_foreground_mark_names_the_chat() -> None:
    cache = FakeCache()
    command, chat, other_chat = uuid4(), uuid4(), uuid4()
    assert not approval_cache.command_in_foreground(command, chat, cache)

    approval_cache.mark_command_foreground(command, chat, cache)

    assert approval_cache.command_in_foreground(command, chat, cache)
    assert not approval_cache.command_in_foreground(command, other_chat, cache)
    approval_cache.clear_command_foreground(command, cache)
    assert not approval_cache.command_in_foreground(command, chat, cache)
