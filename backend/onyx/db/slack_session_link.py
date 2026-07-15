from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from onyx.db.models import SlackSessionLink


def get_session_id_for_slack_thread(
    db_session: Session,
    slack_team_id: str,
    channel_id: str,
    thread_ts: str,
) -> UUID | None:
    link = db_session.scalar(
        select(SlackSessionLink).where(
            SlackSessionLink.slack_team_id == slack_team_id,
            SlackSessionLink.channel_id == channel_id,
            SlackSessionLink.thread_ts == thread_ts,
        )
    )
    return link.build_session_id if link else None


def insert_slack_session_link(
    db_session: Session,
    slack_team_id: str,
    channel_id: str,
    thread_ts: str,
    build_session_id: UUID,
) -> SlackSessionLink:
    """Raises IntegrityError on a race between concurrent inserts for the same
    thread; callers should catch it and re-fetch the winning link."""
    link = SlackSessionLink(
        slack_team_id=slack_team_id,
        channel_id=channel_id,
        thread_ts=thread_ts,
        build_session_id=build_session_id,
    )
    db_session.add(link)
    try:
        db_session.commit()
    except IntegrityError:
        db_session.rollback()
        raise
    return link


def get_link_for_session(
    db_session: Session,
    build_session_id: UUID,
) -> SlackSessionLink | None:
    return db_session.scalar(
        select(SlackSessionLink).where(
            SlackSessionLink.build_session_id == build_session_id
        )
    )
