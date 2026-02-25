"""Database operations for Personal Access Tokens."""

import asyncio
from datetime import datetime
from datetime import timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.orm import Session

from onyx.auth.pat import build_displayable_pat
from onyx.auth.pat import calculate_expiration
from onyx.auth.pat import generate_pat
from onyx.auth.pat import hash_pat
from onyx.db.engine.async_sql_engine import get_async_session_context_manager
from onyx.db.models import PersonalAccessToken
from onyx.db.models import User
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id


logger = setup_logger()


async def fetch_user_for_pat(
    hashed_token: str, async_db_session: AsyncSession
) -> User | None:
    """Fetch user associated with PAT. Returns None if invalid, expired, or inactive user.

    NOTE: This is async since it's used during auth (which is necessarily async due to FastAPI Users).
    NOTE: Expired includes both naturally expired and user-revoked tokens (revocation sets expires_at=NOW()).

    Uses select(User) as primary entity so that joined-eager relationships (e.g. oauth_accounts)
    are loaded correctly — matching the pattern in fetch_user_for_api_key.
    """
    now = datetime.now(timezone.utc)

    user = await async_db_session.scalar(
        select(User)
        .join(PersonalAccessToken, PersonalAccessToken.user_id == User.id)
        .where(PersonalAccessToken.hashed_token == hashed_token)
        .where(User.is_active)  # type: ignore
        .where(
            (PersonalAccessToken.expires_at.is_(None))
            | (PersonalAccessToken.expires_at > now)
        )
        .options(selectinload(User.memories))
    )
    if not user:
        return None

    _schedule_pat_last_used_update(hashed_token, now)
    return user


def _schedule_pat_last_used_update(hashed_token: str, now: datetime) -> None:
    """Fire-and-forget update of last_used_at, throttled to 5-minute granularity."""

    async def _update() -> None:
        try:
            tenant_id = get_current_tenant_id()
            async with get_async_session_context_manager(tenant_id) as session:
                pat = await session.scalar(
                    select(PersonalAccessToken).where(
                        PersonalAccessToken.hashed_token == hashed_token
                    )
                )
                if not pat:
                    return
                if (
                    pat.last_used_at is not None
                    and (now - pat.last_used_at).total_seconds() <= 300
                ):
                    return
                await session.execute(
                    update(PersonalAccessToken)
                    .where(PersonalAccessToken.hashed_token == hashed_token)
                    .values(last_used_at=now)
                )
                await session.commit()
        except Exception as e:
            logger.warning(f"Failed to update last_used_at for PAT: {e}")

    asyncio.create_task(_update())


def create_pat(
    db_session: Session,
    user_id: UUID,
    name: str,
    expiration_days: int | None,
) -> tuple[PersonalAccessToken, str]:
    """Create new PAT. Returns (db_record, raw_token).

    Raises ValueError if user is inactive or not found.
    """
    user = db_session.scalar(select(User).where(User.id == user_id))  # type: ignore
    if not user or not user.is_active:
        raise ValueError("Cannot create PAT for inactive or non-existent user")

    tenant_id = get_current_tenant_id()
    raw_token = generate_pat(tenant_id)

    pat = PersonalAccessToken(
        name=name,
        hashed_token=hash_pat(raw_token),
        token_display=build_displayable_pat(raw_token),
        user_id=user_id,
        expires_at=calculate_expiration(expiration_days),
    )
    db_session.add(pat)
    db_session.commit()

    return pat, raw_token


def list_user_pats(db_session: Session, user_id: UUID) -> list[PersonalAccessToken]:
    """List all active (non-expired) PATs for a user."""
    return list(
        db_session.scalars(
            select(PersonalAccessToken)
            .where(PersonalAccessToken.user_id == user_id)
            .where(
                (PersonalAccessToken.expires_at.is_(None))
                | (PersonalAccessToken.expires_at > datetime.now(timezone.utc))
            )
            .order_by(PersonalAccessToken.created_at.desc())
        ).all()
    )


def revoke_pat(db_session: Session, pat_id: int, user_id: UUID) -> bool:
    """Revoke PAT by setting expires_at=NOW() for immediate expiry.

    Returns True if revoked, False if not found, not owned by user, or already expired.
    """
    now = datetime.now(timezone.utc)
    pat = db_session.scalar(
        select(PersonalAccessToken)
        .where(PersonalAccessToken.id == pat_id)
        .where(PersonalAccessToken.user_id == user_id)
        .where(
            (PersonalAccessToken.expires_at.is_(None))
            | (PersonalAccessToken.expires_at > now)
        )  # Only revoke active (non-expired) tokens
    )
    if not pat:
        return False

    # Revoke by setting expires_at to NOW() and marking as revoked for audit trail
    pat.expires_at = now
    pat.is_revoked = True
    db_session.commit()
    return True
