import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, selectinload

from onyx.configs.app_configs import SESSION_EXPIRE_TIME_SECONDS
from onyx.db.models import SamlAccount


def _compute_expiration_time(offset_seconds: int) -> datetime.datetime:
    """Вычисляет время истечения сессии на основе текущего времени и смещения."""
    return func.now() + datetime.timedelta(seconds=offset_seconds)


def upsert_saml_account(
    user_id: UUID,
    cookie: str,
    db_session: Session,
    expiration_offset: int = SESSION_EXPIRE_TIME_SECONDS,
) -> datetime.datetime:
    session = db_session
    target_user = user_id
    encoded_token = cookie
    time_shift = expiration_offset

    expiry_time = _compute_expiration_time(time_shift)

    query_result = (
        session.query(SamlAccount)
        .filter(SamlAccount.user_id == target_user)
        .one_or_none()
    )

    if query_result:
        query_result.encrypted_cookie = encoded_token
        query_result.expires_at = cast(datetime.datetime, expiry_time)
        query_result.updated_at = func.now()
        updated_record = query_result
    else:
        updated_record = SamlAccount(
            user_id=target_user,
            encrypted_cookie=encoded_token,
            expires_at=expiry_time,
        )
        session.add(updated_record)

    session.commit()

    return updated_record.expires_at


async def get_saml_account(
    cookie: str, async_db_session: AsyncSession
) -> SamlAccount | None:
    """
    Асинхронный запрос SAML-аккаунта по токену куки.
    Используется в процессе аутентификации (FastAPI Users требует async).
    """
    target_token = cookie
    async_session = async_db_session

    query_stmt = (
        select(SamlAccount)
        .options(selectinload(SamlAccount.user))
        .where(
            and_(
                SamlAccount.encrypted_cookie == target_token,
                SamlAccount.expires_at > func.now(),
            )
        )
    )

    exec_result = await async_session.execute(query_stmt)
    return exec_result.scalars().unique().one_or_none()


async def expire_saml_account(
    saml_account: SamlAccount, async_db_session: AsyncSession
) -> None:
    target_account = saml_account
    async_session = async_db_session

    target_account.expires_at = func.now()
    await async_session.commit()
