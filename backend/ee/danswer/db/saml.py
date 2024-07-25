import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import and_
from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy.orm import Session

from danswer.configs.app_configs import SESSION_EXPIRE_TIME_SECONDS
from danswer.db.models import SamlAccount
from danswer.db.models import User


def upsert_saml_account(
    user_id: UUID,
    cookie: str,
    db_session: Session,
    expiration_offset: int = SESSION_EXPIRE_TIME_SECONDS,
) -> datetime.datetime:
    expires_at = func.now() + datetime.timedelta(seconds=expiration_offset)

    existing_saml_acc = (
        db_session.query(SamlAccount)
        .filter(SamlAccount.user_id == user_id)
        .one_or_none()
    )

    if existing_saml_acc:
        existing_saml_acc.encrypted_cookie = cookie
        existing_saml_acc.expires_at = cast(datetime.datetime, expires_at)
        existing_saml_acc.updated_at = func.now()
        saml_acc = existing_saml_acc
    else:
        saml_acc = SamlAccount(
            user_id=user_id,
            encrypted_cookie=cookie,
            expires_at=expires_at,
        )
        db_session.add(saml_acc)

    db_session.commit()

    return saml_acc.expires_at


def get_saml_account(cookie: str, db_session: Session) -> SamlAccount | None:
    stmt = (
        select(SamlAccount)
        .join(User, User.id == SamlAccount.user_id)  # type: ignore
        .where(
            and_(
                SamlAccount.encrypted_cookie == cookie,
                SamlAccount.expires_at > func.now(),
            )
        )
    )

    result = db_session.execute(stmt)
    return result.scalar_one_or_none()


def expire_saml_account(saml_account: SamlAccount, db_session: Session) -> None:
    saml_account.expires_at = func.now()
    db_session.commit()
