"""Tests that SlackBot CRUD operations return properly typed SensitiveValue fields.

Regression test for the bug where insert_slack_bot/update_slack_bot returned
objects with raw string tokens instead of SensitiveValue wrappers, causing
'str object has no attribute get_value' errors in SlackBot.from_model().
"""

from uuid import uuid4

from sqlalchemy.orm import Session

from onyx.db.slack_bot import insert_slack_bot
from onyx.db.slack_bot import update_slack_bot
from onyx.server.manage.models import SlackBot
from onyx.utils.sensitive import SensitiveValue


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:8]}"


def test_insert_slack_bot_returns_sensitive_values(db_session: Session) -> None:
    slack_bot = insert_slack_bot(
        db_session=db_session,
        name=_unique("test-bot-insert"),
        enabled=True,
        bot_token=_unique("xoxb-insert"),
        app_token=_unique("xapp-insert"),
        user_token=_unique("xoxp-insert"),
    )

    assert isinstance(slack_bot.bot_token, SensitiveValue)
    assert isinstance(slack_bot.app_token, SensitiveValue)
    assert isinstance(slack_bot.user_token, SensitiveValue)

    # Verify from_model works without error
    pydantic_bot = SlackBot.from_model(slack_bot)
    assert pydantic_bot.bot_token  # masked, but not empty
    assert pydantic_bot.app_token


def test_update_slack_bot_returns_sensitive_values(db_session: Session) -> None:
    slack_bot = insert_slack_bot(
        db_session=db_session,
        name=_unique("test-bot-update"),
        enabled=True,
        bot_token=_unique("xoxb-update"),
        app_token=_unique("xapp-update"),
    )

    updated = update_slack_bot(
        db_session=db_session,
        slack_bot_id=slack_bot.id,
        name=_unique("test-bot-updated"),
        enabled=False,
        bot_token=_unique("xoxb-update-new"),
        app_token=_unique("xapp-update-new"),
        user_token=_unique("xoxp-update-new"),
    )

    assert isinstance(updated.bot_token, SensitiveValue)
    assert isinstance(updated.app_token, SensitiveValue)
    assert isinstance(updated.user_token, SensitiveValue)

    # Verify from_model works without error
    pydantic_bot = SlackBot.from_model(updated)
    assert pydantic_bot.bot_token
    assert pydantic_bot.app_token
    assert pydantic_bot.user_token is not None
