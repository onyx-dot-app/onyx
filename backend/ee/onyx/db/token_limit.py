from collections.abc import Sequence

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ee.onyx.db.license import acquire_advisory_xact_lock, advisory_lock_id
from ee.onyx.server.spending_limits.models import GroupWithLimits, SpendingLimitRequest
from onyx.configs.constants import TokenRateLimitScope
from onyx.db.models import (
    ModelConfiguration,
    TokenRateLimit,
    User__UserGroup,
    UserGroup,
)
from onyx.db.token_limit import commit_token_rate_limit
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from shared_configs.contextvars import get_current_tenant_id

_WORKSPACE_CARD_LOCK_NAMESPACE = "onyx_spending_limit_card"


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


def replace_card_token_rate_limits(
    db_session: Session,
    scope: TokenRateLimitScope,
    user_group_id: int | None,
    enabled: bool,
    rows: Sequence[SpendingLimitRequest],
) -> None:
    """Replace every row on one card in a single transaction. Locks the card
    first, so concurrent replaces of one card serialize."""
    _lock_card(db_session, scope, user_group_id)
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
