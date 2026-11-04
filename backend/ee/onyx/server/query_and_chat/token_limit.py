from datetime import datetime, timezone
from uuid import UUID

from onyx.configs.constants import TokenRateLimitScope
from onyx.db.api_key import is_api_key_email_address
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import AccountType
from onyx.db.models import User
from onyx.db.token_limit import (
    fetch_all_user_token_rate_limits,
    fetch_user_group_token_rate_limits,
)
from onyx.db.user_usage import (
    TokenUsageBucket,
    cost_budget_limits,
    get_group_cost_cents_buckets_since,
    get_group_token_buckets_since,
    get_user_cost_cents_buckets_since,
    get_user_token_buckets_since,
    period_fetch_cutoff,
    token_budget_limits,
)
from onyx.server.query_and_chat.token_limit import (
    _cost_budget_reset,
    _raise_for_latest_reset,
    _token_budget_reset,
    _user_is_rate_limited_by_global,
    raise_rate_limited,
)
from onyx.utils.threadpool_concurrency import run_functions_tuples_in_parallel


def _check_token_rate_limits(user: User) -> None:
    # Anonymous users are only rate limited by global settings
    if user.is_anonymous:
        _user_is_rate_limited_by_global()

    elif user.account_type == AccountType.SERVICE_ACCOUNT or is_api_key_email_address(
        user.email
    ):
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

        now = datetime.now(timezone.utc)
        token_reset: datetime | None = None
        if token_limits := token_budget_limits(user_rate_limits):
            user_usage = get_user_token_buckets_since(
                db_session, str(user_id), period_fetch_cutoff(now, token_limits)
            )
            token_reset = _token_budget_reset(token_limits, user_usage)

        cost_reset: datetime | None = None
        if cost_limits := cost_budget_limits(user_rate_limits):
            cost_buckets = get_user_cost_cents_buckets_since(
                db_session, str(user_id), period_fetch_cutoff(now, cost_limits)
            )
            cost_reset = _cost_budget_reset(cost_limits, cost_buckets)

        _raise_for_latest_reset(TokenRateLimitScope.USER, token_reset, cost_reset)


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

        now = datetime.now(timezone.utc)
        group_token_usage: dict[int, list[TokenUsageBucket]] = {}
        if token_limits := token_budget_limits(all_rate_limits):
            group_token_usage = get_group_token_buckets_since(
                db_session, user_group_ids, period_fetch_cutoff(now, token_limits)
            )

        group_cost_usage: dict[int, list[tuple[datetime, float]]] = {}
        if cost_limits := cost_budget_limits(all_rate_limits):
            group_cost_usage = get_group_cost_cents_buckets_since(
                db_session, user_group_ids, period_fetch_cutoff(now, cost_limits)
            )

        group_resets: list[datetime] = []
        for user_group_id, rate_limits in group_rate_limits.items():
            token_reset = _token_budget_reset(
                rate_limits, group_token_usage.get(user_group_id, [])
            )
            cost_reset = _cost_budget_reset(
                rate_limits, group_cost_usage.get(user_group_id, [])
            )
            # A group the user is under (no exceeded budget) unblocks them entirely.
            if token_reset is None and cost_reset is None:
                return
            resets = [reset for reset in (token_reset, cost_reset) if reset is not None]
            group_resets.append(max(resets))

        raise_rate_limited(TokenRateLimitScope.USER_GROUP, min(group_resets))
