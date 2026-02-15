from ee.onyx.configs.app_configs import POSTHOG_API_KEY
from onyx.feature_flags.interface import FeatureFlagProvider
from onyx.feature_flags.interface import NoOpFeatureFlagProvider


def get_posthog_feature_flag_provider() -> FeatureFlagProvider:
    """
    Get the PostHog feature flag provider instance.

    This is the EE implementation that gets loaded by the versioned
    implementation loader.

    Returns:
        PostHogFeatureFlagProvider: The PostHog-based feature flag provider
    """
    if not POSTHOG_API_KEY:
        return NoOpFeatureFlagProvider()

    from ee.onyx.feature_flags.posthog_provider import PostHogFeatureFlagProvider

    return PostHogFeatureFlagProvider()
