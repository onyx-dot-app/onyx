from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from itertools import groupby
from typing import Dict
from typing import List
from typing import Tuple
from uuid import UUID

from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db.api_key import is_api_key_email_address
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import ChatMessage
from onyx.db.models import ChatSession
from onyx.db.models import TokenRateLimit
from onyx.db.models import TokenRateLimit__UserGroup
from onyx.db.models import User
from onyx.db.models import User__UserGroup
from onyx.db.models import UserGroup
from onyx.db.token_limit import fetch_all_user_token_rate_limits
from onyx.db.user_usage import get_group_cost_cents_buckets_since
from onyx.db.user_usage import get_user_cost_cents_since
from onyx.server.query_and_chat.token_limit import _get_cutoff_time
from onyx.server.query_and_chat.token_limit import _LEDGER_GRID
from onyx.server.query_and_chat.token_limit import _raise_for_longest_window
from onyx.server.query_and_chat.token_limit import _user_is_rate_limited_by_global
from onyx.server.query_and_chat.token_limit import _worst_triggered_cost_limit
from onyx.server.query_and_chat.token_limit import _worst_triggered_limit
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

        if user_rate_limits:
            user_cutoff_time = _get_cutoff_time(user_rate_limits)
            user_usage = _fetch_user_usage(user_id, user_cutoff_time, db_session)

            triggered = _worst_triggered_limit(user_rate_limits, user_usage)
            cost_triggered = _worst_triggered_cost_limit(
                user_rate_limits,
                lambda cutoff: get_user_cost_cents_since(
                    db_session, str(user_id), cutoff
                ),
            )
            _raise_for_longest_window(
                "user",
                triggered.period_hours if triggered else None,
                cost_triggered.period_hours if cost_triggered else None,
            )


def _fetch_user_usage(
    user_id: UUID, cutoff_time: datetime, db_session: Session
) -> Sequence[tuple[datetime, int]]:
    """
    Fetch user usage within the cutoff time, grouped by minute
    """
    result = db_session.execute(
        select(
            func.date_trunc("minute", ChatMessage.time_sent),
            func.sum(ChatMessage.token_count),
        )
        .join(ChatSession, ChatMessage.chat_session_id == ChatSession.id)
        .where(ChatSession.user_id == user_id, ChatMessage.time_sent >= cutoff_time)
        .group_by(func.date_trunc("minute", ChatMessage.time_sent))
    ).all()

    return [(row[0], row[1]) for row in result]


"""
User Group rate limits
"""


def _user_is_rate_limited_by_group(user_id: UUID) -> None:
    with get_session_with_current_tenant() as db_session:
        group_rate_limits = _fetch_all_user_group_rate_limits(user_id, db_session)

        if not group_rate_limits:
            return

        # Group cutoff time is the same for all groups.
        # This could be optimized to only fetch the maximum cutoff time for
        # a specific group, but seems unnecessary for now.
        group_cutoff_time = _get_cutoff_time(
            [e for sublist in group_rate_limits.values() for e in sublist]
        )

        user_group_ids = list(group_rate_limits.keys())
        group_usage = _fetch_user_group_usage(
            user_group_ids, group_cutoff_time, db_session
        )

        # Token + cost are independent gates, each with most-permissive-group-wins:
        # the user is limited only when EVERY group the user belongs to is over
        # that gate's budget; one under-budget group exempts the user. Evaluate
        # both gates, then raise once for the longest triggering window across
        # either — so a short token window can't mask a longer cost reset.
        token_period: int | None = None
        token_periods: list[int] = []
        for user_group_id, rate_limits in group_rate_limits.items():
            usage = group_usage.get(user_group_id, [])
            triggered = _worst_triggered_limit(rate_limits, usage)
            if triggered is None:
                break  # an under-budget group means the user is not token-limited
            token_periods.append(triggered.period_hours)
        else:
            token_period = max(token_periods)

        # Batch every group's cost buckets in one query (like the token path
        # above) so the cost gate windows in Python instead of issuing a query
        # per group/limit. Fetch since the broadest cost window any group sets.
        cost_limits = [
            rl
            for rls in group_rate_limits.values()
            for rl in rls
            if rl.cost_budget_cents is not None
        ]
        group_cost_buckets: dict[int, list[tuple[datetime, float]]] = {}
        if cost_limits:
            max_cost_period = max(rl.period_hours for rl in cost_limits)
            cost_fetch_cutoff = (
                datetime.now(tz=timezone.utc)
                - timedelta(hours=max_cost_period)
                - _LEDGER_GRID
            )
            group_cost_buckets = get_group_cost_cents_buckets_since(
                db_session, user_group_ids, cost_fetch_cutoff
            )

        cost_period: int | None = None
        cost_periods: list[int] = []
        for user_group_id, rate_limits in group_rate_limits.items():
            buckets = group_cost_buckets.get(user_group_id, [])
            cost_triggered = _worst_triggered_cost_limit(
                rate_limits,
                lambda cutoff, b=buckets: sum(c for ws, c in b if ws >= cutoff),
            )
            if cost_triggered is None:
                break  # an under-budget group means the user is not cost-limited
            cost_periods.append(cost_triggered.period_hours)
        else:
            cost_period = max(cost_periods)

        _raise_for_longest_window("user's groups", token_period, cost_period)


def _fetch_all_user_group_rate_limits(
    user_id: UUID, db_session: Session
) -> Dict[int, List[TokenRateLimit]]:
    group_limits = (
        select(TokenRateLimit, User__UserGroup.user_group_id)
        .join(
            TokenRateLimit__UserGroup,
            TokenRateLimit.id == TokenRateLimit__UserGroup.rate_limit_id,
        )
        .join(
            UserGroup,
            UserGroup.id == TokenRateLimit__UserGroup.user_group_id,
        )
        .join(
            User__UserGroup,
            User__UserGroup.user_group_id == UserGroup.id,
        )
        .where(
            User__UserGroup.user_id == user_id,
            TokenRateLimit.enabled.is_(True),
        )
    )

    raw_rate_limits = db_session.execute(group_limits).all()

    group_rate_limits = defaultdict(list)
    for rate_limit, user_group_id in raw_rate_limits:
        group_rate_limits[user_group_id].append(rate_limit)

    return group_rate_limits


def _fetch_user_group_usage(
    user_group_ids: list[int], cutoff_time: datetime, db_session: Session
) -> dict[int, list[Tuple[datetime, int]]]:
    """
    Fetch user group usage within the cutoff time, grouped by minute
    """
    user_group_usage = db_session.execute(
        select(
            func.sum(ChatMessage.token_count),
            func.date_trunc("minute", ChatMessage.time_sent),
            UserGroup.id,
        )
        .join(ChatSession, ChatMessage.chat_session_id == ChatSession.id)
        .join(User__UserGroup, User__UserGroup.user_id == ChatSession.user_id)
        .join(UserGroup, UserGroup.id == User__UserGroup.user_group_id)
        .filter(UserGroup.id.in_(user_group_ids), ChatMessage.time_sent >= cutoff_time)
        .group_by(func.date_trunc("minute", ChatMessage.time_sent), UserGroup.id)
    ).all()

    return {
        user_group_id: [(usage, time_sent) for time_sent, usage, _ in group_usage]
        for user_group_id, group_usage in groupby(
            user_group_usage, key=lambda row: row[2]
        )
    }
