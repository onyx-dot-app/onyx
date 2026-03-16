from ee.onyx.utils.posthog_client import posthog
from onyx.utils.logger import setup_logger

logger = setup_logger()


def event_telemetry(
    distinct_id: str, event: str, properties: dict | None = None
) -> None:
    """Capture and send an event to PostHog, flushing immediately."""
    if not posthog:
        return

    logger.info(f"Capturing PostHog event: {distinct_id} {event} {properties}")
    try:
        posthog.capture(distinct_id, event, properties)
        posthog.flush()
    except Exception as e:
        logger.error(f"Error capturing PostHog event: {e}")


def identify_user(distinct_id: str, properties: dict | None = None) -> None:
    """Create/update a PostHog person profile, flushing immediately."""
    if not posthog:
        return

    try:
        posthog.identify(distinct_id, properties)
        posthog.flush()
    except Exception as e:
        logger.error(f"Error identifying PostHog user: {e}")
