from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db.models import TeamsBot


def insert_teams_bot(
    db_session: Session,
    name: str,
    enabled: bool,
    tenant_id: str,
    client_id: str,
    client_secret: str,
) -> TeamsBot:
    teams_bot = TeamsBot(
        name=name,
        enabled=enabled,
        tenant_id=tenant_id,
        client_id=client_id,
        client_secret=client_secret,
    )
    db_session.add(teams_bot)
    db_session.commit()

    return teams_bot


def update_teams_bot(
    db_session: Session,
    teams_bot_id: int,
    name: str | None = None,
    enabled: bool | None = None,
    tenant_id: str | None = None,
    client_id: str | None = None,
    client_secret: str | None = None,
) -> TeamsBot:
    teams_bot = fetch_teams_bot(db_session=db_session, teams_bot_id=teams_bot_id)
    if not teams_bot:
        raise ValueError(f"Teams bot with id {teams_bot_id} not found")

    if name is not None:
        teams_bot.name = name
    if enabled is not None:
        teams_bot.enabled = enabled
    if tenant_id is not None:
        teams_bot.tenant_id = tenant_id
    if client_id is not None:
        teams_bot.client_id = client_id
    if client_secret is not None:
        teams_bot.client_secret = client_secret

    db_session.commit()
    return teams_bot


def remove_teams_bot(
    db_session: Session,
    teams_bot_id: int,
) -> None:
    teams_bot = fetch_teams_bot(db_session=db_session, teams_bot_id=teams_bot_id)
    if not teams_bot:
        raise ValueError(f"Teams bot with id {teams_bot_id} not found")

    db_session.delete(teams_bot)
    db_session.commit()


def fetch_teams_bot(
    db_session: Session,
    teams_bot_id: int,
) -> TeamsBot | None:
    return db_session.get(TeamsBot, teams_bot_id)


def fetch_teams_bots(
    db_session: Session,
) -> Sequence[TeamsBot]:
    return db_session.scalars(select(TeamsBot)).all()


def fetch_teams_bot_tokens(
    db_session: Session,
    teams_bot_id: int,
) -> dict[str, str] | None:
    teams_bot = fetch_teams_bot(db_session=db_session, teams_bot_id=teams_bot_id)
    if not teams_bot:
        return None

    return {
        "tenant_id": teams_bot.tenant_id,
        "client_id": teams_bot.client_id,
        "client_secret": teams_bot.client_secret,
    } 