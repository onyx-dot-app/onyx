from collections.abc import Sequence
from datetime import datetime, timezone
from math import ceil
from threading import RLock

from cachetools import TTLCache
from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.auth.users import current_chat_accessible_user
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import TokenRateLimit, User
from onyx.db.token_limit import fetch_all_global_token_rate_limits
from onyx.db.user_usage import (
    TokenUsageBucket,
    get_cost_window_start,
    get_next_usage_bucket_start,
    get_token_window_start,
    get_total_cost_cents_buckets_since,
    get_total_token_buckets_since,
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

        if global_rate_limits:
            # Skip the token-usage aggregation when every limit is cost-only.
            triggered = None
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
                triggered = _worst_triggered_limit(global_rate_limits, global_usage)

            cost_limits = [
                rl for rl in global_rate_limits if rl.cost_budget_cents is not None
            ]
            cost_buckets: list[tuple[datetime, float]] = []
            if cost_limits:
                cost_cutoff = get_cost_window_start(
                    datetime.now(timezone.utc),
                    max(rl.period_hours for rl in cost_limits),
                )
                cost_buckets = get_total_cost_cents_buckets_since(
                    db_session, cost_cutoff
                )
            cost_triggered = _worst_triggered_cost_limit(
                global_rate_limits, cost_buckets
            )
            _raise_for_latest_reset(
                "organization",
                _token_reset_at(triggered),
                _cost_reset_at(cost_triggered),
            )


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


def _worst_triggered_limit(
    rate_limits: Sequence[TokenRateLimit], usage: Sequence[TokenUsageBucket]
) -> TokenRateLimit | None:
    """Among the exceeded token limits, return the one with the longest window
    (or None). Picking the longest period_hours makes the reported reset
    deterministic and conservative: a client that waits it out won't immediately
    re-trip a still-exceeded longer limit. Carries period_hours for the reset."""
    now = datetime.now(timezone.utc)
    worst: TokenRateLimit | None = None
    for rate_limit in rate_limits:
        # A null (cost-only) or non-positive token_budget is token-exempt — skip
        # the token check. Guarding <= 0 means a 0 (new cost-only rows store null,
        # but legacy/edge rows may hold 0) can never block every request.
        if rate_limit.token_budget is None or rate_limit.token_budget <= 0:
            continue

        cutoff = get_token_window_start(now, rate_limit.period_hours)
        tokens_used = sum(
            bucket.tokens for bucket in usage if bucket.window_start >= cutoff
        )

        # The admin enters the budget in THOUSANDS of tokens (Onyx convention),
        # so the stored value is scaled up to the real token count here.
        if tokens_used >= rate_limit.token_budget * TOKEN_BUDGET_UNIT:
            if worst is None or rate_limit.period_hours > worst.period_hours:
                worst = rate_limit

    return worst


def _is_rate_limited(
    rate_limits: Sequence[TokenRateLimit],
    usage: Sequence[TokenUsageBucket],
) -> bool:
    """Whether any provider-token budget is exceeded."""
    return _worst_triggered_limit(rate_limits, usage) is not None


def _worst_triggered_cost_limit(
    rate_limits: Sequence[TokenRateLimit],
    cost_buckets: Sequence[tuple[datetime, float]],
) -> TokenRateLimit | None:
    """Among rows whose cost_budget_cents is set and exceeded, return the one
    with the longest window (or None) — longest period_hours so the reset is
    deterministic and conservative, matching _worst_triggered_limit.

    Cost windows contain whole UTC-day buckets, including the current day.
    Rows without a cost_budget_cents are cost-exempt.
    """
    now = datetime.now(tz=timezone.utc)
    worst: TokenRateLimit | None = None
    for rate_limit in rate_limits:
        budget = rate_limit.cost_budget_cents
        if budget is None:
            continue

        cutoff = get_cost_window_start(now, rate_limit.period_hours)
        cost = sum(
            cents for window_start, cents in cost_buckets if window_start >= cutoff
        )
        if cost >= budget:
            if worst is None or rate_limit.period_hours > worst.period_hours:
                worst = rate_limit

    return worst


def raise_rate_limited(scope: str, reset_at: datetime) -> None:
    """Raise a structured 429 with the next relevant budget reset."""
    retry_after_seconds = max(
        1, ceil((reset_at - datetime.now(timezone.utc)).total_seconds())
    )
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


def _token_reset_at(limit: TokenRateLimit | None) -> datetime | None:
    if limit is None:
        return None
    return get_next_usage_bucket_start(datetime.now(timezone.utc))


def _cost_reset_at(limit: TokenRateLimit | None) -> datetime | None:
    if limit is None:
        return None
    return get_next_usage_bucket_start(datetime.now(timezone.utc))


def _raise_for_latest_reset(scope: str, *reset_times: datetime | None) -> None:
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
