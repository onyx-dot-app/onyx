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
from onyx.db.user_usage import get_total_cost_cents_buckets_since
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.utils.logger import setup_logger
from onyx.utils.variable_functionality import fetch_versioned_implementation
from shared_configs.configs import USAGE_LIMIT_WINDOW_SECONDS

logger = setup_logger()

# Admin token budgets are entered in thousands of tokens; the stored value is
# multiplied by this to get the real token count enforced.
TOKEN_BUDGET_UNIT = 1000

# The cost ledger buckets at this fixed grid; the cost cutoff is relaxed by one
# grid to capture partially-overlapping buckets (see _worst_triggered_cost_limit).
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
            # Skip the token-usage aggregation when every limit is cost-only.
            triggered = None
            if _has_token_budget(global_rate_limits):
                global_cutoff_time = _get_cutoff_time(global_rate_limits)
                global_usage = _fetch_global_usage(global_cutoff_time, db_session)
                triggered = _worst_triggered_limit(global_rate_limits, global_usage)

            cost_buckets: list[tuple[datetime, float]] = []
            if any(rl.cost_budget_cents is not None for rl in global_rate_limits):
                # One bucket fetch for the widest window; _worst_triggered_cost_limit
                # sums per-limit in Python (no query per cost limit).
                cost_cutoff = _get_cutoff_time(global_rate_limits) - _LEDGER_GRID
                cost_buckets = get_total_cost_cents_buckets_since(
                    db_session, cost_cutoff
                )
            cost_triggered = _worst_triggered_cost_limit(
                global_rate_limits, cost_buckets
            )
            _raise_for_longest_window(
                "organization",
                triggered.period_hours if triggered else None,
                cost_triggered.period_hours if cost_triggered else None,
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


def _has_token_budget(rate_limits: Sequence[TokenRateLimit]) -> bool:
    """Whether any limit sets a positive token budget. If not (cost-only limits),
    the caller skips the token-usage aggregation query entirely."""
    return any(
        rl.token_budget is not None and rl.token_budget > 0 for rl in rate_limits
    )


def _worst_triggered_limit(
    rate_limits: Sequence[TokenRateLimit], usage: Sequence[tuple[datetime, int]]
) -> TokenRateLimit | None:
    """Among the exceeded token limits, return the one with the longest window
    (or None). Picking the longest period_hours makes the reported reset
    deterministic and conservative: a client that waits it out won't immediately
    re-trip a still-exceeded longer limit. Carries period_hours for the reset."""
    worst: TokenRateLimit | None = None
    for rate_limit in rate_limits:
        # A null (cost-only) or non-positive token_budget is token-exempt — skip
        # the token check. Guarding <= 0 means a 0 (new cost-only rows store null,
        # but legacy/edge rows may hold 0) can never block every request.
        if rate_limit.token_budget is None or rate_limit.token_budget <= 0:
            continue

        tokens_used = sum(
            u_token_count
            for u_date, u_token_count in usage
            if u_date
            >= datetime.now(tz=tz.UTC) - timedelta(hours=rate_limit.period_hours)
        )

        # The admin enters the budget in THOUSANDS of tokens (Onyx convention),
        # so the stored value is scaled up to the real token count here.
        if tokens_used >= rate_limit.token_budget * TOKEN_BUDGET_UNIT:
            if worst is None or rate_limit.period_hours > worst.period_hours:
                worst = rate_limit

    return worst


def _worst_triggered_cost_limit(
    rate_limits: Sequence[TokenRateLimit],
    cost_buckets: Sequence[tuple[datetime, float]],
) -> TokenRateLimit | None:
    """Among rows whose cost_budget_cents is set and exceeded, return the one
    with the longest window (or None) — longest period_hours so the reset is
    deterministic and conservative, matching _worst_triggered_limit.

    Cost comes from the UserUsage ledger (not ChatMessage.token_count), bucketed
    at a coarse fixed grid (_LEDGER_GRID) and fetched once upstream; we sum the
    buckets per window in Python (no query per limit). A bucket has no sub-grid
    timing, so to mirror the token sliding window over [now - period_hours, now]
    we count every bucket that *overlaps* it: window_start >= now - period_hours
    - grid. This is conservative (a budget period finer than the grid can pull in
    one adjacent bucket) — fail-CLOSED, the safe direction for a budget gate.
    Rows without a cost_budget_cents are cost-exempt (token-only).
    """
    now = datetime.now(tz=timezone.utc)
    worst: TokenRateLimit | None = None
    for rate_limit in rate_limits:
        budget = rate_limit.cost_budget_cents
        if budget is None:
            continue

        cutoff = now - timedelta(hours=rate_limit.period_hours) - _LEDGER_GRID
        cost = sum(
            cents for window_start, cents in cost_buckets if window_start >= cutoff
        )
        if cost >= budget:
            if worst is None or rate_limit.period_hours > worst.period_hours:
                worst = rate_limit

    return worst


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
        # Neutral wording, no raw timestamp — the FE renders a friendly reset
        # time from reset_at / retry_after_seconds below.
        f"You've reached the usage budget for {scope}.",
        extra={
            "scope": scope,
            "reset_at": reset_at_iso,
            "retry_after_seconds": retry_after_seconds,
        },
        headers={"Retry-After": str(retry_after_seconds)},
    )


def _raise_for_longest_window(scope: str, *period_hours: int | None) -> None:
    """Raise once for the longest of the given reset windows (Nones skipped).
    The token and cost gates are independent; evaluating both before raising
    avoids reporting a too-early reset when a short token window and a long cost
    window are both exceeded."""
    periods = [p for p in period_hours if p is not None]
    if periods:
        raise_rate_limited(scope, max(periods))


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
