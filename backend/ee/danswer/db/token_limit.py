from collections.abc import Sequence

from sqlalchemy import Row
from sqlalchemy import select
from sqlalchemy.orm import Session

from danswer.configs.constants import TokenRateLimitScope
from danswer.db.models import TokenRateLimit
from danswer.db.models import TokenRateLimit__UserGroup
from danswer.db.models import UserGroup
from danswer.server.token_rate_limits.models import TokenRateLimitArgs


def fetch_all_user_token_rate_limits(
    db_session: Session,
    enabled_only: bool = False,
    ordered: bool = True,
) -> Sequence[TokenRateLimit]:
    query = select(TokenRateLimit).where(
        TokenRateLimit.scope == TokenRateLimitScope.USER
    )

    if enabled_only:
        query = query.where(TokenRateLimit.enabled.is_(True))

    if ordered:
        query = query.order_by(TokenRateLimit.created_at.desc())

    return db_session.scalars(query).all()


def fetch_all_global_token_rate_limits(
    db_session: Session,
    enabled_only: bool = False,
    ordered: bool = True,
) -> Sequence[TokenRateLimit]:
    query = select(TokenRateLimit).where(
        TokenRateLimit.scope == TokenRateLimitScope.GLOBAL
    )

    if enabled_only:
        query = query.where(TokenRateLimit.enabled.is_(True))

    if ordered:
        query = query.order_by(TokenRateLimit.created_at.desc())

    token_rate_limits = db_session.scalars(query).all()
    return token_rate_limits


def fetch_all_user_group_token_rate_limits(
    db_session: Session, group_id: int, enabled_only: bool = False, ordered: bool = True
) -> Sequence[TokenRateLimit]:
    query = (
        select(TokenRateLimit)
        .join(
            TokenRateLimit__UserGroup,
            TokenRateLimit.id == TokenRateLimit__UserGroup.rate_limit_id,
        )
        .where(
            TokenRateLimit__UserGroup.user_group_id == group_id,
            TokenRateLimit.scope == TokenRateLimitScope.USER_GROUP,
        )
    )

    if enabled_only:
        query = query.where(TokenRateLimit.enabled.is_(True))

    if ordered:
        query = query.order_by(TokenRateLimit.created_at.desc())

    token_rate_limits = db_session.scalars(query).all()
    return token_rate_limits


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


def insert_user_token_rate_limit(
    db_session: Session,
    token_rate_limit_settings: TokenRateLimitArgs,
) -> TokenRateLimit:
    token_limit = TokenRateLimit(
        enabled=token_rate_limit_settings.enabled,
        token_budget=token_rate_limit_settings.token_budget,
        period_hours=token_rate_limit_settings.period_hours,
        scope=TokenRateLimitScope.USER,
    )
    db_session.add(token_limit)
    db_session.commit()

    return token_limit


def insert_global_token_rate_limit(
    db_session: Session,
    token_rate_limit_settings: TokenRateLimitArgs,
) -> TokenRateLimit:
    token_limit = TokenRateLimit(
        enabled=token_rate_limit_settings.enabled,
        token_budget=token_rate_limit_settings.token_budget,
        period_hours=token_rate_limit_settings.period_hours,
        scope=TokenRateLimitScope.GLOBAL,
    )
    db_session.add(token_limit)
    db_session.commit()

    return token_limit


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


def update_token_rate_limit(
    db_session: Session,
    token_rate_limit_id: int,
    token_rate_limit_settings: TokenRateLimitArgs,
) -> TokenRateLimit:
    token_limit = db_session.get(TokenRateLimit, token_rate_limit_id)
    if token_limit is None:
        raise ValueError(f"TokenRateLimit with id '{token_rate_limit_id}' not found")

    token_limit.enabled = token_rate_limit_settings.enabled
    token_limit.token_budget = token_rate_limit_settings.token_budget
    token_limit.period_hours = token_rate_limit_settings.period_hours
    db_session.commit()

    return token_limit


def delete_token_rate_limit(
    db_session: Session,
    token_rate_limit_id: int,
) -> None:
    token_limit = db_session.get(TokenRateLimit, token_rate_limit_id)
    if token_limit is None:
        raise ValueError(f"TokenRateLimit with id '{token_rate_limit_id}' not found")

    db_session.query(TokenRateLimit__UserGroup).filter(
        TokenRateLimit__UserGroup.rate_limit_id == token_rate_limit_id
    ).delete()

    db_session.delete(token_limit)
    db_session.commit()
