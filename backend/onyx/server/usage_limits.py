"""Usage limits enforcement for cloud deployments."""

from collections.abc import Callable

from fastapi import HTTPException
from sqlalchemy.orm import Session

from onyx.configs.app_configs import ANTHROPIC_DEFAULT_API_KEY
from onyx.configs.app_configs import COHERE_DEFAULT_API_KEY
from onyx.configs.app_configs import OPENAI_DEFAULT_API_KEY
from onyx.configs.app_configs import OPENROUTER_DEFAULT_API_KEY
from onyx.db.usage import check_usage_limit
from onyx.db.usage import UsageLimitExceededError
from onyx.db.usage import UsageType
from onyx.server.tenant_usage_limits import TenantUsageLimitKeys
from onyx.server.tenant_usage_limits import TenantUsageLimitOverrides
from onyx.utils.logger import setup_logger
from onyx.utils.variable_functionality import fetch_versioned_implementation
from shared_configs.configs import USAGE_LIMIT_API_CALLS_PAID
from shared_configs.configs import USAGE_LIMIT_API_CALLS_TRIAL
from shared_configs.configs import USAGE_LIMIT_CHUNKS_INDEXED_PAID
from shared_configs.configs import USAGE_LIMIT_CHUNKS_INDEXED_TRIAL
from shared_configs.configs import USAGE_LIMIT_LLM_COST_CENTS_PAID
from shared_configs.configs import USAGE_LIMIT_LLM_COST_CENTS_TRIAL
from shared_configs.configs import USAGE_LIMIT_NON_STREAMING_CALLS_PAID
from shared_configs.configs import USAGE_LIMIT_NON_STREAMING_CALLS_TRIAL
from shared_configs.configs import USAGE_LIMITS_ENABLED

logger = setup_logger()

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


def is_onyx_managed_api_key(api_key: str | None) -> bool:
    """Check if the given API key is one of Onyx's managed default keys."""
    return bool(api_key) and api_key in _ONYX_MANAGED_API_KEYS


def is_usage_limits_enabled() -> bool:
    """Check if usage limits are enabled for this deployment."""
    return USAGE_LIMITS_ENABLED


def is_tenant_on_trial(tenant_id: str) -> bool:
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
        - None: No override specified, use default env var value
    """
    try:
        # Try to get EE version that has tenant overrides
        get_overrides_fn = fetch_versioned_implementation(
            "onyx.server.tenant_usage_limits", "get_tenant_usage_limit_overrides"
        )
        overrides: TenantUsageLimitOverrides | None = get_overrides_fn(tenant_id)

        if overrides is not None:
            # Get the field value - None means not set, use default
            return getattr(overrides, field_name, None)
    except Exception:
        logger.exception(
            "Error getting tenant override for %s.%s falling back to defaults",
            tenant_id,
            field_name,
        )
    return None


# Special value meaning "no limit" (unlimited)
NO_LIMIT = -1
_FIELD_AND_DEFAULT = {
    UsageType.LLM_COST: {
        True: (
            TenantUsageLimitKeys.LLM_COST_CENTS_TRIAL,
            USAGE_LIMIT_LLM_COST_CENTS_TRIAL,
        ),
        False: (
            TenantUsageLimitKeys.LLM_COST_CENTS_PAID,
            USAGE_LIMIT_LLM_COST_CENTS_PAID,
        ),
    },
    UsageType.CHUNKS_INDEXED: {
        True: (
            TenantUsageLimitKeys.CHUNKS_INDEXED_TRIAL,
            USAGE_LIMIT_CHUNKS_INDEXED_TRIAL,
        ),
        False: (
            TenantUsageLimitKeys.CHUNKS_INDEXED_PAID,
            USAGE_LIMIT_CHUNKS_INDEXED_PAID,
        ),
    },
    UsageType.API_CALLS: {
        True: (TenantUsageLimitKeys.API_CALLS_TRIAL, USAGE_LIMIT_API_CALLS_TRIAL),
        False: (TenantUsageLimitKeys.API_CALLS_PAID, USAGE_LIMIT_API_CALLS_PAID),
    },
    UsageType.NON_STREAMING_API_CALLS: {
        True: (
            TenantUsageLimitKeys.NON_STREAMING_CALLS_TRIAL,
            USAGE_LIMIT_NON_STREAMING_CALLS_TRIAL,
        ),
        False: (
            TenantUsageLimitKeys.NON_STREAMING_CALLS_PAID,
            USAGE_LIMIT_NON_STREAMING_CALLS_PAID,
        ),
    },
}


def get_limit_for_usage_type(
    usage_type: UsageType, is_trial: bool, tenant_id: str | None
) -> int:
    """
    Get the appropriate limit based on usage type, trial status, and tenant overrides.

    Returns:
        - Positive int: The usage limit
        - NO_LIMIT (-1): No limit (unlimited) for this tenant
    """

    field_name, default_value = _FIELD_AND_DEFAULT[usage_type][is_trial]
    if tenant_id:
        override = _get_tenant_override(tenant_id, field_name)
        if override is not None:
            logger.debug(
                "Using tenant override for %s.%s: %s", tenant_id, field_name, override
            )
            return override
    logger.debug(
        "Using default value for %s.%s: %s", usage_type, is_trial, default_value
    )
    return default_value


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


def check_usage_and_raise(
    db_session: Session,
    usage_type: UsageType,
    tenant_id: str,
    pending_amount: float | int = 0,
) -> None:
    """
    Check if usage limit would be exceeded and raise HTTPException if so.

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
    limit = get_limit_for_usage_type(usage_type, is_trial, tenant_id)
    logger.debug("Checking usage limit for %s.%s: %s", usage_type, is_trial, limit)

    # NO_LIMIT means this tenant has unlimited usage for this type
    if limit == NO_LIMIT:
        return

    try:
        check_usage_limit(
            db_session=db_session,
            usage_type=usage_type,
            limit=limit,
            pending_amount=pending_amount,
        )
    except UsageLimitExceededError as e:
        user_type = "trial" if is_trial else "paid"
        if usage_type == UsageType.LLM_COST:
            detail = (
                f"LLM usage limit exceeded for {user_type} account. "
                f"Current cost: ${e.current / 100:.2f}, "
                f"Limit: ${e.limit / 100:.2f} per week. "
                "Please use your own LLM API key, upgrade your plan,"
                " or wait for the next billing period (1 week)."
            )
        elif usage_type == UsageType.CHUNKS_INDEXED:
            detail = (
                f"Document indexing limit exceeded for {user_type} account. "
                f"Indexed: {int(e.current)} chunks, Limit: {int(e.limit)} per week. "
                "Please upgrade your plan or wait for the next billing period."
            )
        elif usage_type == UsageType.API_CALLS:
            detail = (
                f"API call limit exceeded for {user_type} account. "
                f"Calls: {int(e.current)}, Limit: {int(e.limit)} per week. "
                "Please upgrade your plan or wait for the next billing period."
            )
        else:
            detail = (
                f"Non-streaming API call limit exceeded for {user_type} account. "
                f"Calls: {int(e.current)}, Limit: {int(e.limit)} per week. "
                "Please upgrade your plan or wait for the next billing period."
            )

        raise HTTPException(status_code=429, detail=detail)
