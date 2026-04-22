from typing import Any

from ee.onyx.utils.posthog_client import posthog
from onyx.utils.logger import setup_logger

logger = setup_logger()


def _with_client_ip(
    properties: dict[str, Any] | None, client_ip: str | None
) -> dict[str, Any] | None:
    """Merge the caller-supplied client IP into properties as ``$ip`` so that
    PostHog's GeoIP enricher populates ``$geoip_*`` fields. Server-side
    captures otherwise attribute every event to the pod's own outbound IP.
    """
    if not client_ip:
        return properties
    merged = dict(properties) if properties else {}
    merged.setdefault("$ip", client_ip)
    return merged


def event_telemetry(
    distinct_id: str,
    event: str,
    properties: dict[str, Any] | None = None,
    client_ip: str | None = None,
) -> None:
    """Capture and send an event to PostHog, flushing immediately."""
    if not posthog:
        return

    enriched = _with_client_ip(properties, client_ip)
    logger.info(f"Capturing PostHog event: {distinct_id} {event} {enriched}")
    try:
        posthog.capture(distinct_id, event, enriched)
        posthog.flush()
    except Exception as e:
        logger.error(f"Error capturing PostHog event: {e}")


def identify_user(
    distinct_id: str,
    properties: dict[str, Any] | None = None,
    client_ip: str | None = None,
) -> None:
    """Create/update a PostHog person profile, flushing immediately."""
    if not posthog:
        return

    enriched = _with_client_ip(properties, client_ip)
    try:
        posthog.identify(distinct_id, enriched)
        posthog.flush()
    except Exception as e:
        logger.error(f"Error identifying PostHog user: {e}")
