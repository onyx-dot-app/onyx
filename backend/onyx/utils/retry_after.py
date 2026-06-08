import math
from datetime import datetime
from datetime import timezone
from email.utils import parsedate_to_datetime

from onyx.utils.logger import setup_logger

logger = setup_logger()


def parse_retry_after_seconds(value: str | None) -> float | None:
    """Parse an HTTP ``Retry-After`` header value into seconds to wait.

    RFC 9110 allows two forms:
    - delay-seconds: a non-negative number of seconds (e.g. ``"120"``).
    - HTTP-date: an absolute instant (e.g. ``"Wed, 21 Oct 2015 07:28:00 GMT"``),
      converted to seconds from now and floored at 0 for already-elapsed dates.

    Returns ``None`` when the value is missing or unparseable, so callers can
    fall back to their own backoff strategy.
    """
    if value is None:
        return None

    text = value.strip()
    if not text:
        return None

    # The spec says integer, but some servers send floats. Reject nan/inf
    try:
        seconds = float(text)
    except ValueError:
        seconds = None
    if seconds is not None:
        return max(seconds, 0.0) if math.isfinite(seconds) else None

    # HTTP-date form.
    try:
        retry_at = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        logger.debug("Failed to parse Retry-After header '%s'", text)
        return None

    if retry_at is None:
        logger.debug("Failed to parse Retry-After header '%s'", text)
        return None

    # parsedate_to_datetime returns a naive datetime when the date carries no
    # timezone; RFC dates are GMT, so treat that as UTC.
    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=timezone.utc)

    delta_seconds = (retry_at - datetime.now(timezone.utc)).total_seconds()
    return max(delta_seconds, 0.0)
