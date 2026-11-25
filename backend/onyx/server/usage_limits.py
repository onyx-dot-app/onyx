"""Usage limits enforcement for cloud deployments.

A ``LimitPolicy`` is everything one plan allows: for each usage type, an
``Allowance`` that says how much, over what window, whose usage counts, where
the usage is read from, and which field of cloud's override record can replace
the amount for one tenant. Every one of those can differ between policies.
Cloud has two policies, trial and paid; the plan is picked per tenant.

``check_usage_and_raise`` is the one enforcement path; the entry points call it
or ``check_llm_cost_limit_for_provider``.

An override is an absolute value that replaces the policy's amount, never an
amount added to it. A value of ``NO_LIMIT`` (-1) means unlimited, 0 means
nothing is allowed (the trial API-call default), and an unset override means
"use the policy". A usage type a policy does not list is unlimited under it.
"""

from collections.abc import Callable
from enum import Enum

from pydantic import BaseModel, ConfigDict, model_validator
from sqlalchemy.orm import Session

from onyx.configs.app_configs import (
    ANTHROPIC_DEFAULT_API_KEY,
    COHERE_DEFAULT_API_KEY,
    OPENAI_DEFAULT_API_KEY,
    OPENROUTER_DEFAULT_API_KEY,
)
from onyx.db.usage import UsageLimitExceededError, UsageType, check_usage_limit
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.tenant_usage_limits import (
    TenantUsageLimitKeys,
    TenantUsageLimitOverrides,
)
from onyx.utils.logger import setup_logger
from onyx.utils.variable_functionality import fetch_versioned_implementation
from shared_configs.configs import (
    USAGE_LIMIT_API_CALLS_PAID,
    USAGE_LIMIT_API_CALLS_TRIAL,
    USAGE_LIMIT_CHUNKS_INDEXED_PAID,
    USAGE_LIMIT_CHUNKS_INDEXED_TRIAL,
    USAGE_LIMIT_LLM_COST_CENTS_PAID,
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


class LimitScope(str, Enum):
    """Whose usage a limit counts."""

    TENANT = "tenant"


class LimitMeasure(str, Enum):
    """Where a limit's current usage is read from."""

    # A tenant_usage column. Checked before the call, added after it, so one
    # call can pass the line; callers that need an exact stop pass the amount
    # they are about to use as ``pending_amount``.
    COUNTER = "counter"


class WindowAnchor(str, Enum):
    """Where a limit's windows are counted from."""

    # A grid shared by every tenant, from ``onyx.db.usage.get_current_window_start``:
    # with the default USAGE_LIMIT_WINDOW_SECONDS, the calendar week from Monday
    # 00:00 UTC. Not counted from the tenant's sign-up.
    CALENDAR = "calendar"


class LimitWindow(BaseModel):
    """The period a limit's usage is counted over before it starts from zero."""

    model_config = ConfigDict(frozen=True)

    anchor: WindowAnchor
    # Length of one window. None means one window that never resets.
    length_seconds: int | None = None

    @model_validator(mode="after")
    def _calendar_has_length(self) -> "LimitWindow":
        if self.anchor == WindowAnchor.CALENDAR and self.length_seconds is None:
            raise ValueError("A calendar window needs a length")
        return self


# Cloud's window today: the tenant_usage grid.
CALENDAR_WEEK = LimitWindow(
    anchor=WindowAnchor.CALENDAR, length_seconds=USAGE_LIMIT_WINDOW_SECONDS
)


class LimitPolicyName(str, Enum):
    """The plans a tenant can be held to. Fixed in code; one ``LimitPolicy`` each."""

    CLOUD_TRIAL = "cloud_trial"
    CLOUD_PAID = "cloud_paid"


class Allowance(BaseModel):
    """One usage type under one policy: how much, over what window, whose usage,
    read from where, and which override field can replace the amount."""

    model_config = ConfigDict(frozen=True)

    # NO_LIMIT for unlimited, 0 for nothing allowed.
    limit: int
    scope: LimitScope = LimitScope.TENANT
    measure: LimitMeasure = LimitMeasure.COUNTER
    # Required for a COUNTER; it names the tenant_usage row the count lives in.
    window: LimitWindow | None = None
    # Field of cloud's override record that replaces ``limit`` for one tenant.
    override_field: TenantUsageLimitKeys | None = None

    @model_validator(mode="after")
    def _counter_has_window(self) -> "Allowance":
        if self.measure == LimitMeasure.COUNTER and self.window is None:
            raise ValueError("A counter allowance needs a window")
        return self


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


class LimitPolicy(BaseModel):
    """Everything one plan allows. A usage type with no allowance is unlimited."""

    model_config = ConfigDict(frozen=True)

    name: LimitPolicyName
    allowances: dict[UsageType, Allowance]


# One line per limited usage type. Adding a limit to a plan is one line here;
# removing it is deleting the line.
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


def policy_for_plan(is_trial: bool) -> LimitPolicy:
    """The policy a cloud tenant is held to, by its billing status."""
    return CLOUD_TRIAL if is_trial else CLOUD_PAID


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
) -> None:
    """Read the usage the allowance points at and raise
    ``UsageLimitExceededError`` when usage plus ``pending_amount`` is over
    ``limit``."""
    if allowance.measure == LimitMeasure.COUNTER:
        check_usage_limit(
            db_session=db_session,
            usage_type=usage_type,
            limit=limit,
            pending_amount=pending_amount,
        )
        return
    raise NotImplementedError(f"No measurement for {allowance.measure}")


def _refusal_detail(
    usage_type: UsageType, is_trial: bool, e: UsageLimitExceededError
) -> str:
    user_type = "trial" if is_trial else "paid"
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

    Raises:
        HTTPException: 429 Too Many Requests if limit exceeded
    """
    if not is_usage_limits_enabled():
        return

    is_trial = is_tenant_on_trial_fn(tenant_id)
    allowance = policy_for_plan(is_trial).allowances.get(usage_type)
    if allowance is None:
        return
    limit = get_limit_for_usage_type(usage_type, is_trial, tenant_id)
    logger.debug("Checking usage limit for %s.%s: %s", usage_type, is_trial, limit)

    # NO_LIMIT means this tenant has unlimited usage for this type
    if limit == NO_LIMIT:
        return

    try:
        _measure_and_check(db_session, usage_type, allowance, limit, pending_amount)
    except UsageLimitExceededError as e:
        raise OnyxError(
            OnyxErrorCode.RATE_LIMITED, _refusal_detail(usage_type, is_trial, e)
        )
