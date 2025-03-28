from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.schema import Column

from danswer.db.models import Persona
from danswer.db.models import User
from danswer.db.models import UserSlackPersona


def list_users(db_session: Session, q: str = "") -> Sequence[User]:
    """List all users. No pagination as of now, as the # of users
    is assumed to be relatively small (<< 1 million)"""
    query = db_session.query(User)
    if q:
        query = query.filter(Column("email").ilike("%{}%".format(q)))
    return query.all()


def get_user_by_email(email: str, db_session: Session) -> User | None:
    user = db_session.query(User).filter(User.email == email).first()  # type: ignore

    return user


def fetch_user_slack_persona(
    db_session: Session, sender_id: str
) -> UserSlackPersona | None:
    return db_session.scalar(
        select(UserSlackPersona).where(UserSlackPersona.sender_id == sender_id)
    )


def add_user_slack_persona(
    db_session: Session, sender_id: str, persona: Persona
) -> None:
    user_persona = UserSlackPersona(
        sender_id=sender_id, persona_id=persona.id, persona=persona
    )
    db_session.add(user_persona)
    db_session.commit()


def add_slack_persona_for_user(
    db_session: Session, persona: Persona, user_slack_persona: UserSlackPersona
) -> None:
    user_slack_persona.persona_id = persona.id
    user_slack_persona.persona = persona

    db_session.commit()
