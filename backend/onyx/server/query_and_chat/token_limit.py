from collections.abc import Sequence
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from functools import lru_cache

from dateutil import tz
from fastapi import Depends
from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.auth.users import current_chat_accessible_user
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import ChatMessage
from onyx.db.models import ChatSession
from onyx.db.models import TokenRateLimit
from onyx.db.models import User
from onyx.db.token_limit import fetch_all_global_token_rate_limits
from onyx.utils.logger import setup_logger
from onyx.utils.variable_functionality import fetch_versioned_implementation


logger = setup_logger()


TOKEN_BUDGET_UNIT = 1_000


def check_token_rate_limits(
    user: User | None = Depends(current_chat_accessible_user),
) -> None:
    # short circuit if no rate limits are set up
    # NOTE: result of `any_rate_limit_exists` is cached, so this call is fast 99% of the time
    if not any_rate_limit_exists():
        return

    versioned_rate_limit_strategy = fetch_versioned_implementation(
        "onyx.server.query_and_chat.token_limit", _check_token_rate_limits.__name__
    )
    return versioned_rate_limit_strategy(user)


def _check_token_rate_limits(_: User | None) -> None:
    _user_is_rate_limited_by_global()


"""
Global rate limits
"""


def _user_is_rate_limited_by_global() -> None:
    with get_session_with_current_tenant() as db_session:
        global_rate_limits = fetch_all_global_token_rate_limits(
            db_session=db_session, enabled_only=True, ordered=False
        )

        if global_rate_limits:
            global_cutoff_time = _get_cutoff_time(global_rate_limits)
            global_usage = _fetch_global_usage(global_cutoff_time, db_session)

            if _is_rate_limited(global_rate_limits, global_usage):
                raise HTTPException(
                    status_code=429,
                    detail="Token budget exceeded for organization. Try again later.",
                )


def _fetch_global_usage(
    cutoff_time: datetime, db_session: Session
) -> Sequence[tuple[datetime, int]]:
    """
    Fetch global token usage within the cutoff time, grouped by minute
    """
    result = db_session.execute(
        select(
            func.date_trunc("minute", ChatMessage.time_sent),
            func.sum(ChatMessage.token_count),
        )
        .join(ChatSession, ChatMessage.chat_session_id == ChatSession.id)
        .filter(
            ChatMessage.time_sent >= cutoff_time,
        )
        .group_by(func.date_trunc("minute", ChatMessage.time_sent))
    ).all()

    return [(row[0], row[1]) for row in result]


"""
Common functions
"""


def _get_cutoff_time(rate_limits: Sequence[TokenRateLimit]) -> datetime:
    max_period_hours = max(rate_limit.period_hours for rate_limit in rate_limits)
    return datetime.now(tz=timezone.utc) - timedelta(hours=max_period_hours)


def _is_rate_limited(
    rate_limits: Sequence[TokenRateLimit], usage: Sequence[tuple[datetime, int]]
) -> bool:
    """
    If at least one rate limit is exceeded, return True
    """
    for rate_limit in rate_limits:
        tokens_used = sum(
            u_token_count
            for u_date, u_token_count in usage
            if u_date
            >= datetime.now(tz=tz.UTC) - timedelta(hours=rate_limit.period_hours)
        )

        if tokens_used >= rate_limit.token_budget * TOKEN_BUDGET_UNIT:
            return True

    return False


@lru_cache()
def any_rate_limit_exists() -> bool:
    """Checks if any rate limit exists in the database. Is cached, so that if no rate limits
    are setup, we don't have any effect on average query latency."""
    logger.debug("Checking for any rate limits...")
    with get_session_with_current_tenant() as db_session:
        return (
            db_session.scalar(
                select(TokenRateLimit.id).where(
                    TokenRateLimit.enabled == True  # noqa: E712
                )
            )
            is not None
        )
