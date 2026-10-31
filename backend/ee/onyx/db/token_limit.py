from collections.abc import Sequence

from pydantic import BaseModel
from sqlalchemy import Row, delete, func, select
from sqlalchemy.orm import Session

from onyx.configs.constants import (
    TokenRateLimitAction,
    TokenRateLimitPeriod,
    TokenRateLimitScope,
)
from onyx.db.models import (
    ModelConfiguration,
    TokenRateLimit,
    User__UserGroup,
    UserGroup,
)
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


class SpendingLimitRow(BaseModel):
    """One limit to write on a card."""

    period: TokenRateLimitPeriod
    model_configuration_id: int | None
    token_budget: int | None
    cost_budget_cents: float | None
    action: TokenRateLimitAction
    threshold_percent: int | None


class GroupWithLimits(BaseModel):
    id: int
    name: str
    member_count: int


def fetch_card_token_rate_limits(
    db_session: Session,
    scope: TokenRateLimitScope,
    user_group_id: int | None = None,
) -> Sequence[TokenRateLimit]:
    """Every row on one card, enabled or not."""
    return db_session.scalars(
        select(TokenRateLimit)
        .where(
            TokenRateLimit.scope == scope,
            (
                TokenRateLimit.user_group_id.is_(None)
                if user_group_id is None
                else TokenRateLimit.user_group_id == user_group_id
            ),
        )
        .order_by(TokenRateLimit.id)
    ).all()


def fetch_groups_with_token_rate_limits(db_session: Session) -> list[GroupWithLimits]:
    member_count = (
        select(func.count(User__UserGroup.user_id))
        .where(User__UserGroup.user_group_id == UserGroup.id)
        .scalar_subquery()
    )
    rows = db_session.execute(
        select(UserGroup.id, UserGroup.name, member_count)
        .where(
            UserGroup.id.in_(
                select(TokenRateLimit.user_group_id).where(
                    TokenRateLimit.user_group_id.is_not(None)
                )
            )
        )
        .order_by(UserGroup.name)
    ).all()
    return [
        GroupWithLimits(id=group_id, name=name, member_count=count)
        for group_id, name, count in rows
    ]


def fetch_model_configuration_names(
    db_session: Session, model_configuration_ids: set[int]
) -> dict[int, str]:
    """Display name per id; an id with no configuration is left out."""
    if not model_configuration_ids:
        return {}
    rows = db_session.execute(
        select(
            ModelConfiguration.id,
            func.coalesce(
                ModelConfiguration.custom_display_name,
                ModelConfiguration.display_name,
                ModelConfiguration.name,
            ),
        ).where(ModelConfiguration.id.in_(model_configuration_ids))
    ).all()
    return {row[0]: row[1] for row in rows}


def replace_card_token_rate_limits(
    db_session: Session,
    scope: TokenRateLimitScope,
    user_group_id: int | None,
    enabled: bool,
    rows: Sequence[SpendingLimitRow],
) -> None:
    """Replace every row on one card in a single transaction."""
    db_session.execute(
        delete(TokenRateLimit).where(
            TokenRateLimit.scope == scope,
            (
                TokenRateLimit.user_group_id.is_(None)
                if user_group_id is None
                else TokenRateLimit.user_group_id == user_group_id
            ),
        )
    )
    db_session.add_all(
        TokenRateLimit(
            enabled=enabled,
            scope=scope,
            user_group_id=user_group_id,
            period=row.period,
            model_configuration_id=row.model_configuration_id,
            token_budget=row.token_budget,
            cost_budget_cents=row.cost_budget_cents,
            action=row.action,
            threshold_percent=row.threshold_percent,
        )
        for row in rows
    )
    commit_token_rate_limit(db_session)


def delete_group_token_rate_limits(db_session: Session, user_group_id: int) -> None:
    db_session.execute(
        delete(TokenRateLimit).where(TokenRateLimit.user_group_id == user_group_id)
    )
    db_session.commit()
