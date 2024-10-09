from collections.abc import Sequence
from uuid import UUID

from fastapi_users.password import PasswordHelper
from sqlalchemy import func
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


def get_users_by_emails(
    db_session: Session, emails: list[str]
) -> tuple[list[User], list[str]]:
    # Use distinct to avoid duplicates
    stmt = select(User).filter(User.email.in_(emails))  # type: ignore
    found_users = list(db_session.scalars(stmt).unique().all())  # Convert to list
    found_users_emails = [user.email for user in found_users]
    missing_user_emails = [email for email in emails if email not in found_users_emails]
    return found_users, missing_user_emails


def get_user_by_email(email: str, db_session: Session) -> User | None:
    user = (
        db_session.query(User)
        .filter(func.lower(User.email) == func.lower(email))
        .first()
    )

    return user


def fetch_user_by_id(db_session: Session, user_id: UUID) -> User | None:
    user = db_session.query(User).filter(User.id == user_id).first()  # type: ignore

    return user


def _generate_non_web_user(email: str) -> User:
    fastapi_users_pw_helper = PasswordHelper()
    password = fastapi_users_pw_helper.generate()
    hashed_pass = fastapi_users_pw_helper.hash(password)
    return User(
        email=email,
        hashed_password=hashed_pass,
        has_web_login=False,
        role=UserRole.BASIC,
    )


def add_non_web_user_if_not_exists(db_session: Session, email: str) -> User:
    user = get_user_by_email(email, db_session)
    if user is not None:
        return user

    user = _generate_non_web_user(email=email)
    db_session.add(user)
    db_session.commit()
    return user


def add_non_web_user_if_not_exists__no_commit(db_session: Session, email: str) -> User:
    user = get_user_by_email(email, db_session)
    if user is not None:
        return user

    user = _generate_non_web_user(email=email)
    db_session.add(user)
    db_session.flush()  # generate id
    return user


def batch_add_non_web_user_if_not_exists__no_commit(
    db_session: Session, emails: list[str]
) -> list[User]:
    found_users, missing_user_emails = get_users_by_emails(db_session, emails)

    new_users: list[User] = []
    for email in missing_user_emails:
        new_users.append(_generate_non_web_user(email=email))

    db_session.add_all(new_users)
    db_session.flush()  # generate ids

    return found_users + new_users
