from collections.abc import Sequence

from sqlalchemy.orm import Session
from sqlalchemy.schema import Column

from danswer.db.models import User


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
