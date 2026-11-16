from collections import defaultdict
from collections.abc import Collection, Mapping, Sequence
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import Select, exists, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from onyx.configs.constants import TokenRateLimitAction, TokenRateLimitScope
from onyx.db.models import TokenRateLimit, TokenRateLimitUsageBaseline, User__UserGroup
from onyx.db.utils import is_unique_violation
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError

TOKEN_RATE_LIMIT_BUCKET_INDEX = "uq_token_rate_limit_bucket"


class UsageBaseline(BaseModel):
    """Usage the reset day's bucket held when a limit was reset."""

    tokens: float = 0.0
    cost_cents: float = 0.0


def usage_baseline(
    limit: TokenRateLimit, baselines: Mapping[int, UsageBaseline]
) -> UsageBaseline:
    if limit.usage_reset_at is None:
        return UsageBaseline()
    return baselines.get(limit.id, UsageBaseline())


def fetch_user_usage_baselines(
    db_session: Session, user_id: UUID, limit_ids: Collection[int]
) -> dict[int, UsageBaseline]:
    if not limit_ids:
        return {}
    rows = db_session.execute(
        select(
            TokenRateLimitUsageBaseline.token_rate_limit_id,
            TokenRateLimitUsageBaseline.tokens,
            TokenRateLimitUsageBaseline.cost_cents,
        ).where(
            TokenRateLimitUsageBaseline.user_id == user_id,
            TokenRateLimitUsageBaseline.token_rate_limit_id.in_(limit_ids),
        )
    ).all()
    return {
        limit_id: UsageBaseline(tokens=tokens, cost_cents=cost_cents)
        for limit_id, tokens, cost_cents in rows
    }


def fetch_pool_usage_baselines(
    db_session: Session, limits: Sequence[TokenRateLimit]
) -> dict[int, UsageBaseline]:
    """Each reset pool limit's baseline: the sum of the baselines of the users
    the pool covers now, so it always matches the pool's usage query. The
    workspace pool covers every user; a group pool its current members."""
    limit_ids = [limit.id for limit in limits if limit.usage_reset_at is not None]
    if not limit_ids:
        return {}
    baseline = TokenRateLimitUsageBaseline
    is_member = exists().where(
        User__UserGroup.user_id == baseline.user_id,
        User__UserGroup.user_group_id == TokenRateLimit.user_group_id,
    )
    rows = db_session.execute(
        select(
            baseline.token_rate_limit_id,
            func.sum(baseline.tokens),
            func.sum(baseline.cost_cents),
        )
        .join(TokenRateLimit, TokenRateLimit.id == baseline.token_rate_limit_id)
        .where(
            baseline.token_rate_limit_id.in_(limit_ids),
            or_(TokenRateLimit.user_group_id.is_(None), is_member),
        )
        .group_by(baseline.token_rate_limit_id)
    ).all()
    return {
        limit_id: UsageBaseline(tokens=float(tokens), cost_cents=float(cost_cents))
        for limit_id, tokens, cost_cents in rows
    }


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
            "An enabled limit for this model and period already exists.",
        ) from e


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
