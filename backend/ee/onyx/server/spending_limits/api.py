"""Admin API for spending limits, shaped like the admin page's cards: the
workspace pool, the workspace per-user default, and each group's pool and
per-member allowance. A PUT replaces every limit on one card."""

from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import cast
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ee.onyx.db.token_limit import (
    SpendingLimitRow,
    delete_group_token_rate_limits,
    fetch_card_token_rate_limits,
    fetch_groups_with_token_rate_limits,
    fetch_model_configuration_names,
    replace_card_token_rate_limits,
)
from ee.onyx.server.spending_limits.models import (
    EffectiveSpendingLimit,
    EffectiveSpendingLimitsResponse,
    GroupSpendingLimitCards,
    GroupSpendingLimits,
    SpendingLimitCard,
    SpendingLimitCardRequest,
    SpendingLimitsResponse,
    SpendingLimitView,
)
from onyx.auth.permissions import require_permission
from onyx.auth.scoped_permissions import assert_manages_group, assert_within_scope
from onyx.configs.constants import (
    PUBLIC_API_TAGS,
    TokenRateLimitAction,
    TokenRateLimitScope,
)
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import Permission
from onyx.db.models import TokenRateLimit, User
from onyx.db.token_limit import fetch_token_rate_limits_applying_to_user
from onyx.db.user_group import assert_group_config_is_editable
from onyx.db.user_usage import (
    get_group_cost_cents_buckets_since,
    get_group_token_buckets_since,
    get_period_window_reset,
    get_period_window_start,
    get_total_cost_cents_buckets_since,
    get_total_token_buckets_since,
)
from onyx.db.users import fetch_user_by_id
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.query_and_chat.token_limit import (
    BudgetWindow,
    budget_windows,
    invalidate_any_rate_limit_exists_cache,
    resolve_member_allowance,
)

router = APIRouter(prefix="/admin/spending-limits", tags=PUBLIC_API_TAGS)


def _model_names(
    db_session: Session, limits: Sequence[TokenRateLimit]
) -> dict[int, str]:
    return fetch_model_configuration_names(
        db_session,
        {
            limit.model_configuration_id
            for limit in limits
            if limit.model_configuration_id is not None
        },
    )


def _pool_usage(
    db_session: Session, limit: TokenRateLimit, now: datetime
) -> tuple[int, float]:
    """Tokens and cents the pool has used in the limit's current period."""
    start = get_period_window_start(now, limit.period)
    if limit.user_group_id is None:
        tokens = get_total_token_buckets_since(
            db_session, start, limit.model_configuration_id
        )
        cost = get_total_cost_cents_buckets_since(
            db_session, start, limit.model_configuration_id
        )
    else:
        tokens = get_group_token_buckets_since(
            db_session, [limit.user_group_id], start, limit.model_configuration_id
        ).get(limit.user_group_id, [])
        cost = get_group_cost_cents_buckets_since(
            db_session, [limit.user_group_id], start, limit.model_configuration_id
        ).get(limit.user_group_id, [])
    return sum(bucket.tokens for bucket in tokens), sum(c for _, c in cost)


def _card(
    db_session: Session,
    scope: TokenRateLimitScope,
    user_group_id: int | None = None,
) -> SpendingLimitCard:
    limits = fetch_card_token_rate_limits(db_session, scope, user_group_id)
    names = _model_names(db_session, limits)
    now = datetime.now(timezone.utc)
    is_pool = scope in (TokenRateLimitScope.GLOBAL, TokenRateLimitScope.USER_GROUP)
    views: list[SpendingLimitView] = []
    for limit in limits:
        view = SpendingLimitView(
            id=limit.id,
            period=limit.period,
            model_configuration_id=limit.model_configuration_id,
            model_name=(
                names.get(limit.model_configuration_id)
                if limit.model_configuration_id is not None
                else None
            ),
            token_budget=limit.token_budget,
            cost_budget_cents=limit.cost_budget_cents,
            action=limit.action,
            threshold_percent=limit.threshold_percent,
            reset_at=get_period_window_reset(now, limit.period),
        )
        if is_pool:
            view.used_tokens, view.used_cost_cents = _pool_usage(db_session, limit, now)
        views.append(view)
    # One switch per card; a card with no rows reads as enabled.
    return SpendingLimitCard(
        enabled=all(limit.enabled for limit in limits), limits=views
    )


