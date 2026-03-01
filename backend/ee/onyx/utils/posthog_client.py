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


def _build_posthog_client(project_api_key: str | None) -> Posthog | None:
    if not project_api_key:
        return None

    return Posthog(
        project_api_key=project_api_key,
        host=POSTHOG_HOST,
        debug=POSTHOG_DEBUG_LOGS_ENABLED,
        on_error=posthog_on_error,
    )


posthog = _build_posthog_client(POSTHOG_API_KEY)

# For cross referencing between cloud and www Onyx sites
# NOTE: These clients are separate because they are separate posthog projects.
# We should eventually unify them into a single posthog project,
# which would no longer require this workaround
marketing_posthog = _build_posthog_client(MARKETING_POSTHOG_API_KEY)


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
            if not posthog:
                return

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
