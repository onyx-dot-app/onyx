from collections.abc import Sequence

from sqlalchemy import Row, select
from sqlalchemy.orm import Session

from onyx.configs.constants import TokenRateLimitScope
from onyx.db.models import TokenRateLimit, UserGroup
from onyx.db.token_limit import commit_token_rate_limit
from onyx.server.token_rate_limits.models import TokenRateLimitArgs


def fetch_all_user_group_token_rate_limits_by_group(
    db_session: Session,
) -> Sequence[Row[tuple[TokenRateLimit, str]]]:
    query = (
        select(TokenRateLimit, UserGroup.name)
        .join(UserGroup, UserGroup.id == TokenRateLimit.user_group_id)
        .where(TokenRateLimit.scope == TokenRateLimitScope.USER_GROUP)
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
        cost_budget_cents=token_rate_limit_settings.cost_budget_cents,
        period=token_rate_limit_settings.period,
        scope=TokenRateLimitScope.USER_GROUP,
        user_group_id=group_id,
    )
    db_session.add(token_limit)
    commit_token_rate_limit(db_session)

    return token_limit


def fetch_user_group_token_rate_limits_for_group(
    db_session: Session,
    group_id: int,
    enabled_only: bool = False,
    ordered: bool = True,
) -> Sequence[TokenRateLimit]:
    stmt = select(TokenRateLimit).where(
        TokenRateLimit.user_group_id == group_id,
        TokenRateLimit.scope == TokenRateLimitScope.USER_GROUP,
    )

    if enabled_only:
        stmt = stmt.where(TokenRateLimit.enabled.is_(True))

    if ordered:
        stmt = stmt.order_by(TokenRateLimit.created_at.desc())

    return db_session.scalars(stmt).all()