def _group_limits(
    db_session: Session, group_id: int, group_name: str, member_count: int
) -> GroupSpendingLimits:
    return GroupSpendingLimits(
        user_group_id=group_id,
        group_name=group_name,
        member_count=member_count,
        pool=_card(db_session, TokenRateLimitScope.USER_GROUP, group_id),
        per_member=_card(db_session, TokenRateLimitScope.USER_GROUP_MEMBER, group_id),
    )


def _replace_card(
    db_session: Session,
    scope: TokenRateLimitScope,
    user_group_id: int | None,
    card: SpendingLimitCardRequest,
) -> None:
    requested_models = {
        limit.model_configuration_id
        for limit in card.limits
        if limit.model_configuration_id is not None
    }
    missing = requested_models - set(
        fetch_model_configuration_names(db_session, requested_models)
    )
    if missing:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"Unknown model configuration ids: {sorted(missing)}",
        )
    replace_card_token_rate_limits(
        db_session,
        scope,
        user_group_id,
        card.enabled,
        [
            SpendingLimitRow(
                period=limit.period,
                model_configuration_id=limit.model_configuration_id,
                token_budget=limit.token_budget,
                cost_budget_cents=limit.cost_budget_cents,
                action=limit.action,
                threshold_percent=limit.threshold_percent,
            )
            for limit in card.limits
        ],
    )
    invalidate_any_rate_limit_exists_cache()


def _authorize_group_write(user: User, db_session: Session, group_id: int) -> None:
    # Spending limits have no privacy dimension, so is_non_public=True.
    assert_within_scope(
        user,
        db_session,
        permission=Permission.MANAGE_USER_GROUPS,
        current_group_ids=[group_id],
        requested_group_ids=[group_id],
        is_non_public=True,
    )
    assert_group_config_is_editable(db_session, group_id, "set spending limits on")


"""
Read
"""


