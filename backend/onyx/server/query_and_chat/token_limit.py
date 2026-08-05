from collections.abc import Sequence
from datetime import datetime, timezone
from math import ceil
from threading import RLock

from cachetools import TTLCache
from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.auth.users import current_chat_accessible_user
from onyx.configs.constants import TokenRateLimitScope
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import TokenRateLimit, User
from onyx.db.token_limit import fetch_all_global_token_rate_limits
from onyx.db.user_usage import (
    TokenUsageBucket,
    earliest_window_reset,
    get_cost_window_start,
    get_token_window_start,
    get_total_cost_cents_buckets_since,
    get_total_token_buckets_since,
    normalize_token_period_hours,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.utils.logger import setup_logger
from onyx.utils.variable_functionality import fetch_versioned_implementation
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()

# Admin token budgets are entered in thousands of tokens; the stored value is
# multiplied by this to get the real token count enforced.
TOKEN_BUDGET_UNIT = 1000


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

        if not global_rate_limits:
            return

        # Skip the token-usage aggregation when every limit is cost-only.
        token_reset: datetime | None = None
        if _has_token_budget(global_rate_limits):
            # Scan the token table only as far back as the widest *token*
            # window — a longer cost-only window must not widen the scan.
            token_limits = [
                rl
                for rl in global_rate_limits
                if rl.token_budget is not None and rl.token_budget > 0
            ]
            global_cutoff_time = _get_cutoff_time(token_limits)
            global_usage = _fetch_global_usage(global_cutoff_time, db_session)
            token_reset = _token_budget_reset(global_rate_limits, global_usage)

        cost_reset: datetime | None = None
        cost_limits = [
            rl for rl in global_rate_limits if rl.cost_budget_cents is not None
        ]
        if cost_limits:
            cost_cutoff = get_cost_window_start(
                datetime.now(timezone.utc),
                max(rl.period_hours for rl in cost_limits),
            )
            cost_buckets = get_total_cost_cents_buckets_since(db_session, cost_cutoff)
            cost_reset = _cost_budget_reset(global_rate_limits, cost_buckets)

        _raise_for_latest_reset(TokenRateLimitScope.GLOBAL, token_reset, cost_reset)


def _fetch_global_usage(
    cutoff_time: datetime, db_session: Session
) -> list[TokenUsageBucket]:
    return get_total_token_buckets_since(db_session, cutoff_time)


"""
Common functions
"""


def _get_cutoff_time(rate_limits: Sequence[TokenRateLimit]) -> datetime:
    max_period_hours = max(rate_limit.period_hours for rate_limit in rate_limits)
    return get_token_window_start(
        datetime.now(timezone.utc),
        max_period_hours,
    )


def _has_token_budget(rate_limits: Sequence[TokenRateLimit]) -> bool:
    """Whether any limit sets a positive token budget. If not (cost-only limits),
    the caller skips the token-usage aggregation query entirely."""
    return any(
        rl.token_budget is not None and rl.token_budget > 0 for rl in rate_limits
    )


def _token_budget_reset(
    rate_limits: Sequence[TokenRateLimit], usage: Sequence[TokenUsageBucket]
) -> datetime | None:
    """The latest exact reset among the exceeded token budgets, or None.

    Each limit's reset is the earliest UTC-day boundary at which its trailing
    window drops back under budget (see `earliest_window_reset`) — not the full
    window expiry. Taking the max across all exceeded limits keeps the reported
    reset safe: a client that waits it out won't immediately re-trip a limit that
    clears later.
    """
    now = datetime.now(timezone.utc)
    buckets = [(bucket.window_start, float(bucket.tokens)) for bucket in usage]
    resets: list[datetime] = []
    for rate_limit in rate_limits:
        # A null (cost-only) or non-positive token_budget is token-exempt — skip
        # the token check. Guarding <= 0 means a 0 (new cost-only rows store null,
        # but legacy/edge rows may hold 0) can never block every request.
        if rate_limit.token_budget is None or rate_limit.token_budget <= 0:
            continue

        # The admin enters the budget in THOUSANDS of tokens (Onyx convention),
        # so the stored value is scaled up to the real token count here.
        budget = rate_limit.token_budget * TOKEN_BUDGET_UNIT
        cutoff = get_token_window_start(now, rate_limit.period_hours)
        used = sum(tokens for window_start, tokens in buckets if window_start >= cutoff)
        if used >= budget:
            resets.append(
                earliest_window_reset(
                    now,
                    normalize_token_period_hours(rate_limit.period_hours),
                    buckets,
                    budget,
                )
            )

    return max(resets) if resets else None


def _cost_budget_reset(
    rate_limits: Sequence[TokenRateLimit],
    cost_buckets: Sequence[tuple[datetime, float]],
) -> datetime | None:
    """The latest exact reset among the exceeded cost budgets, or None.

    Mirrors `_token_budget_reset`. Cost windows contain whole UTC-day buckets;
    rows without a cost_budget_cents are cost-exempt.
    """
    now = datetime.now(timezone.utc)
    resets: list[datetime] = []
    for rate_limit in rate_limits:
        budget = rate_limit.cost_budget_cents
        if budget is None:
            continue

        cutoff = get_cost_window_start(now, rate_limit.period_hours)
        cost = sum(
            cents for window_start, cents in cost_buckets if window_start >= cutoff
        )
        if cost >= budget:
            resets.append(
                earliest_window_reset(
                    now, rate_limit.period_hours, cost_buckets, budget
                )
            )

    return max(resets) if resets else None


# Human-readable subject for each scope, used only in the fallback message text.
# The machine-readable scope value goes in the structured `extra` payload.
_SCOPE_LABELS: dict[TokenRateLimitScope, str] = {
    TokenRateLimitScope.GLOBAL: "your organization",
    TokenRateLimitScope.USER: "your account",
    TokenRateLimitScope.USER_GROUP: "your user group",
}


def raise_rate_limited(scope: TokenRateLimitScope, reset_at: datetime) -> None:
    """Raise a structured 429 with the next relevant budget reset."""
    retry_after_seconds = max(
        1, ceil((reset_at - datetime.now(timezone.utc)).total_seconds())
    )
    reset_at_iso = reset_at.isoformat()
    raise OnyxError(
        OnyxErrorCode.RATE_LIMITED,
        # Neutral wording, no raw timestamp — the FE renders a friendly reset
        # time from reset_at / retry_after_seconds below.
        f"You've reached the usage budget for {_SCOPE_LABELS[scope]}.",
        extra={
            "scope": scope.value,
            "reset_at": reset_at_iso,
            "retry_after_seconds": retry_after_seconds,
        },
        headers={"Retry-After": str(retry_after_seconds)},
    )


def _raise_for_latest_reset(
    scope: TokenRateLimitScope, *reset_times: datetime | None
) -> None:
    """Raise after evaluating independent limits that must all recover."""
    resets = [reset for reset in reset_times if reset is not None]
    if resets:
        raise_rate_limited(scope, max(resets))


_ANY_RATE_LIMIT_EXISTS_CACHE_TTL_SECONDS = 60
_any_rate_limit_exists_lock = RLock()
# tenant_id -> whether that tenant has any enabled token rate limit. Keyed by tenant so
# one tenant's answer never suppresses another's enforcement in a shared worker. The
# short TTL bounds staleness across processes without an explicit cross-process bust.
_any_rate_limit_exists_cache: TTLCache[str, bool] = TTLCache(
    maxsize=10_000, ttl=_ANY_RATE_LIMIT_EXISTS_CACHE_TTL_SECONDS
)


def any_rate_limit_exists() -> bool:
    """Whether the current tenant has any enabled token rate limit. Cached per tenant so
    the common no-limits case stays a cheap fast-path on the chat dependency without a DB
    query per message."""
    tenant_id = get_current_tenant_id()
    with _any_rate_limit_exists_lock:
        cached = _any_rate_limit_exists_cache.get(tenant_id)
    if cached is not None:
        return cached

    logger.debug("Checking for any rate limits...")
    with get_session_with_current_tenant() as db_session:
        exists = (
            db_session.scalar(
                select(TokenRateLimit.id).where(
                    TokenRateLimit.enabled == True  # noqa: E712
                )
            )
            is not None
        )

    with _any_rate_limit_exists_lock:
        _any_rate_limit_exists_cache[tenant_id] = exists
    return exists


def invalidate_any_rate_limit_exists_cache() -> None:
    """Drop the current tenant's cached flag after a rate-limit write so the change is
    picked up on this process without waiting for the TTL."""
    with _any_rate_limit_exists_lock:
        _any_rate_limit_exists_cache.pop(get_current_tenant_id(), None)
