from ee.onyx.feature_flags.posthog_provider import PostHogFeatureFlagProvider
from ee.onyx.utils.posthog_client import posthog
from onyx.feature_flags.interface import FeatureFlagProvider
from onyx.feature_flags.interface import NoOpFeatureFlagProvider


def get_posthog_feature_flag_provider() -> FeatureFlagProvider:
    """
    Get the PostHog feature flag provider instance.

    This is the EE implementation that gets loaded by the versioned
    implementation loader.

    When the PostHog client isn't configured (no `POSTHOG_API_KEY` — the
    standard local-dev state), return a NoOp provider so env-var-driven
    flag fallbacks (e.g. `ENABLE_CRAFT`) take effect. A real PostHog
    provider with no client would silently answer `False` for every flag,
    which masks env-var intent.
    """
    if posthog is None:
        return NoOpFeatureFlagProvider()
    return PostHogFeatureFlagProvider()
