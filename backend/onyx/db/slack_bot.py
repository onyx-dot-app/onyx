from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db.models import SlackBot


def insert_slack_bot(
    db_session: Session,
    name: str,
    enabled: bool,
    bot_token: str,
    app_token: str,
    user_token: str | None = None,
) -> SlackBot:
    slack_bot = SlackBot(
        name=name,
        enabled=enabled,
        bot_token=bot_token,
        app_token=app_token,
        user_token=user_token,
    )
    db_session.add(slack_bot)
    db_session.commit()

    return slack_bot


def update_slack_bot(
    db_session: Session,
    slack_bot_id: int,
    name: str,
    enabled: bool,
    bot_token: str,
    app_token: str,
    user_token: str | None = None,
) -> SlackBot:
    slack_bot = db_session.scalar(select(SlackBot).where(SlackBot.id == slack_bot_id))
    if slack_bot is None:
        raise ValueError(f"Unable to find Slack Bot with ID {slack_bot_id}")

    # update the app
    slack_bot.name = name
    slack_bot.enabled = enabled
    slack_bot.bot_token = bot_token
    slack_bot.app_token = app_token
    slack_bot.user_token = user_token

    db_session.commit()

    return slack_bot


def fetch_slack_bot(
    db_session: Session,
    slack_bot_id: int,
) -> SlackBot:
    slack_bot = db_session.scalar(select(SlackBot).where(SlackBot.id == slack_bot_id))
    if slack_bot is None:
        raise ValueError(f"Unable to find Slack Bot with ID {slack_bot_id}")

    return slack_bot


def remove_slack_bot(
    db_session: Session,
    slack_bot_id: int,
) -> None:
    slack_bot = fetch_slack_bot(
        db_session=db_session,
        slack_bot_id=slack_bot_id,
    )

    db_session.delete(slack_bot)
    db_session.commit()


def fetch_slack_bots(db_session: Session) -> Sequence[SlackBot]:
    return db_session.scalars(select(SlackBot)).all()
