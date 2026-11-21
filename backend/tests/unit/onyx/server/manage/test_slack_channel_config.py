from unittest.mock import MagicMock

import pytest
from sqlalchemy.orm import Session

from onyx.server.manage.models import (
    SlackBotResponseType,
    SlackChannelConfigCreationRequest,
)
from onyx.server.manage.slack_bot import _form_channel_config


def test_form_channel_config_preserves_remove_feedback_buttons(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "onyx.server.manage.slack_bot.validate_channel_name",
        lambda **_: "general",
    )
    request = SlackChannelConfigCreationRequest(
        slack_bot_id=1,
        channel_name="general",
        response_type=SlackBotResponseType.CITATIONS,
        remove_feedback_buttons=True,
    )

    channel_config = _form_channel_config(
        db_session=MagicMock(spec=Session),
        slack_channel_config_creation_request=request,
        current_slack_channel_config_id=None,
    )

    assert channel_config["remove_feedback_buttons"] is True


def test_form_channel_config_defaults_remove_feedback_buttons_to_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "onyx.server.manage.slack_bot.validate_channel_name",
        lambda **_: "general",
    )
    request = SlackChannelConfigCreationRequest(
        slack_bot_id=1,
        channel_name="general",
        response_type=SlackBotResponseType.CITATIONS,
    )

    channel_config = _form_channel_config(
        db_session=MagicMock(spec=Session),
        slack_channel_config_creation_request=request,
        current_slack_channel_config_id=None,
    )

    assert channel_config["remove_feedback_buttons"] is False
