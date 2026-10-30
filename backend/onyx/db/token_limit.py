from collections import defaultdict
from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import Select, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from onyx.configs.constants import TokenRateLimitAction, TokenRateLimitScope
from onyx.db.models import TokenRateLimit, User__UserGroup
from onyx.db.utils import is_unique_violation
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.token_rate_limits.models import (
    MAX_TOKEN_BUDGET_THOUSANDS,
    TokenRateLimitArgs,
    TokenRateLimitUpdateArgs,
)

TOKEN_RATE_LIMIT_BUCKET_INDEX = "uq_token_rate_limit_bucket"


def commit_token_rate_limit(db_session: Session) -> None:
    """Commit, turning a second enabled limit for the same bucket into a 409."""
    try:
        db_session.commit()
    except IntegrityError as e:
        db_session.rollback()
        if not is_unique_violation(e, TOKEN_RATE_LIMIT_BUCKET_INDEX):
            raise
        raise OnyxError(
            OnyxErrorCode.DUPLICATE_RESOURCE,
            "An enabled limit with this period already exists. Edit it instead.",
        ) from e


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


def _enforced_limits_query(
    scope: TokenRateLimitScope, model_configuration_id: int | None
) -> Select[tuple[TokenRateLimit]]:
    model_filter = (
        TokenRateLimit.model_configuration_id.is_(None)
        if model_configuration_id is None
        else TokenRateLimit.model_configuration_id == model_configuration_id
    )
    return select(TokenRateLimit).where(
        TokenRateLimit.scope == scope,
        TokenRateLimit.enabled.is_(True),
        TokenRateLimit.action == TokenRateLimitAction.BLOCK,
        model_filter,
    )


def fetch_enforced_token_rate_limits(
    db_session: Session,
    scope: TokenRateLimitScope,
    model_configuration_id: int | None = None,
) -> Sequence[TokenRateLimit]:
    """Enabled BLOCK limits of a workspace scope, on one model or, for None,
    on all models."""
    return db_session.scalars(
        _enforced_limits_query(scope, model_configuration_id)
    ).all()


def fetch_user_group_enforced_token_rate_limits(
    db_session: Session,
    user_id: UUID,
    scope: TokenRateLimitScope,
    model_configuration_id: int | None = None,
) -> dict[int, list[TokenRateLimit]]:
    """Enabled BLOCK limits of a group scope for every group the user is in,
    keyed by group id."""
    query = (
        _enforced_limits_query(scope, model_configuration_id)
        .add_columns(User__UserGroup.user_group_id)
        .join(
            User__UserGroup,
            User__UserGroup.user_group_id == TokenRateLimit.user_group_id,
        )
        .where(User__UserGroup.user_id == user_id)
    )
    result: dict[int, list[TokenRateLimit]] = defaultdict(list)
    for limit, group_id in db_session.execute(query).all():
        result[group_id].append(limit)
    return dict(result)


def fetch_token_rate_limits_applying_to_user(
    db_session: Session, user_id: UUID
) -> Sequence[TokenRateLimit]:
    """Every enabled limit whose usage includes this user's: workspace limits
    and the limits of the user's groups, on any model."""
    user_group_ids = select(User__UserGroup.user_group_id).where(
        User__UserGroup.user_id == user_id
    )
    return db_session.scalars(
        select(TokenRateLimit).where(
            TokenRateLimit.enabled.is_(True),
            or_(
                TokenRateLimit.user_group_id.is_(None),
                TokenRateLimit.user_group_id.in_(user_group_ids),
            ),
        )
    ).all()


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


def insert_user_token_rate_limit(
    db_session: Session,
    token_rate_limit_settings: TokenRateLimitArgs,
) -> TokenRateLimit:
    token_limit = TokenRateLimit(
        enabled=token_rate_limit_settings.enabled,
        token_budget=token_rate_limit_settings.token_budget,
        cost_budget_cents=token_rate_limit_settings.cost_budget_cents,
        period=token_rate_limit_settings.period,
        scope=TokenRateLimitScope.USER,
    )
    db_session.add(token_limit)
    commit_token_rate_limit(db_session)

    return token_limit


def insert_global_token_rate_limit(
    db_session: Session,
    token_rate_limit_settings: TokenRateLimitArgs,
) -> TokenRateLimit:
    token_limit = TokenRateLimit(
        enabled=token_rate_limit_settings.enabled,
        token_budget=token_rate_limit_settings.token_budget,
        cost_budget_cents=token_rate_limit_settings.cost_budget_cents,
        period=token_rate_limit_settings.period,
        scope=TokenRateLimitScope.GLOBAL,
    )
    db_session.add(token_limit)
    commit_token_rate_limit(db_session)

    return token_limit


def get_token_rate_limit_scope_and_group_id(
    db_session: Session, token_rate_limit_id: int
) -> tuple[TokenRateLimitScope, int | None]:
    """Raises ValueError if the id is unknown."""
    token_limit = db_session.get(TokenRateLimit, token_rate_limit_id)
    if token_limit is None:
        raise ValueError(f"TokenRateLimit with id '{token_rate_limit_id}' not found")
    return token_limit.scope, token_limit.user_group_id


def update_token_rate_limit(
    db_session: Session,
    token_rate_limit_id: int,
    token_rate_limit_settings: TokenRateLimitUpdateArgs,
) -> TokenRateLimit:
    token_limit = db_session.get(TokenRateLimit, token_rate_limit_id)
    if token_limit is None:
        raise ValueError(f"TokenRateLimit with id '{token_rate_limit_id}' not found")

    if (
        token_rate_limit_settings.token_budget is not None
        and token_rate_limit_settings.token_budget > MAX_TOKEN_BUDGET_THOUSANDS
        and token_rate_limit_settings.token_budget != token_limit.token_budget
    ):
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "Token budgets cannot exceed 1T tokens.",
        )

    token_limit.enabled = token_rate_limit_settings.enabled
    token_limit.token_budget = token_rate_limit_settings.token_budget
    token_limit.cost_budget_cents = token_rate_limit_settings.cost_budget_cents
    token_limit.period = token_rate_limit_settings.period
    commit_token_rate_limit(db_session)

    return token_limit


def delete_token_rate_limit(
    db_session: Session,
    token_rate_limit_id: int,
) -> None:
    token_limit = db_session.get(TokenRateLimit, token_rate_limit_id)
    if token_limit is None:
        raise ValueError(f"TokenRateLimit with id '{token_rate_limit_id}' not found")

    db_session.delete(token_limit)
    db_session.commit()
