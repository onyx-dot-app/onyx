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
