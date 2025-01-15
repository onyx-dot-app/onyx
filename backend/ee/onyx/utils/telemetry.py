from typing import Any

from posthog import Posthog

from ee.onyx.configs.app_configs import POSTHOG_API_KEY
from ee.onyx.configs.app_configs import POSTHOG_HOST
from onyx.utils.logger import setup_logger

logger = setup_logger()


def posthog_on_error(error: Any, items: Any) -> None:
    """Log any PostHog delivery errors."""
    logger.error(f"PostHog error: {error}, items: {items}")


posthog = Posthog(
    project_api_key=POSTHOG_API_KEY,
    host=POSTHOG_HOST,
    debug=True,
    on_error=posthog_on_error,
)


def event_telemetry(
    distinct_id: str, event: str, properties: dict | None = None
) -> None:
    """Capture and send an event to PostHog, flushing immediately."""
    logger.info(f"Capturing PostHog event: {distinct_id} {event} {properties}")
    try:
        posthog.capture(distinct_id, event, properties)
        posthog.flush()
    except Exception as e:
        logger.error(f"Error capturing PostHog event: {e}")
