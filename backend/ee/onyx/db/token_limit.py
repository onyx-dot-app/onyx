from collections.abc import Sequence

from sqlalchemy import Row
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.configs.constants import TokenRateLimitScope
from onyx.db.models import TokenRateLimit
from onyx.db.models import TokenRateLimit__UserGroup
from onyx.db.models import UserGroup
from onyx.server.token_rate_limits.models import TokenRateLimitArgs


def fetch_all_user_group_token_rate_limits_by_group(
    db_session: Session,
) -> Sequence[Row[tuple[TokenRateLimit, str]]]:
    query = (
        select(TokenRateLimit, UserGroup.name)
        .join(
            TokenRateLimit__UserGroup,
            TokenRateLimit.id == TokenRateLimit__UserGroup.rate_limit_id,
        )
        .join(UserGroup, UserGroup.id == TokenRateLimit__UserGroup.user_group_id)
    )

    return db_session.execute(query).all()


def insert_user_group_token_rate_limit(
    db_session: Session,
    token_rate_limit_settings: TokenRateLimitArgs,
    group_id: int,
) -> TokenRateLimit:
    token_limit = TokenRateLimit(
        enabled=token_rate_limit_settings.enabled,
        token_budget=token_rate_limit_settings.token_budget,
        period_hours=token_rate_limit_settings.period_hours,
        scope=TokenRateLimitScope.USER_GROUP,
    )
    db_session.add(token_limit)
    db_session.flush()

    rate_limit = TokenRateLimit__UserGroup(
        rate_limit_id=token_limit.id, user_group_id=group_id
    )
    db_session.add(rate_limit)
    db_session.commit()

    return token_limit


def fetch_user_group_token_rate_limits_for_group(
    db_session: Session,
    group_id: int,
    enabled_only: bool = False,
    ordered: bool = True,
) -> Sequence[TokenRateLimit]:
    stmt = (
        select(TokenRateLimit)
        .join(
            TokenRateLimit__UserGroup,
            TokenRateLimit.id == TokenRateLimit__UserGroup.rate_limit_id,
        )
        .where(TokenRateLimit__UserGroup.user_group_id == group_id)
    )

    if enabled_only:
        stmt = stmt.where(TokenRateLimit.enabled.is_(True))

    if ordered:
        stmt = stmt.order_by(TokenRateLimit.created_at.desc())

    return db_session.scalars(stmt).all()
