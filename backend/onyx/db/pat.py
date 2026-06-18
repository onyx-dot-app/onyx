"""Database operations for Personal Access Tokens."""

import asyncio
from datetime import datetime
from datetime import timezone
from typing import NamedTuple
from uuid import UUID

from sqlalchemy import select
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import contains_eager
from sqlalchemy.orm import Session

from onyx.auth.pat import build_displayable_pat
from onyx.auth.pat import calculate_expiration
from onyx.auth.pat import generate_pat
from onyx.auth.pat import hash_pat
from onyx.db.engine.async_sql_engine import get_async_session_context_manager
from onyx.db.enums import PatType
from onyx.db.enums import Permission
from onyx.db.models import PersonalAccessToken
from onyx.db.models import User
from onyx.db.permissions import parse_permission_values
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()


class PatAuthResult(NamedTuple):
    """A PAT resolved to its user and scopes (scopes None = unrestricted)."""

    user: User
    scopes: list[Permission] | None


async def resolve_pat(
    hashed_token: str, async_db_session: AsyncSession
) -> PatAuthResult | None:
    """Resolve a PAT to its user and scopes. Returns None if invalid, expired, or inactive user.

    NOTE: This is async since it's used during auth (which is necessarily async due to FastAPI Users).
    NOTE: Expired includes both naturally expired and user-revoked tokens (revocation sets expires_at=NOW()).

    Loads the PAT with its user eagerly via contains_eager so the user's own
    joined-eager relationships (e.g. oauth_accounts) populate, and .unique()
    collapses the duplicate rows that joined collection produces.
    """
    now = datetime.now(timezone.utc)

    pat = (
        (
            await async_db_session.execute(
                select(PersonalAccessToken)
                .join(PersonalAccessToken.user)
                .options(contains_eager(PersonalAccessToken.user))
                .where(PersonalAccessToken.hashed_token == hashed_token)
                .where(User.is_active)  # ty: ignore[invalid-argument-type]
                .where(
                    (PersonalAccessToken.expires_at.is_(None))
                    | (PersonalAccessToken.expires_at > now)
                )
            )
        )
        .scalars()
        .unique()
        .one_or_none()
    )
    if pat is None:
        return None

    _schedule_pat_last_used_update(hashed_token, now)
    # None (no scopes) = unrestricted; a stored list is parsed to Permissions.
    scopes = parse_permission_values(pat.scopes) if pat.scopes is not None else None
    return PatAuthResult(user=pat.user, scopes=scopes)


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
            logger.warning("Failed to update last_used_at for PAT: %s", e)

    asyncio.create_task(_update())


def create_pat(
    db_session: Session,
    user_id: UUID,
    name: str,
    expiration_days: int | None,
    pat_type: PatType = PatType.USER,
    scopes: list[Permission] | None = None,
) -> tuple[PersonalAccessToken, str]:
    """Create new PAT. Returns (db_record, raw_token).

    scopes defaults to None (no restriction — full user access); pass a list to
    scope the token to specific permissions.

    Raises ValueError if user is inactive or not found.
    """
    user = db_session.scalar(
        select(User).where(User.id == user_id)  # ty: ignore[invalid-argument-type]
    )
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
        pat_type=pat_type,
        scopes=[s.value for s in scopes] if scopes is not None else None,
    )
    db_session.add(pat)
    db_session.flush()

    return pat, raw_token


def list_user_pats(
    db_session: Session,
    user_id: UUID,
    pat_type: PatType | None = None,
) -> list[PersonalAccessToken]:
    """List all active (non-expired) PATs for a user, optionally filtered by type."""
    stmt = (
        select(PersonalAccessToken)
        .where(PersonalAccessToken.user_id == user_id)
        .where(
            (PersonalAccessToken.expires_at.is_(None))
            | (PersonalAccessToken.expires_at > datetime.now(timezone.utc))
        )
    )
    if pat_type is not None:
        stmt = stmt.where(PersonalAccessToken.pat_type == pat_type)
    return list(
        db_session.scalars(stmt.order_by(PersonalAccessToken.created_at.desc())).all()
    )


def revoke_pat(
    db_session: Session,
    pat_id: int,
    user_id: UUID,
    pat_type: PatType | None = None,
) -> bool:
    """Revoke PAT by setting expires_at=NOW() for immediate expiry.

    Returns True if revoked, False if not found, not owned by user, or already expired.
    When pat_type is specified, only revokes PATs of that type.
    """
    now = datetime.now(timezone.utc)
    stmt = (
        select(PersonalAccessToken)
        .where(PersonalAccessToken.id == pat_id)
        .where(PersonalAccessToken.user_id == user_id)
        .where(
            (PersonalAccessToken.expires_at.is_(None))
            | (PersonalAccessToken.expires_at > now)
        )
    )
    if pat_type is not None:
        stmt = stmt.where(PersonalAccessToken.pat_type == pat_type)
    pat = db_session.scalar(stmt)
    if not pat:
        return False

    # Revoke by setting expires_at to NOW() and marking as revoked for audit trail
    pat.expires_at = now
    pat.is_revoked = True
    db_session.flush()
    return True
