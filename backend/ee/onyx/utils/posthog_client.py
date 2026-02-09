import json
from typing import Any
from urllib.parse import unquote

from posthog import Posthog

from ee.onyx.configs.app_configs import MARKETING_POSTHOG_API_KEY
from ee.onyx.configs.app_configs import POSTHOG_API_KEY
from ee.onyx.configs.app_configs import POSTHOG_DEBUG_LOGS_ENABLED
from ee.onyx.configs.app_configs import POSTHOG_HOST
from onyx.utils.logger import setup_logger

logger = setup_logger()


def posthog_on_error(error: Any, items: Any) -> None:
    """Log any PostHog delivery errors."""
    logger.error(f"PostHog error: {error}, items: {items}")


# This module intentionally lives under `utils` (rather than `feature_flags`) because
# PostHog is used by more than feature flags:
# - Feature flag evaluation
# - Cloud telemetry capture
# - Marketing cookie/identity syncing

# These flags are disabled by default when PostHog is not configured.
POSTHOG_DISABLED_DEFAULT_OFF_FLAGS = frozenset(
    {
        # Build mode access should stay disabled unless explicitly enabled.
        "onyx-craft-enabled",
        # Build mode rate limits should stay off unless explicitly enabled.
        "craft-has-usage-limits",
    }
)


def default_feature_enabled_when_posthog_disabled(flag_key: str) -> bool:
    """
    Default behavior for feature flags when PostHog is not configured.

    Most flags default to True to avoid blocking functionality, while selected
    safety/rollout flags default to False.
    """
    return flag_key not in POSTHOG_DISABLED_DEFAULT_OFF_FLAGS


class NoOpPosthogClient:
    """No-op PostHog client used when POSTHOG_API_KEY is not configured."""

    def identify(self, *args: Any, **kwargs: Any) -> None:  # noqa: ARG002
        return None

    def capture(self, *args: Any, **kwargs: Any) -> None:  # noqa: ARG002
        return None

    def flush(self, *args: Any, **kwargs: Any) -> None:  # noqa: ARG002
        return None

    def set(self, *args: Any, **kwargs: Any) -> None:  # noqa: ARG002
        return None

    def feature_enabled(
        self, flag_key: str, *args: Any, **kwargs: Any  # noqa: ARG002
    ) -> bool:
        return default_feature_enabled_when_posthog_disabled(flag_key)


POSTHOG_ENABLED = bool(POSTHOG_API_KEY)

posthog: Posthog | NoOpPosthogClient
if POSTHOG_ENABLED:
    posthog = Posthog(
        project_api_key=POSTHOG_API_KEY,
        host=POSTHOG_HOST,
        debug=POSTHOG_DEBUG_LOGS_ENABLED,
        on_error=posthog_on_error,
    )
else:
    posthog = NoOpPosthogClient()
    logger.info("PostHog is disabled because POSTHOG_API_KEY is not set.")

# For cross referencing between cloud and www Onyx sites
# NOTE: These clients are separate because they are separate posthog projects.
# We should eventually unify them into a single posthog project,
# which would no longer require this workaround
marketing_posthog = None
if MARKETING_POSTHOG_API_KEY:
    marketing_posthog = Posthog(
        project_api_key=MARKETING_POSTHOG_API_KEY,
        host=POSTHOG_HOST,
        debug=POSTHOG_DEBUG_LOGS_ENABLED,
        on_error=posthog_on_error,
    )


def capture_and_sync_with_alternate_posthog(
    alternate_distinct_id: str, event: str, properties: dict[str, Any]
) -> None:
    """
    Identify in both PostHog projects and capture the event in marketing.
    - Marketing keeps the marketing distinct_id (for feature flags).
    - Cloud identify uses the cloud distinct_id
    """
    if not marketing_posthog:
        return

    props = properties.copy()

    try:
        marketing_posthog.identify(distinct_id=alternate_distinct_id, properties=props)
        marketing_posthog.capture(alternate_distinct_id, event, props)
        marketing_posthog.flush()
    except Exception as e:
        logger.error(f"Error capturing marketing posthog event: {e}")

    try:
        if cloud_user_id := props.get("onyx_cloud_user_id"):
            cloud_props = props.copy()
            cloud_props.pop("onyx_cloud_user_id", None)

            posthog.identify(
                distinct_id=cloud_user_id,
                properties=cloud_props,
            )
    except Exception as e:
        logger.error(f"Error identifying cloud posthog user: {e}")


def get_marketing_posthog_cookie_name() -> str | None:
    if not MARKETING_POSTHOG_API_KEY:
        return None
    return f"onyx_custom_ph_{MARKETING_POSTHOG_API_KEY}_posthog"


def parse_marketing_cookie(cookie_value: str) -> dict[str, Any] | None:
    """
    Parse the URL-encoded JSON marketing cookie.

    Expected format (URL-encoded):
    {"distinct_id":"...", "featureFlags":{"landing_page_variant":"..."}, ...}

    Returns:
        Dict with 'distinct_id' explicitly required and all other cookie values
        passed through as-is, or None if parsing fails or distinct_id is missing.
    """
    try:
        decoded_cookie = unquote(cookie_value)
        cookie_data = json.loads(decoded_cookie)

        distinct_id = cookie_data.get("distinct_id")
        if not distinct_id:
            return None

        return cookie_data
    except (json.JSONDecodeError, KeyError, TypeError, AttributeError) as e:
        logger.warning(f"Failed to parse cookie: {e}")
        return None
