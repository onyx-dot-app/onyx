from collections.abc import Sequence
from uuid import UUID

from fastapi_users.password import PasswordHelper
from sqlalchemy import select
from sqlalchemy.orm import Session

from danswer.auth.schemas import UserRole
from danswer.db.models import User


def list_users(
    db_session: Session, email_filter_string: str = "", user: User | None = None
) -> Sequence[User]:
    """List all users. No pagination as of now, as the # of users
    is assumed to be relatively small (<< 1 million)"""
    stmt = select(User)

    if email_filter_string:
        stmt = stmt.where(User.email.ilike(f"%{email_filter_string}%"))  # type: ignore

    return db_session.scalars(stmt).unique().all()


def get_user_by_email(email: str, db_session: Session) -> User | None:
    user = db_session.query(User).filter(User.email == email).first()  # type: ignore

    return user


def fetch_user_by_id(db_session: Session, user_id: UUID) -> User | None:
    user = db_session.query(User).filter(User.id == user_id).first()  # type: ignore

    return user


def add_non_web_user_if_not_exists(email: str, db_session: Session) -> User:
    user = get_user_by_email(email, db_session)
    if user is not None:
        return user

    fastapi_users_pw_helper = PasswordHelper()
    password = fastapi_users_pw_helper.generate()
    hashed_pass = fastapi_users_pw_helper.hash(password)
    user = User(
        email=email,
        hashed_password=hashed_pass,
        has_web_login=False,
        role=UserRole.BASIC,
    )
    db_session.add(user)
    db_session.commit()
    return user
