from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import Session

from onyx.configs.constants import TokenRateLimitScope
from onyx.db.api_key import is_api_key_email_address
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import TokenRateLimit, User
from onyx.db.token_limit import (
    fetch_all_user_token_rate_limits,
    fetch_user_group_token_rate_limits,
)
from onyx.db.user_usage import (
    TokenUsageBucket,
    get_group_cost_cents_buckets_since,
    get_group_token_buckets_since,
    get_user_cost_cents_buckets_since,
    get_user_token_buckets_since,
)
from onyx.server.query_and_chat.token_limit import (
    _LEDGER_GRID,
    _get_cutoff_time,
    _has_token_budget,
    _raise_for_longest_window,
    _user_is_rate_limited_by_global,
    _worst_triggered_cost_limit,
    _worst_triggered_limit,
)
from onyx.utils.threadpool_concurrency import run_functions_tuples_in_parallel


def _check_token_rate_limits(user: User) -> None:
    # Anonymous users are only rate limited by global settings
    if user.is_anonymous:
        _user_is_rate_limited_by_global()

    elif is_api_key_email_address(user.email):
        # API keys are only rate limited by global settings
        _user_is_rate_limited_by_global()

    else:
        run_functions_tuples_in_parallel(
            [
                (_user_is_rate_limited, (user.id,)),
                (_user_is_rate_limited_by_group, (user.id,)),
                (_user_is_rate_limited_by_global, ()),
            ]
        )


"""
User rate limits
"""


def _user_is_rate_limited(user_id: UUID) -> None:
    with get_session_with_current_tenant() as db_session:
        user_rate_limits = fetch_all_user_token_rate_limits(
            db_session=db_session, enabled_only=True, ordered=False
        )
        if not user_rate_limits:
            return

        token_triggered: TokenRateLimit | None = None
        token_limits = [
            limit
            for limit in user_rate_limits
            if limit.token_budget is not None and limit.token_budget > 0
        ]
        if token_limits:
            user_cutoff_time = _get_cutoff_time(token_limits)
            user_usage = _fetch_user_usage(user_id, user_cutoff_time, db_session)
            token_triggered = _worst_triggered_limit(user_rate_limits, user_usage)

        cost_triggered: TokenRateLimit | None = None
        cost_limits = [
            limit for limit in user_rate_limits if limit.cost_budget_cents is not None
        ]
        if cost_limits:
            cost_cutoff = _get_cutoff_time(cost_limits) - _LEDGER_GRID
            cost_buckets = get_user_cost_cents_buckets_since(
                db_session, str(user_id), cost_cutoff
            )
            cost_triggered = _worst_triggered_cost_limit(user_rate_limits, cost_buckets)

        _raise_for_longest_window(
            TokenRateLimitScope.USER.value,
            token_triggered.period_hours if token_triggered else None,
            cost_triggered.period_hours if cost_triggered else None,
        )


def _fetch_user_usage(
    user_id: UUID, cutoff_time: datetime, db_session: Session
) -> list[TokenUsageBucket]:
    return get_user_token_buckets_since(db_session, str(user_id), cutoff_time)


"""
User Group rate limits
"""


def _user_is_rate_limited_by_group(user_id: UUID) -> None:
    with get_session_with_current_tenant() as db_session:
        group_rate_limits = fetch_user_group_token_rate_limits(db_session, user_id)
        if not group_rate_limits:
            return

        all_rate_limits = [
            limit for limits in group_rate_limits.values() for limit in limits
        ]
        user_group_ids = list(group_rate_limits)

        group_token_usage: dict[int, list[TokenUsageBucket]] = {}
        if _has_token_budget(all_rate_limits):
            token_limits = [
                limit
                for limit in all_rate_limits
                if limit.token_budget is not None and limit.token_budget > 0
            ]
            token_cutoff = _get_cutoff_time(token_limits)
            group_token_usage = _fetch_user_group_usage(
                user_group_ids, token_cutoff, db_session
            )

        group_cost_usage: dict[int, list[tuple[datetime, float]]] = {}
        cost_limits = [
            limit for limit in all_rate_limits if limit.cost_budget_cents is not None
        ]
        if cost_limits:
            cost_cutoff = _get_cutoff_time(cost_limits) - _LEDGER_GRID
            group_cost_usage = get_group_cost_cents_buckets_since(
                db_session, user_group_ids, cost_cutoff
            )

        triggered_periods: list[int] = []
        for user_group_id, rate_limits in group_rate_limits.items():
            token_triggered = _worst_triggered_limit(
                rate_limits, group_token_usage.get(user_group_id, [])
            )
            cost_triggered = _worst_triggered_cost_limit(
                rate_limits, group_cost_usage.get(user_group_id, [])
            )
            if token_triggered is None and cost_triggered is None:
                return
            if token_triggered:
                triggered_periods.append(token_triggered.period_hours)
            if cost_triggered:
                triggered_periods.append(cost_triggered.period_hours)

        _raise_for_longest_window(
            TokenRateLimitScope.USER_GROUP.value, *triggered_periods
        )


def _fetch_user_group_usage(
    user_group_ids: list[int], cutoff_time: datetime, db_session: Session
) -> dict[int, list[TokenUsageBucket]]:
    return get_group_token_buckets_since(db_session, user_group_ids, cutoff_time)
