from onyx.feature_flags.interface import FeatureFlagProvider
from onyx.feature_flags.interface import NoOpFeatureFlagProvider
from onyx.utils.variable_functionality import (
    fetch_versioned_implementation_with_fallback,
)
from shared_configs.configs import MULTI_TENANT


def get_default_feature_flag_provider() -> FeatureFlagProvider:
    """
    Get the default feature flag provider implementation.

    Returns the PostHog-based provider in Enterprise Edition when available,
    otherwise returns a no-op provider that always returns False.

    This function is designed for dependency injection - callers should
    use this factory rather than directly instantiating providers.

    Returns:
        FeatureFlagProvider: The configured feature flag provider instance
    """
    if MULTI_TENANT:
        return fetch_versioned_implementation_with_fallback(
            module="onyx.feature_flags.factory",
            attribute="get_posthog_feature_flag_provider",
            fallback=lambda: NoOpFeatureFlagProvider(),
        )()
    return NoOpFeatureFlagProvider()
