from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime, timezone
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from ee.onyx.db.license import acquire_advisory_xact_lock, advisory_lock_id
from ee.onyx.server.spending_limits.models import GroupWithLimits, SpendingLimitRequest
from onyx.configs.constants import (
    TokenRateLimitAction,
    TokenRateLimitPeriod,
    TokenRateLimitScope,
)
from onyx.db.models import (
    ModelConfiguration,
    TokenRateLimit,
    TokenRateLimitUsageBaseline,
    User__UserGroup,
    UserGroup,
)
from onyx.db.token_limit import commit_token_rate_limit
from onyx.db.user_usage import (
    get_period_window_start,
    get_usage_bucket_start,
    insert_user_usage_baselines__no_commit,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from shared_configs.contextvars import get_current_tenant_id

_WORKSPACE_CARD_LOCK_NAMESPACE = "onyx_spending_limit_card"

# (model_configuration_id, period, action, threshold_percent): one bucket on a card.
_CardBucketKey = tuple[
    int | None, TokenRateLimitPeriod, TokenRateLimitAction, int | None
]


def _card_bucket_key(
    limit: TokenRateLimit | SpendingLimitRequest,
) -> _CardBucketKey:
    return (
        limit.model_configuration_id,
        limit.period,
        limit.action,
        limit.threshold_percent,
    )


def fetch_token_rate_limit(db_session: Session, limit_id: int) -> TokenRateLimit | None:
    return db_session.get(TokenRateLimit, limit_id)


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


def _lock_card(
    db_session: Session, scope: TokenRateLimitScope, user_group_id: int | None
) -> None:
    """Group cards lock the group row; workspace cards have no row to lock and
    take an advisory lock on the scope. Released on commit or rollback."""
    if user_group_id is None:
        acquire_advisory_xact_lock(
            db_session,
            advisory_lock_id(
                f"{_WORKSPACE_CARD_LOCK_NAMESPACE}:{scope.value}",
                get_current_tenant_id(),
            ),
        )
        return
    locked_group_id = db_session.scalar(
        select(UserGroup.id).where(UserGroup.id == user_group_id).with_for_update()
    )
    if locked_group_id is None:
        raise OnyxError(
            OnyxErrorCode.NOT_FOUND, f"User group {user_group_id} not found"
        )


class _CarriedReset(BaseModel):
    old_limit_id: int
    usage_reset_at: datetime


class _CarriedBaseline(BaseModel):
    user_id: UUID
    tokens: int
    cost_cents: float


def _carried_resets(
    old_limits: Sequence[TokenRateLimit], now: datetime
) -> dict[_CardBucketKey, _CarriedReset]:
    """Per bucket, the reset of the old row with the latest reset in its
    current period."""
    carried: dict[_CardBucketKey, _CarriedReset] = {}
    for old in old_limits:
        reset = old.usage_reset_at
        if reset is None or reset < get_period_window_start(now, old.period):
            continue
        key = _card_bucket_key(old)
        current = carried.get(key)
        if current is None or reset > current.usage_reset_at:
            carried[key] = _CarriedReset(old_limit_id=old.id, usage_reset_at=reset)
    return carried


def _fetch_baselines(
    db_session: Session, limit_ids: list[int]
) -> dict[int, list[_CarriedBaseline]]:
    baselines: dict[int, list[_CarriedBaseline]] = defaultdict(list)
    if not limit_ids:
        return baselines
    for limit_id, user_id, tokens, cost_cents in db_session.execute(
        select(
            TokenRateLimitUsageBaseline.token_rate_limit_id,
            TokenRateLimitUsageBaseline.user_id,
            TokenRateLimitUsageBaseline.tokens,
            TokenRateLimitUsageBaseline.cost_cents,
        ).where(TokenRateLimitUsageBaseline.token_rate_limit_id.in_(limit_ids))
    ):
        baselines[limit_id].append(
            _CarriedBaseline(user_id=user_id, tokens=tokens, cost_cents=cost_cents)
        )
    return baselines


def replace_card_token_rate_limits(
    db_session: Session,
    scope: TokenRateLimitScope,
    user_group_id: int | None,
    enabled: bool,
    rows: Sequence[SpendingLimitRequest],
) -> None:
    """Replace every row on one card in a single transaction. Locks the card
    first, so concurrent replaces of one card serialize. A new row keeps the
    usage reset and baselines of the old row in its bucket while that reset is
    in the current period."""
    _lock_card(db_session, scope, user_group_id)
    carried = _carried_resets(
        fetch_card_token_rate_limits(db_session, scope, user_group_id),
        datetime.now(timezone.utc),
    )
    # Read before the delete: deleting the old rows cascades to their baselines.
    baselines = _fetch_baselines(
        db_session, [reset.old_limit_id for reset in carried.values()]
    )
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
    for row in rows:
        limit = TokenRateLimit(
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
        db_session.add(limit)
        reset = carried.get(_card_bucket_key(row))
        if reset is None:
            continue
        limit.usage_reset_at = reset.usage_reset_at
        db_session.add_all(
            TokenRateLimitUsageBaseline(
                token_rate_limit=limit,
                user_id=baseline.user_id,
                tokens=baseline.tokens,
                cost_cents=baseline.cost_cents,
            )
            for baseline in baselines[reset.old_limit_id]
        )
    commit_token_rate_limit(db_session)


def reset_token_rate_limit_usage(
    db_session: Session, limit: TokenRateLimit, now: datetime
) -> None:
    """Count the limit's usage from `now`: store each user's usage in the
    current bucket as the baseline to subtract from it. Takes the card lock, so
    a reset and a card replace serialize and the replace carries the reset over."""
    limit_id = limit.id
    model_configuration_id = limit.model_configuration_id
    _lock_card(db_session, limit.scope, limit.user_group_id)
    # A replace that committed before the lock deleted the row.
    updated_id = db_session.scalar(
        update(TokenRateLimit)
        .where(TokenRateLimit.id == limit_id)
        .values(usage_reset_at=now)
        .returning(TokenRateLimit.id)
    )
    if updated_id is None:
        db_session.rollback()
        raise OnyxError(OnyxErrorCode.NOT_FOUND, f"Spending limit {limit_id} not found")
    db_session.execute(
        delete(TokenRateLimitUsageBaseline).where(
            TokenRateLimitUsageBaseline.token_rate_limit_id == limit_id
        )
    )
    insert_user_usage_baselines__no_commit(
        db_session, limit_id, get_usage_bucket_start(now), model_configuration_id
    )
    db_session.commit()


def delete_group_token_rate_limits(db_session: Session, user_group_id: int) -> None:
    db_session.execute(
        delete(TokenRateLimit).where(TokenRateLimit.user_group_id == user_group_id)
    )
    db_session.commit()
