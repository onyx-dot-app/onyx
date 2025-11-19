from ee.onyx.utils.posthog_client import posthog
from onyx.utils.logger import setup_logger

logger = setup_logger()


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
