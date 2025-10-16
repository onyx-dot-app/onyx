from ee.onyx.feature_flags.posthog_provider import PostHogFeatureFlagProvider
from onyx.feature_flags.interface import FeatureFlagProvider


def get_posthog_feature_flag_provider() -> FeatureFlagProvider:
    """
    Get the PostHog feature flag provider instance.

    This is the EE implementation that gets loaded by the versioned
    implementation loader.

    Returns:
        PostHogFeatureFlagProvider: The PostHog-based feature flag provider
    """
    return PostHogFeatureFlagProvider()
