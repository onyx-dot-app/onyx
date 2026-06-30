from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime
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
from onyx.db.user_usage import get_user_cost_cents_buckets_since
from onyx.server.query_and_chat.token_limit import _get_cutoff_time
from onyx.server.query_and_chat.token_limit import _has_token_budget
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
        if not user_rate_limits:
            return

        # Token side — skip the usage scan entirely when every limit is cost-only.
        token_triggered = None
        if _has_token_budget(user_rate_limits):
            token_limits = [
                rl
                for rl in user_rate_limits
                if rl.token_budget is not None and rl.token_budget > 0
            ]
            user_cutoff_time = _get_cutoff_time(token_limits)
            user_usage = _fetch_user_usage(user_id, user_cutoff_time, db_session)
            token_triggered = _worst_triggered_limit(user_rate_limits, user_usage)

        # Cost side — same UserUsage-ledger bucket approach as the global gate.
        cost_buckets: list[tuple[datetime, float]] = []
        if any(rl.cost_budget_cents is not None for rl in user_rate_limits):
            cost_cutoff = _get_cutoff_time(user_rate_limits) - _LEDGER_GRID
            cost_buckets = get_user_cost_cents_buckets_since(
                db_session, str(user_id), cost_cutoff
            )
        cost_triggered = _worst_triggered_cost_limit(user_rate_limits, cost_buckets)

        _raise_for_longest_window(
            "your account",
            token_triggered.period_hours if token_triggered else None,
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

        all_limits = [e for sublist in group_rate_limits.values() for e in sublist]
        user_group_ids = list(group_rate_limits.keys())

        # Token usage per group — skip the scan when every group limit is cost-only.
        group_usage: dict[int, list[tuple[datetime, int]]] = {}
        if _has_token_budget(all_limits):
            token_limits = [
                rl for rl in all_limits if rl.token_budget is not None and rl.token_budget > 0
            ]
            group_cutoff_time = _get_cutoff_time(token_limits)
            group_usage = _fetch_user_group_usage(
                user_group_ids, group_cutoff_time, db_session
            )

        # Cost buckets per group — one query for the widest window.
        group_cost_buckets: dict[int, list[tuple[datetime, float]]] = {}
        if any(rl.cost_budget_cents is not None for rl in all_limits):
            cost_cutoff = _get_cutoff_time(all_limits) - _LEDGER_GRID
            group_cost_buckets = get_group_cost_cents_buckets_since(
                db_session, user_group_ids, cost_cutoff
            )

        # A user passes if ANY of their groups is fully under budget (token AND
        # cost). Only when EVERY group has an exceeded limit do we block, then
        # report the longest offending window across all groups.
        worst_token_period: int | None = None
        worst_cost_period: int | None = None
        for user_group_id, rate_limits in group_rate_limits.items():
            usage = group_usage.get(user_group_id, [])
            token_trig = _worst_triggered_limit(rate_limits, usage)
            cost_trig = _worst_triggered_cost_limit(
                rate_limits, group_cost_buckets.get(user_group_id, [])
            )
            if token_trig is None and cost_trig is None:
                return  # this group is under budget -> user is allowed
            if token_trig is not None:
                worst_token_period = max(
                    worst_token_period or 0, token_trig.period_hours
                )
            if cost_trig is not None:
                worst_cost_period = max(worst_cost_period or 0, cost_trig.period_hours)

        _raise_for_longest_window(
            "your group", worst_token_period, worst_cost_period
        )


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
