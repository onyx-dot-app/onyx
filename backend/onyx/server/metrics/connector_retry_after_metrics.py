"""Prometheus metrics for long server-supplied connector retry delays.

Labels are low cardinality: ``source`` is a fixed connector family name and
``wait_class`` is one of ``over_1m``, ``over_5m`` or ``capped``. No tenant label.
"""

from prometheus_client import Counter

from onyx.utils.logger import setup_logger

logger = setup_logger()

CONNECTOR_LONG_RETRY_AFTER = Counter(
    "onyx_connector_long_retry_after_total",
    "Server-supplied connector retry delays over 1 minute, over 5 minutes, or capped",
    ["source", "wait_class"],
)


def inc_connector_long_retry_after(source: str, wait_class: str) -> None:
    try:
        CONNECTOR_LONG_RETRY_AFTER.labels(source=source, wait_class=wait_class).inc()
    except Exception:
        logger.debug("Failed to record connector long retry-after", exc_info=True)