@router.get("")
def get_spending_limits(
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> SpendingLimitsResponse:
    return SpendingLimitsResponse(
        workspace_pool=_card(db_session, TokenRateLimitScope.GLOBAL),
        workspace_per_user=_card(db_session, TokenRateLimitScope.USER),
        groups=[
            _group_limits(db_session, group.id, group.name, group.member_count)
            for group in fetch_groups_with_token_rate_limits(db_session)
        ],
    )


@router.get("/groups/{group_id}")
def get_group_spending_limits(
    group_id: int,
    user: User = Depends(
        require_permission(Permission.MANAGE_USER_GROUPS, allow_scope=True)
    ),
    db_session: Session = Depends(get_session),
) -> GroupSpendingLimitCards:
    assert_manages_group(user, db_session, group_id=group_id)
    return GroupSpendingLimitCards(
        pool=_card(db_session, TokenRateLimitScope.USER_GROUP, group_id),
        per_member=_card(db_session, TokenRateLimitScope.USER_GROUP_MEMBER, group_id),
    )


"""
Write
"""


@router.put("/workspace/pool")
def put_workspace_pool(
    card: SpendingLimitCardRequest,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> SpendingLimitCard:
    _replace_card(db_session, TokenRateLimitScope.GLOBAL, None, card)
    return _card(db_session, TokenRateLimitScope.GLOBAL)


@router.put("/workspace/per-user")
def put_workspace_per_user(
    card: SpendingLimitCardRequest,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> SpendingLimitCard:
    _replace_card(db_session, TokenRateLimitScope.USER, None, card)
    return _card(db_session, TokenRateLimitScope.USER)


@router.put("/groups/{group_id}/pool")
def put_group_pool(
    group_id: int,
    card: SpendingLimitCardRequest,
    user: User = Depends(
        require_permission(Permission.MANAGE_USER_GROUPS, allow_scope=True)
    ),
    db_session: Session = Depends(get_session),
) -> SpendingLimitCard:
    _authorize_group_write(user, db_session, group_id)
    _replace_card(db_session, TokenRateLimitScope.USER_GROUP, group_id, card)
    return _card(db_session, TokenRateLimitScope.USER_GROUP, group_id)


# Full admin only: a group allowance beats the workspace per-user default in
# both directions, so a scoped manager could lift their own limit with it.
@router.put("/groups/{group_id}/per-member")
def put_group_per_member(
    group_id: int,
    card: SpendingLimitCardRequest,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> SpendingLimitCard:
    assert_group_config_is_editable(db_session, group_id, "set spending limits on")
    _replace_card(db_session, TokenRateLimitScope.USER_GROUP_MEMBER, group_id, card)
    return _card(db_session, TokenRateLimitScope.USER_GROUP_MEMBER, group_id)


# Full admin only: it also removes per-member allowances (see above). A scoped
# manager clears their group's pool with an empty pool PUT.
@router.delete("/groups/{group_id}")
def delete_group_spending_limits(
    group_id: int,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> None:
    assert_group_config_is_editable(db_session, group_id, "set spending limits on")
    delete_group_token_rate_limits(db_session, group_id)
    invalidate_any_rate_limit_exists_cache()


"""
Effective limits
"""


class _Names:
    def __init__(self, models: dict[int, str], groups: dict[int, str]) -> None:
        self.models = models
        self.groups = groups

    def effective(
        self,
        window: BudgetWindow,
        scope: TokenRateLimitScope,
        model_configuration_id: int | None,
    ) -> EffectiveSpendingLimit:
        group_id = window.user_group_id
        return EffectiveSpendingLimit(
            model_configuration_id=model_configuration_id,
            model_name=(
                self.models.get(model_configuration_id)
                if model_configuration_id is not None
                else None
            ),
            period=window.period,
            unit=window.unit,
            budget=window.budget,
            scope=scope,
            user_group_id=group_id,
            group_name=self.groups.get(group_id) if group_id is not None else None,
        )


@router.get("/users/{user_id}/effective")
def get_effective_spending_limits(
    user_id: UUID,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> EffectiveSpendingLimitsResponse:
    """The budgets one user is held to and where each comes from: the per-user
    allowance resolved per (model, period, unit), and the pools that apply."""
    if fetch_user_by_id(db_session, user_id) is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "User not found")

    limits = [
        limit
        for limit in fetch_token_rate_limits_applying_to_user(db_session, user_id)
        if limit.action == TokenRateLimitAction.BLOCK
    ]
    names = _Names(
        _model_names(db_session, limits),
        {
            group.id: group.name
            for group in fetch_groups_with_token_rate_limits(db_session)
        },
    )

    defaults: dict[int | None, list[TokenRateLimit]] = defaultdict(list)
    members: dict[int | None, dict[int, list[TokenRateLimit]]] = defaultdict(dict)
    pools: list[EffectiveSpendingLimit] = []
    for limit in limits:
        model_id = limit.model_configuration_id
        if limit.scope == TokenRateLimitScope.USER:
            defaults[model_id].append(limit)
        elif limit.scope == TokenRateLimitScope.USER_GROUP_MEMBER:
            group_id = cast(int, limit.user_group_id)  # set for group scopes
            members[model_id].setdefault(group_id, []).append(limit)
        else:
            pools.extend(
                names.effective(window, limit.scope, model_id)
                for window in budget_windows([limit], limit.user_group_id)
            )

    allowances = [
        names.effective(
            window,
            (
                TokenRateLimitScope.USER_GROUP_MEMBER
                if window.user_group_id is not None
                else TokenRateLimitScope.USER
            ),
            model_id,
        )
        for model_id in defaults.keys() | members.keys()
        for window in resolve_member_allowance(
            defaults.get(model_id, []), members.get(model_id, {})
        )
    ]
    return EffectiveSpendingLimitsResponse(
        user_id=str(user_id), allowances=allowances, pools=pools
    )
