from typing import Any

from ee.onyx.utils.posthog_client import posthog
from onyx.utils.client_ip import current_client_ip
from onyx.utils.logger import setup_logger

logger = setup_logger()


def _with_client_ip(
    properties: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Merge the current-request client IP into properties as ``$ip`` so
    PostHog's GeoIP enricher populates ``$geoip_*`` fields. Server-side
    captures otherwise attribute every event to the pod's own outbound IP.

    The IP is read from the contextvar set by ``ClientIPMiddleware``; it
    is ``None`` outside a request (e.g. Celery), in which case ``$ip``
    is not added and the payload shape stays unchanged.
    """
    ip = current_client_ip()
    if not ip:
        return properties
    merged = dict(properties) if properties else {}
    merged.setdefault("$ip", ip)
    return merged


def event_telemetry(
    distinct_id: str,
    event: str,
    properties: dict[str, Any] | None = None,
) -> None:
    """Capture and send an event to PostHog, flushing immediately."""
    if not posthog:
        return

    enriched = _with_client_ip(properties)
    # Log the pre-enrichment properties so the real client IP (PII) never
    # reaches the application log aggregator. PostHog itself still receives
    # the enriched payload via the capture call below.
    logger.info("Capturing PostHog event: %s %s %s", distinct_id, event, properties)
    try:
        posthog.capture(distinct_id, event, enriched)
        posthog.flush()
    except Exception as e:
        logger.error("Error capturing PostHog event: %s", e)


def identify_user(
    distinct_id: str,
    properties: dict[str, Any] | None = None,
) -> None:
    """Create/update a PostHog person profile, flushing immediately."""
    if not posthog:
        return

    enriched = _with_client_ip(properties)
    try:
        posthog.identify(distinct_id, enriched)
        posthog.flush()
    except Exception as e:
        logger.error("Error identifying PostHog user: %s", e)
