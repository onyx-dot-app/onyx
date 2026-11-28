"""Usage limits for tenants that use Onyx's own LLM keys.

Each plan has a policy. A policy has one allowance per limit: how much is
allowed, and over what period. Cloud has two plans, trial and paid. The
playground has one plan for every tenant.

``check_usage_and_raise`` checks a limit. ``record_usage`` adds usage.

Limit values:
- -1 (``NO_LIMIT``) means no limit.
- 0 means nothing is allowed.
- A limit that a plan does not list is not limited on that plan.

A tenant override replaces the plan's value. It is not added to it.
"""

import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy.orm import Session

from onyx.configs.app_configs import (
    ANTHROPIC_DEFAULT_API_KEY,
    COHERE_DEFAULT_API_KEY,
    OPENAI_DEFAULT_API_KEY,
    OPENROUTER_DEFAULT_API_KEY,
)
from onyx.db import usage as tenant_usage_db
from onyx.db.usage import (
    UsageLimitExceededError,
    UsagePeriod,
    UsageType,
    check_usage_limit,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.models import (
    Allowance,
    LimitMeasure,
    LimitPolicy,
    LimitPolicyName,
    LimitScope,
    LimitWindow,
    WindowAnchor,
)
from onyx.server.tenant_usage_limits import (
    TenantUsageLimitKeys,
    TenantUsageLimitOverrides,
)
from onyx.utils.datetime import get_window_start
from onyx.utils.logger import setup_logger
from onyx.utils.variable_functionality import fetch_versioned_implementation
from shared_configs.configs import (
    IS_PLAYGROUND,
    USAGE_LIMIT_API_CALLS_PAID,
    USAGE_LIMIT_API_CALLS_TRIAL,
    USAGE_LIMIT_CHUNKS_INDEXED_PAID,
    USAGE_LIMIT_CHUNKS_INDEXED_PLAYGROUND,
    USAGE_LIMIT_CHUNKS_INDEXED_TRIAL,
    USAGE_LIMIT_IMAGE_GENERATIONS_PER_USER_PLAYGROUND,
    USAGE_LIMIT_LLM_COST_CENTS_PAID,
    USAGE_LIMIT_LLM_COST_CENTS_PLAYGROUND,
    USAGE_LIMIT_LLM_COST_CENTS_TRIAL,
    USAGE_LIMIT_NON_STREAMING_CALLS_PAID,
    USAGE_LIMIT_NON_STREAMING_CALLS_TRIAL,
    USAGE_LIMIT_WINDOW_SECONDS,
    USAGE_LIMITS_ENABLED,
)

logger = setup_logger()

# Special value meaning "no limit" (unlimited)
NO_LIMIT = -1

# Collect all Onyx-managed default API keys for comparison
_ONYX_MANAGED_API_KEYS: set[str] = set()
for key in [
    OPENAI_DEFAULT_API_KEY,
    ANTHROPIC_DEFAULT_API_KEY,
    COHERE_DEFAULT_API_KEY,
    OPENROUTER_DEFAULT_API_KEY,
]:
    if key:
        _ONYX_MANAGED_API_KEYS.add(key)


# Calendar week, Monday 00:00 UTC. The same for all tenants. Used by cloud.
CALENDAR_WEEK = LimitWindow(
    anchor=WindowAnchor.CALENDAR, length_seconds=USAGE_LIMIT_WINDOW_SECONDS
)
# 7 days at a time, starting from the tenant's trial start.
TENANT_WEEK = LimitWindow(anchor=WindowAnchor.TENANT_START, length_seconds=7 * 86400)
# The whole trial. Never resets.
WHOLE_TRIAL = LimitWindow(anchor=WindowAnchor.TENANT_START)


def _weekly_tenant_counter(
    limit: int, override_field: TenantUsageLimitKeys
) -> Allowance:
    return Allowance(
        limit=limit,
        scope=LimitScope.TENANT,
        measure=LimitMeasure.COUNTER,
        window=CALENDAR_WEEK,
        override_field=override_field,
    )


def _tenant_counter(limit: int, window: LimitWindow) -> Allowance:
    return Allowance(
        limit=limit,
        scope=LimitScope.TENANT,
        measure=LimitMeasure.COUNTER,
        window=window,
    )


# One line per limit. To add a limit to a plan, add a line. To remove it,
# delete the line.
CLOUD_TRIAL = LimitPolicy(
    name=LimitPolicyName.CLOUD_TRIAL,
    allowances={
        UsageType.LLM_COST: _weekly_tenant_counter(
            USAGE_LIMIT_LLM_COST_CENTS_TRIAL, TenantUsageLimitKeys.LLM_COST_CENTS_TRIAL
        ),
        UsageType.CHUNKS_INDEXED: _weekly_tenant_counter(
            USAGE_LIMIT_CHUNKS_INDEXED_TRIAL, TenantUsageLimitKeys.CHUNKS_INDEXED_TRIAL
        ),
        UsageType.API_CALLS: _weekly_tenant_counter(
            USAGE_LIMIT_API_CALLS_TRIAL, TenantUsageLimitKeys.API_CALLS_TRIAL
        ),
        UsageType.NON_STREAMING_API_CALLS: _weekly_tenant_counter(
            USAGE_LIMIT_NON_STREAMING_CALLS_TRIAL,
            TenantUsageLimitKeys.NON_STREAMING_CALLS_TRIAL,
        ),
    },
)

CLOUD_PAID = LimitPolicy(
    name=LimitPolicyName.CLOUD_PAID,
    allowances={
        UsageType.LLM_COST: _weekly_tenant_counter(
            USAGE_LIMIT_LLM_COST_CENTS_PAID, TenantUsageLimitKeys.LLM_COST_CENTS_PAID
        ),
        UsageType.CHUNKS_INDEXED: _weekly_tenant_counter(
            USAGE_LIMIT_CHUNKS_INDEXED_PAID, TenantUsageLimitKeys.CHUNKS_INDEXED_PAID
        ),
        UsageType.API_CALLS: _weekly_tenant_counter(
            USAGE_LIMIT_API_CALLS_PAID, TenantUsageLimitKeys.API_CALLS_PAID
        ),
        UsageType.NON_STREAMING_API_CALLS: _weekly_tenant_counter(
            USAGE_LIMIT_NON_STREAMING_CALLS_PAID,
            TenantUsageLimitKeys.NON_STREAMING_CALLS_PAID,
        ),
    },
)


# Every playground tenant gets this plan. API calls are not limited here,
# because messages sent with personal tokens count as messages.
PLAYGROUND = LimitPolicy(
    name=LimitPolicyName.PLAYGROUND,
    allowances={
        UsageType.LLM_COST: _tenant_counter(
            USAGE_LIMIT_LLM_COST_CENTS_PLAYGROUND, TENANT_WEEK
        ),
        UsageType.CHUNKS_INDEXED: _tenant_counter(
            USAGE_LIMIT_CHUNKS_INDEXED_PLAYGROUND, WHOLE_TRIAL
        ),
        # Per user, for the whole trial: a derived count has no window, and a
        # playground tenant exists only for its trial.
        UsageType.IMAGE_GENERATIONS: Allowance(
            limit=USAGE_LIMIT_IMAGE_GENERATIONS_PER_USER_PLAYGROUND,
            scope=LimitScope.USER,
            measure=LimitMeasure.DERIVED,
        ),
    },
)


# Usage types cloud limits. Any other type is not checked on cloud at all.
_CLOUD_LIMITED_USAGE_TYPES = frozenset(CLOUD_TRIAL.allowances) | frozenset(
    CLOUD_PAID.allowances
)


def is_usage_type_limited(usage_type: UsageType) -> bool:
    """Whether any plan in force limits this usage type. Needs no lookup, so a
    caller can skip opening a session for a type nothing limits."""
    if not is_usage_limits_enabled():
        return False
    if IS_PLAYGROUND:
        return usage_type in PLAYGROUND.allowances
    return usage_type in _CLOUD_LIMITED_USAGE_TYPES


def _require_cloud_plans_share_windows() -> None:
    """``record_usage`` does not know if a cloud tenant is on trial or paid, so
    it uses the trial plan's periods. This is only correct if both cloud plans
    use the same period for each limit. Stop at startup if they do not."""
    for usage_type in set(CLOUD_TRIAL.allowances) | set(CLOUD_PAID.allowances):
        trial = CLOUD_TRIAL.allowances.get(usage_type)
        paid = CLOUD_PAID.allowances.get(usage_type)
        if (trial and trial.window) != (paid and paid.window):
            raise ValueError(
                f"Cloud trial and paid must use the same period for {usage_type.value}"
            )


_require_cloud_plans_share_windows()


def policy_for_plan(is_trial: bool) -> LimitPolicy:
    """The plan for a tenant. On the playground, always ``PLAYGROUND``."""
    if IS_PLAYGROUND:
        return PLAYGROUND
    return CLOUD_TRIAL if is_trial else CLOUD_PAID


# The plan whose periods ``record_usage`` uses. On cloud, the trial plan: trial
# and paid use the same periods, so we do not need to look up which one the
# tenant is on.
_INCREMENT_POLICY = PLAYGROUND if IS_PLAYGROUND else CLOUD_TRIAL


def tenant_trial_start(tenant_id: str) -> datetime | None:  # noqa: ARG001
    """When the tenant's trial started. Periods that count from the trial start
    begin here. The EE version reads it from the control plane; without EE
    there is no trial start."""
    return None


def tenant_trial_start_fn(tenant_id: str) -> datetime | None:
    fn: Callable[[str], datetime | None] = fetch_versioned_implementation(
        "onyx.server.usage_limits", "tenant_trial_start"
    )
    return fn(tenant_id)


def tenant_limit_override(
    tenant_id: str,  # noqa: ARG001
    usage_type: UsageType,  # noqa: ARG001
) -> int | None:
    """A playground tenant's override for one usage type. The EE version reads
    it from the control plane; without EE there are none."""
    return None


def tenant_limit_override_fn(tenant_id: str, usage_type: UsageType) -> int | None:
    fn: Callable[[str, UsageType], int | None] = fetch_versioned_implementation(
        "onyx.server.usage_limits", "tenant_limit_override"
    )
    return fn(tenant_id, usage_type)


# When each tenant was last warned about a missing trial start, so the warning
# appears at most once an hour per tenant in each process. Kept in memory on
# purpose: a few duplicate log lines across processes cost less than a shared
# cache write on every period lookup.
_TRIAL_START_WARNING_INTERVAL_SECONDS = 3600
_trial_start_warned_at: dict[str, float] = {}


def _warn_missing_trial_start(tenant_id: str) -> None:
    now = time.monotonic()
    last = _trial_start_warned_at.get(tenant_id)
    if last is not None and now - last < _TRIAL_START_WARNING_INTERVAL_SECONDS:
        return
    _trial_start_warned_at[tenant_id] = now
    logger.warning(
        "Tenant %s has no valid trial start. Limits that count from the trial "
        "start use calendar periods of the same length, or one period that "
        "never ends for a whole-trial limit.",
        tenant_id,
    )


# Where a whole-trial limit counts while the tenant's trial start is unknown.
_NO_TRIAL_START_WHOLE_TRIAL = UsagePeriod(
    anchor=WindowAnchor.CALENDAR, start=datetime(1970, 1, 1, tzinfo=timezone.utc)
)


def _calendar_period(now: datetime, length_seconds: int) -> UsagePeriod:
    start = get_window_start(now, length_seconds)
    return UsagePeriod(
        anchor=WindowAnchor.CALENDAR,
        start=start,
        end=start + timedelta(seconds=length_seconds),
    )


def period_for(
    window: LimitWindow, tenant_id: str, now: datetime | None = None
) -> UsagePeriod:
    """The current period for this window. Checking and adding usage both use
    this, so they always read and write the same row."""
    now = now or datetime.now(timezone.utc)
    if window.anchor == WindowAnchor.CALENDAR:
        if window.length_seconds is None:
            raise RuntimeError("A calendar period needs a length")
        return _calendar_period(now, window.length_seconds)

    trial_start = tenant_trial_start_fn(tenant_id)
    if trial_start is None or trial_start.utcoffset() is None or trial_start > now:
        # No usable trial start. The tenant stays limited: a limit with a length
        # uses calendar periods of that length (the calendar week for 7 days),
        # and a whole-trial limit counts in one period that never ends, so it
        # cannot reset every week.
        _warn_missing_trial_start(tenant_id)
        if window.length_seconds is None:
            return _NO_TRIAL_START_WHOLE_TRIAL
        return _calendar_period(now, window.length_seconds)
    if window.length_seconds is None:
        return UsagePeriod(anchor=WindowAnchor.TENANT_START, start=trial_start)
    period_length = timedelta(seconds=window.length_seconds)
    full_periods_passed = (now - trial_start) // period_length
    start = trial_start + full_periods_passed * period_length
    return UsagePeriod(
        anchor=WindowAnchor.TENANT_START, start=start, end=start + period_length
    )


def record_usage(
    db_session: Session,
    usage_type: UsageType,
    amount: float | int,
    tenant_id: str,
) -> None:
    """Add usage to the row for the current period. The caller commits."""
    allowance = _INCREMENT_POLICY.allowances.get(usage_type)
    if allowance is not None and allowance.measure == LimitMeasure.DERIVED:
        # A derived count reads rows that already exist; nothing to add.
        return
    period = None
    if (
        allowance is not None
        and allowance.measure == LimitMeasure.COUNTER
        and allowance.window is not None
    ):
        period = period_for(allowance.window, tenant_id)
    tenant_usage_db.increment_usage(db_session, usage_type, amount, period)


"""
Enforcement
"""


def is_onyx_managed_api_key(api_key: str | None) -> bool:
    """Check if the given API key is one of Onyx's managed default keys."""
    return bool(api_key) and api_key in _ONYX_MANAGED_API_KEYS


def is_usage_limits_enabled() -> bool:
    """Check if usage limits are enabled for this deployment."""
    return USAGE_LIMITS_ENABLED


def is_tenant_on_trial(tenant_id: str) -> bool:  # noqa: ARG001
    """
    Determine if a tenant is currently on a trial subscription.

    Non-EE version always returns False. EE version fetches billing information
    from the control plane to determine if the tenant has an active trial.
    """
    return False


def is_tenant_on_trial_fn(tenant_id: str) -> bool:
    """
    Get the versioned implementation of is_tenant_on_trial and call it.

    Uses fetch_versioned_implementation to get the EE version if available,
    otherwise falls back to the non-EE version that returns False.
    """
    fn: Callable[[str], bool] = fetch_versioned_implementation(
        "onyx.server.usage_limits", "is_tenant_on_trial"
    )
    return fn(tenant_id)


def _get_tenant_override(tenant_id: str, field_name: str) -> int | None:
    """
    Get a tenant-specific usage limit override if available.

    Uses fetch_versioned_implementation to get EE version if available.

    Returns:
        - Positive int: Use this specific limit
        - -1 (NO_LIMIT): No limit (unlimited)
        - None: No override specified, use the policy's amount
    """
    try:
        # Try to get EE version that has tenant overrides
        get_overrides_fn = fetch_versioned_implementation(
            "onyx.server.tenant_usage_limits", "get_tenant_usage_limit_overrides"
        )
        overrides: TenantUsageLimitOverrides | None = get_overrides_fn(tenant_id)

        if overrides is not None:
            # Get the field value - None means not set, use default
            return getattr(overrides, field_name, None)  # ods: ignore[getattr]
    except Exception:
        logger.exception(
            "Error getting tenant override for %s.%s falling back to defaults",
            tenant_id,
            field_name,
        )
    return None


def get_limit_for_usage_type(
    usage_type: UsageType, is_trial: bool, tenant_id: str | None
) -> int:
    """
    The allowed value for one limit: the tenant's override if it has one, else
    the amount from the policy its plan selects.

    Returns:
        - Positive int: The usage limit
        - NO_LIMIT (-1): No limit (unlimited) for this tenant
    """
    policy = policy_for_plan(is_trial)
    allowance = policy.allowances.get(usage_type)
    if allowance is None:
        return NO_LIMIT
    # A playground override comes from the control plane through the cache.
    if policy.name == LimitPolicyName.PLAYGROUND:
        override = (
            tenant_limit_override_fn(tenant_id, usage_type) if tenant_id else None
        )
        if override is not None:
            logger.debug(
                "Using playground override for %s.%s: %s",
                tenant_id,
                usage_type,
                override,
            )
            return override
        return allowance.limit
    if tenant_id and allowance.override_field is not None:
        field_name = allowance.override_field.value
        override = _get_tenant_override(tenant_id, field_name)
        if override is not None:
            logger.debug(
                "Using tenant override for %s.%s: %s", tenant_id, field_name, override
            )
            return override
    logger.debug(
        "Using %s value for %s: %s", policy.name.value, usage_type, allowance.limit
    )
    return allowance.limit


def check_llm_cost_limit_for_provider(
    db_session: Session,
    tenant_id: str,
    llm_provider_api_key: str | None,
) -> None:
    """
    Check if the LLM cost limit would be exceeded for a provider using Onyx-managed keys.

    Only enforces limits when the provider uses Onyx-managed API keys.
    Users with their own API keys are not subject to LLM cost limits.

    Args:
        db_session: Database session for the tenant
        tenant_id: The tenant ID for trial detection
        llm_provider_api_key: The API key of the LLM provider that will be used

    Raises:
        HTTPException: 429 Too Many Requests if limit exceeded
    """
    if not is_usage_limits_enabled():
        return

    # Only enforce limits for Onyx-managed API keys
    if not is_onyx_managed_api_key(llm_provider_api_key):
        return

    check_usage_and_raise(
        db_session=db_session,
        usage_type=UsageType.LLM_COST,
        tenant_id=tenant_id,
        pending_amount=0,  # We check current usage, not pending
    )


def _measure_and_check(
    db_session: Session,
    usage_type: UsageType,
    allowance: Allowance,
    limit: int,
    pending_amount: float | int,
    tenant_id: str,
    user_id: UUID | None,
) -> None:
    """Read the current usage. Raise ``UsageLimitExceededError`` if usage plus
    ``pending_amount`` is more than ``limit``."""
    if allowance.measure == LimitMeasure.DERIVED:
        used = _derived_usage(db_session, usage_type, user_id)
        if used + pending_amount > limit:
            raise UsageLimitExceededError(
                usage_type=usage_type,
                current=used + pending_amount,
                limit=float(limit),
            )
        return
    if allowance.measure == LimitMeasure.COUNTER:
        if allowance.window is None:
            raise RuntimeError(f"The {usage_type.value} counter has no period set")
        check_usage_limit(
            db_session=db_session,
            usage_type=usage_type,
            limit=limit,
            pending_amount=pending_amount,
            period=period_for(allowance.window, tenant_id),
        )
        return
    raise NotImplementedError(f"No measurement for {allowance.measure}")


def _derived_usage(
    db_session: Session, usage_type: UsageType, user_id: UUID | None
) -> int:
    """The current usage of a derived limit, counted from existing rows."""
    if usage_type == UsageType.IMAGE_GENERATIONS:
        if user_id is None:
            raise RuntimeError("A per-user image count needs the user")
        return tenant_usage_db.count_generated_images(db_session, user_id)
    raise NotImplementedError(f"No derived count for {usage_type.value}")


def _refusal_detail(
    usage_type: UsageType, is_trial: bool, e: UsageLimitExceededError
) -> str:
    user_type = "trial" if is_trial else "paid"
    if usage_type == UsageType.IMAGE_GENERATIONS:
        return (
            f"You have used your {int(e.limit)} images for this trial. "
            "Talk to sales to raise the limit."
        )
    if usage_type == UsageType.LLM_COST:
        return (
            f"LLM usage limit exceeded for {user_type} account. "
            f"Current cost: ${e.current / 100:.2f}, "
            f"Limit: ${e.limit / 100:.2f} per week. "
            "Please use your own LLM API key, upgrade your plan,"
            " or wait for the next billing period (1 week)."
        )
    if usage_type == UsageType.CHUNKS_INDEXED:
        return (
            f"Document indexing limit exceeded for {user_type} account. "
            f"Indexed: {int(e.current)} chunks, Limit: {int(e.limit)} per week. "
            "Please upgrade your plan or wait for the next billing period."
        )
    if usage_type == UsageType.API_CALLS:
        if is_trial and e.limit == 0:
            return "API access is not available on trial accounts. Please upgrade to a paid plan to use the API and chat widget."
        return (
            f"API call limit exceeded for {user_type} account. "
            f"Calls: {int(e.current)}, Limit: {int(e.limit)} per week. "
            "Please upgrade your plan or wait for the next billing period."
        )
    return (
        f"Non-streaming API call limit exceeded for {user_type} account. "
        f"Calls: {int(e.current)}, Limit: {int(e.limit)} per week. "
        "Please upgrade your plan or wait for the next billing period."
    )


def check_usage_and_raise(
    db_session: Session,
    usage_type: UsageType,
    tenant_id: str,
    pending_amount: float | int = 0,
    user_id: UUID | None = None,
) -> None:
    """
    The one enforcement path. Resolves the limit's allowed value, reads its
    usage the way its policy's allowance says, and raises a 429 when usage plus
    ``pending_amount`` is over the line.

    Args:
        db_session: Database session for the tenant
        usage_type: Type of usage to check
        tenant_id: The tenant ID for trial detection
        pending_amount: Amount about to be used
        user_id: The user, for a limit that counts each user's own usage

    Raises:
        HTTPException: 429 Too Many Requests if limit exceeded
    """
    # A type no plan in force limits needs no billing lookup or query.
    if not is_usage_type_limited(usage_type):
        return

    # Playground tenants have no billing plan, so do not look it up.
    is_trial = True if IS_PLAYGROUND else is_tenant_on_trial_fn(tenant_id)
    allowance = policy_for_plan(is_trial).allowances.get(usage_type)
    if allowance is None:
        return
    if allowance.scope == LimitScope.USER and user_id is None:
        # Nobody to count for, such as a bot with no Onyx user. The tenant's
        # spend limit still applies.
        return
    limit = get_limit_for_usage_type(usage_type, is_trial, tenant_id)
    logger.debug("Checking usage limit for %s.%s: %s", usage_type, is_trial, limit)

    # NO_LIMIT means this tenant has unlimited usage for this type
    if limit == NO_LIMIT:
        return

    try:
        _measure_and_check(
            db_session,
            usage_type,
            allowance,
            limit,
            pending_amount,
            tenant_id,
            user_id,
        )
    except UsageLimitExceededError as e:
        raise OnyxError(
            OnyxErrorCode.RATE_LIMITED, _refusal_detail(usage_type, is_trial, e)
        )
