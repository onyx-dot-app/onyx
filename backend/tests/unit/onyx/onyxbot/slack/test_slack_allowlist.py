from unittest.mock import MagicMock, patch

import pytest

from onyx.onyxbot.slack.handlers.handle_message import _resolve_allowlist_user_ids
from onyx.server.manage.slack_bot import _form_channel_config


def test_resolve_allowlist_empty_or_blank_returns_none():
    client = MagicMock()

    # Empty list
    resolved, missing = _resolve_allowlist_user_ids(
        {"respond_member_group_list": []}, client
    )
    assert resolved is None
    assert missing == []

    # List of blank / whitespace strings
    resolved, missing = _resolve_allowlist_user_ids(
        {"respond_member_group_list": ["", "  ", "\t"]}, client
    )
    assert resolved is None
    assert missing == []


def test_resolve_allowlist_strips_valid_entries():
    client = MagicMock()
    mock_user_resp = MagicMock()
    mock_user_resp.data = {"ok": True, "user": {"id": "U12345"}}
    client.users_lookupByEmail.return_value = mock_user_resp

    resolved, missing = _resolve_allowlist_user_ids(
        {"respond_member_group_list": ["  user@example.com  ", ""]},
        client,
    )
    assert resolved == ["U12345"]
    assert missing == []


def _channel_config_request(
    *, is_ephemeral: bool, respond_member_group_list: list[str]
) -> MagicMock:
    request = MagicMock()
    request.channel_name = "general"
    request.respond_tag_only = None
    request.respond_member_group_list = respond_member_group_list
    request.answer_filters = []
    request.follow_up_tags = None
    request.is_ephemeral = is_ephemeral
    return request


# create and patch both build the channel config through _form_channel_config.
@pytest.mark.parametrize("current_slack_channel_config_id", [None, 1])
def test_form_channel_config_ephemeral_with_blank_allowlist_is_accepted(
    current_slack_channel_config_id: int | None,
) -> None:
    request = _channel_config_request(
        is_ephemeral=True, respond_member_group_list=["  ", ""]
    )

    with patch(
        "onyx.server.manage.slack_bot.validate_channel_name", return_value="general"
    ):
        channel_config = _form_channel_config(
            db_session=MagicMock(),
            slack_channel_config_creation_request=request,
            current_slack_channel_config_id=current_slack_channel_config_id,
        )

    assert channel_config["is_ephemeral"] is True
    assert "respond_member_group_list" not in channel_config


def test_form_channel_config_ephemeral_with_allowlist_is_rejected() -> None:
    request = _channel_config_request(
        is_ephemeral=True, respond_member_group_list=[" alice@example.com "]
    )

    with (
        patch(
            "onyx.server.manage.slack_bot.validate_channel_name",
            return_value="general",
        ),
        pytest.raises(ValueError),
    ):
        _form_channel_config(
            db_session=MagicMock(),
            slack_channel_config_creation_request=request,
            current_slack_channel_config_id=None,
        )
