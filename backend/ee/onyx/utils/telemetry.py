from typing import Any

from ee.onyx.utils.posthog_client import posthog
from onyx.utils.client_ip import current_client_ip
from onyx.utils.logger import setup_logger

logger = setup_logger()


def _with_client_ip(
    properties: dict[str, Any] | None, client_ip: str | None
) -> dict[str, Any] | None:
    """Merge the client IP into properties as ``$ip`` so PostHog's GeoIP
    enricher populates ``$geoip_*`` fields. Server-side captures otherwise
    attribute every event to the pod's own outbound IP.

    Resolution order: explicit ``client_ip`` > per-request contextvar (set by
    ``ClientIPMiddleware``) > nothing. An explicit value always wins so
    callers with a more specific IP (e.g. replaying a stored event) can
    override the ambient request IP.
    """
    effective_ip = client_ip or current_client_ip()
    if not effective_ip:
        return properties
    merged = dict(properties) if properties else {}
    merged.setdefault("$ip", effective_ip)
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
