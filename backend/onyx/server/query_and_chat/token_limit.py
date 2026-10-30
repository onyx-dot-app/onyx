"""Spending limit enforcement. CE enforces the workspace pool; EE adds group
pools and per-user allowances (`ee.onyx.server.query_and_chat.token_limit`).

Two entry points share one strategy: `check_token_rate_limits` checks the
all-models limits before a request runs, and `check_model_spend_limits` checks
the limits on one model once the request has picked it."""

from collections.abc import Sequence
from datetime import datetime, timezone
from enum import Enum
from math import ceil
from threading import RLock

from cachetools import TTLCache
from fastapi import Depends
from pydantic import BaseModel
from sqlalchemy import select

from onyx.auth.users import current_chat_accessible_user
from onyx.configs.constants import (
    TokenRateLimitAction,
    TokenRateLimitPeriod,
    TokenRateLimitScope,
)
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.llm import fetch_model_configuration_by_id
from onyx.db.models import TokenRateLimit, User
from onyx.db.token_limit import fetch_enforced_token_rate_limits
from onyx.db.user_usage import (
    TokenUsageBucket,
    get_period_window_reset,
    get_period_window_start,
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
    # NOTE: the flag is cached, so the no-limits case skips the DB.
    if not any_rate_limit_exists():
        return
    _run_spend_limit_check(user, None)


def check_model_spend_limits(user: User, model_configuration_id: int | None) -> None:
    """Enforce the limits on one model. A call that ran no saved configuration
    has nothing a model limit can name."""
    if model_configuration_id is None or not any_model_spend_limit_exists():
        return
    _run_spend_limit_check(user, model_configuration_id)


def _run_spend_limit_check(user: User, model_configuration_id: int | None) -> None:
    fetch_versioned_implementation(
        "onyx.server.query_and_chat.token_limit", _check_spend_limits.__name__
    )(user, model_configuration_id)


def _check_spend_limits(_: User, model_configuration_id: int | None) -> None:
    _user_is_rate_limited_by_global(model_configuration_id)


def check_global_token_rate_limits() -> None:
    """Enforce tenant-wide budgets without requiring a user principal."""
    if any_rate_limit_exists():
        _user_is_rate_limited_by_global(None)


"""
Budget windows
"""


class BudgetUnit(str, Enum):
    TOKENS = "TOKENS"
    COST = "COST"


class BudgetWindow(BaseModel):
    """One budget of one limit row: tokens or cents for a calendar period."""

    period: TokenRateLimitPeriod
    unit: BudgetUnit
    budget: float
    # Set when a group allowance, not the workspace default, supplied it.
    user_group_id: int | None = None


class WindowUsage(BaseModel):
    tokens: list[tuple[datetime, float]] = []
    cost_cents: list[tuple[datetime, float]] = []


def budget_windows(
    rate_limits: Sequence[TokenRateLimit], user_group_id: int | None = None
) -> list[BudgetWindow]:
    windows: list[BudgetWindow] = []
    for limit in rate_limits:
        # A non-positive token budget only comes from legacy rows; never block on it.
        if limit.token_budget is not None and limit.token_budget > 0:
            windows.append(
                BudgetWindow(
                    period=limit.period,
                    unit=BudgetUnit.TOKENS,
                    budget=limit.token_budget * TOKEN_BUDGET_UNIT,
                    user_group_id=user_group_id,
                )
            )
        if limit.cost_budget_cents is not None:
            windows.append(
                BudgetWindow(
                    period=limit.period,
                    unit=BudgetUnit.COST,
                    budget=limit.cost_budget_cents,
                    user_group_id=user_group_id,
                )
            )
    return windows


def resolve_member_allowance(
    default_limits: list[TokenRateLimit],
    member_limits_by_group: dict[int, list[TokenRateLimit]],
) -> list[BudgetWindow]:
    """The user's budget for each (period, unit): the largest among their
    groups that set it, else the workspace default. A group that doesn't set a
    bucket has no say in it."""
    allowance: dict[tuple[TokenRateLimitPeriod, BudgetUnit], BudgetWindow] = {}
    for group_id, limits in member_limits_by_group.items():
        for window in budget_windows(limits, user_group_id=group_id):
            key = (window.period, window.unit)
            current = allowance.get(key)
            if current is None or window.budget > current.budget:
                allowance[key] = window
    for window in budget_windows(default_limits):
        allowance.setdefault((window.period, window.unit), window)
    return list(allowance.values())


def usage_cutoff(
    now: datetime, windows: Sequence[BudgetWindow], unit: BudgetUnit
) -> datetime | None:
    """Earliest window start among the unit's budgets, so one fetch covers
    every window; None when no budget uses the unit."""
    starts = [
        get_period_window_start(now, window.period)
        for window in windows
        if window.unit == unit
    ]
    return min(starts) if starts else None


def token_buckets(usage: Sequence[TokenUsageBucket]) -> list[tuple[datetime, float]]:
    return [(bucket.window_start, float(bucket.tokens)) for bucket in usage]


def exhausted_windows(
    windows: Sequence[BudgetWindow], usage: WindowUsage
) -> list[tuple[BudgetWindow, datetime]]:
    """Each window whose current calendar period has used up its budget, with
    the time that period resets."""
    now = datetime.now(timezone.utc)
    exhausted: list[tuple[BudgetWindow, datetime]] = []
    for window in windows:
        buckets = usage.tokens if window.unit == BudgetUnit.TOKENS else usage.cost_cents
        cutoff = get_period_window_start(now, window.period)
        used = sum(amount for start, amount in buckets if start >= cutoff)
        if used >= window.budget:
            exhausted.append((window, get_period_window_reset(now, window.period)))
    return exhausted


def latest_reset(exhausted: Sequence[tuple[BudgetWindow, datetime]]) -> datetime | None:
    """The latest, so a client that waits it out doesn't re-trip a budget that
    clears later."""
    return max((reset for _, reset in exhausted), default=None)


def _token_budget_reset(
    rate_limits: Sequence[TokenRateLimit], usage: Sequence[TokenUsageBucket]
) -> datetime | None:
    windows = [
        window
        for window in budget_windows(rate_limits)
        if window.unit == BudgetUnit.TOKENS
    ]
    return latest_reset(
        exhausted_windows(windows, WindowUsage(tokens=token_buckets(usage)))
    )


def _cost_budget_reset(
    rate_limits: Sequence[TokenRateLimit],
    cost_buckets: Sequence[tuple[datetime, float]],
) -> datetime | None:
    windows = [
        window
        for window in budget_windows(rate_limits)
        if window.unit == BudgetUnit.COST
    ]
    return latest_reset(
        exhausted_windows(windows, WindowUsage(cost_cents=list(cost_buckets)))
    )


"""
Workspace pool
"""


def _user_is_rate_limited_by_global(model_configuration_id: int | None) -> None:
    with get_session_with_current_tenant() as db_session:
        windows = budget_windows(
            fetch_enforced_token_rate_limits(
                db_session, TokenRateLimitScope.GLOBAL, model_configuration_id
            )
        )
        if not windows:
            return

        now = datetime.now(timezone.utc)
        usage = WindowUsage()
        if token_cutoff := usage_cutoff(now, windows, BudgetUnit.TOKENS):
            usage.tokens = token_buckets(
                get_total_token_buckets_since(
                    db_session, token_cutoff, model_configuration_id
                )
            )
        if cost_cutoff := usage_cutoff(now, windows, BudgetUnit.COST):
            usage.cost_cents = get_total_cost_cents_buckets_since(
                db_session, cost_cutoff, model_configuration_id
            )

        if reset := latest_reset(exhausted_windows(windows, usage)):
            raise_rate_limited(
                TokenRateLimitScope.GLOBAL, reset, model_configuration_id
            )


"""
Errors
"""

# Human-readable subject for each scope, used only in the fallback message text.
# The machine-readable scope value goes in the structured `extra` payload.
_SCOPE_LABELS: dict[TokenRateLimitScope, str] = {
    TokenRateLimitScope.GLOBAL: "your organization",
    TokenRateLimitScope.USER: "your account",
    TokenRateLimitScope.USER_GROUP: "your user group",
    TokenRateLimitScope.USER_GROUP_MEMBER: "your group allowance",
}


def _model_label(model_configuration_id: int) -> str:
    with get_session_with_current_tenant() as db_session:
        model = fetch_model_configuration_by_id(db_session, model_configuration_id)
        if model is None:
            return str(model_configuration_id)
        return model.custom_display_name or model.display_name or model.name


def raise_rate_limited(
    scope: TokenRateLimitScope,
    reset_at: datetime,
    model_configuration_id: int | None = None,
) -> None:
    """Raise a structured 429 with the next relevant budget reset. A limit on
    one model names it in `extra.model`."""
    retry_after_seconds = max(
        1, ceil((reset_at - datetime.now(timezone.utc)).total_seconds())
    )
    extra: dict[str, object] = {
        "scope": scope.value,
        "reset_at": reset_at.isoformat(),
        "retry_after_seconds": retry_after_seconds,
    }
    subject = _SCOPE_LABELS[scope]
    message = f"You've reached the usage budget for {subject}."
    if model_configuration_id is not None:
        model = _model_label(model_configuration_id)
        extra["model"] = model
        message = f"You've reached the {model} budget for {subject}."
    raise OnyxError(
        OnyxErrorCode.RATE_LIMITED,
        # Neutral wording, no raw timestamp — the FE renders a friendly reset
        # time from reset_at / retry_after_seconds below.
        message,
        extra=extra,
        headers={"Retry-After": str(retry_after_seconds)},
    )


"""
Fast path
"""

_ANY_RATE_LIMIT_EXISTS_CACHE_TTL_SECONDS = 60
_any_rate_limit_exists_lock = RLock()
# (tenant_id, is_model_limit) -> whether that tenant has such an enforced limit.
# Keyed by tenant so one tenant's answer never suppresses another's enforcement
# in a shared worker. The short TTL bounds staleness across processes.
_any_rate_limit_exists_cache: TTLCache[tuple[str, bool], bool] = TTLCache(
    maxsize=10_000, ttl=_ANY_RATE_LIMIT_EXISTS_CACHE_TTL_SECONDS
)


def _enforced_limit_exists(is_model_limit: bool) -> bool:
    tenant_id = get_current_tenant_id()
    key = (tenant_id, is_model_limit)
    with _any_rate_limit_exists_lock:
        cached = _any_rate_limit_exists_cache.get(key)
    if cached is not None:
        return cached

    model_filter = (
        TokenRateLimit.model_configuration_id.is_not(None)
        if is_model_limit
        else TokenRateLimit.model_configuration_id.is_(None)
    )
    with get_session_with_current_tenant() as db_session:
        exists = (
            db_session.scalar(
                select(TokenRateLimit.id).where(
                    TokenRateLimit.enabled.is_(True),
                    TokenRateLimit.action == TokenRateLimitAction.BLOCK,
                    model_filter,
                )
            )
            is not None
        )

    with _any_rate_limit_exists_lock:
        _any_rate_limit_exists_cache[key] = exists
    return exists


def any_rate_limit_exists() -> bool:
    """Whether the current tenant enforces any all-models limit. Cached per
    tenant so the common no-limits case stays cheap on every chat request."""
    return _enforced_limit_exists(is_model_limit=False)


def any_model_spend_limit_exists() -> bool:
    return _enforced_limit_exists(is_model_limit=True)


def invalidate_any_rate_limit_exists_cache() -> None:
    """Drop the current tenant's cached flags after a limit write so the change
    is picked up on this process without waiting for the TTL."""
    tenant_id = get_current_tenant_id()
    with _any_rate_limit_exists_lock:
        for is_model_limit in (False, True):
            _any_rate_limit_exists_cache.pop((tenant_id, is_model_limit), None)
