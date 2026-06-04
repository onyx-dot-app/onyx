from collections.abc import Callable
from collections.abc import Sequence
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from functools import lru_cache

from dateutil import tz
from fastapi import Depends
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
from onyx.db.user_usage import get_total_cost_cents_since
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.utils.logger import setup_logger
from onyx.utils.variable_functionality import fetch_versioned_implementation
from shared_configs.configs import USAGE_LIMIT_WINDOW_SECONDS

logger = setup_logger()

# The cost ledger buckets at this fixed grid; the cost cutoff is relaxed by one
# grid to capture partially-overlapping buckets (see _first_triggered_cost_limit).
_LEDGER_GRID = timedelta(seconds=USAGE_LIMIT_WINDOW_SECONDS)


def check_token_rate_limits(
    user: User = Depends(current_chat_accessible_user),
) -> None:
    # short circuit if no rate limits are set up
    # NOTE: result of `any_rate_limit_exists` is cached, so this call is fast 99% of the time
    if not any_rate_limit_exists():
        return

    versioned_rate_limit_strategy = fetch_versioned_implementation(
        "onyx.server.query_and_chat.token_limit", _check_token_rate_limits.__name__
    )
    return versioned_rate_limit_strategy(user)


def _check_token_rate_limits(_: User) -> None:
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

            triggered = _first_triggered_limit(global_rate_limits, global_usage)
            if triggered is not None:
                raise_rate_limited("organization", triggered.period_hours)

            cost_triggered = _first_triggered_cost_limit(
                global_rate_limits,
                lambda cutoff: get_total_cost_cents_since(db_session, cutoff),
            )
            if cost_triggered is not None:
                raise_rate_limited("organization", cost_triggered.period_hours)


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


def _first_triggered_limit(
    rate_limits: Sequence[TokenRateLimit], usage: Sequence[tuple[datetime, int]]
) -> TokenRateLimit | None:
    """Return the first exceeded limit, or None. Carries period_hours for the reset time."""
    for rate_limit in rate_limits:
        tokens_used = sum(
            u_token_count
            for u_date, u_token_count in usage
            if u_date
            >= datetime.now(tz=tz.UTC) - timedelta(hours=rate_limit.period_hours)
        )

        # token_budget is stored as a raw token count, matching the admin input.
        if tokens_used >= rate_limit.token_budget:
            return rate_limit

    return None


def _first_triggered_cost_limit(
    rate_limits: Sequence[TokenRateLimit],
    cost_since: Callable[[datetime], float],
) -> TokenRateLimit | None:
    """First row whose cost_budget_cents is set and exceeded, or None.

    Cost comes from the UserUsage ledger (not ChatMessage.token_count), which
    buckets spend at a coarse fixed grid (_LEDGER_GRID). A bucket has no sub-grid
    timing, so to mirror the token sliding window over [now - period_hours, now]
    we count every bucket that *overlaps* it: window_start >= now - period_hours
    - grid. This is conservative (a budget period finer than the grid can pull in
    one adjacent bucket) — fail-CLOSED, the safe direction for a budget gate.
    Rows without a cost_budget_cents are cost-exempt (token-only).
    """
    now = datetime.now(tz=timezone.utc)
    for rate_limit in rate_limits:
        budget = rate_limit.cost_budget_cents
        if budget is None:
            continue

        cutoff = now - timedelta(hours=rate_limit.period_hours) - _LEDGER_GRID
        if cost_since(cutoff) >= budget:
            return rate_limit

    return None


def _is_rate_limited(
    rate_limits: Sequence[TokenRateLimit], usage: Sequence[tuple[datetime, int]]
) -> bool:
    """
    If at least one rate limit is exceeded, return True
    """
    return _first_triggered_limit(rate_limits, usage) is not None


def raise_rate_limited(scope: str, period_hours: int) -> None:
    """Raise a structured 429 carrying the offending scope + when its window rolls over.

    Sliding-window enforcement has no single fixed reset instant; we report a full
    period from now as the conservative "try again after" so the FE banner can count down.
    """
    retry_after_seconds = period_hours * 3600
    reset_at = datetime.now(tz=timezone.utc) + timedelta(seconds=retry_after_seconds)
    reset_at_iso = reset_at.isoformat()
    raise OnyxError(
        OnyxErrorCode.RATE_LIMITED,
        # Neutral wording: this gate covers both token and cost budgets.
        f"Usage budget exceeded for {scope}. Try again after {reset_at_iso}.",
        extra={
            "scope": scope,
            "reset_at": reset_at_iso,
            "retry_after_seconds": retry_after_seconds,
        },
        headers={"Retry-After": str(retry_after_seconds)},
    )


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
