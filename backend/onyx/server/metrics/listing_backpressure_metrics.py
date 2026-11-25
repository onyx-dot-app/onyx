"""Prometheus metrics for the pauses of a listing that waits for the
conversion stage (``background/indexing/listing_backpressure.py``).

``source`` is a ``DocumentSource`` value. The listing runs in a spawned
docfetching process, so the child process relay carries these counters.
"""

from prometheus_client import Counter

LISTING_BACKPRESSURE_PAUSES = Counter(
    "onyx_listing_backpressure_pauses_total",
    "Times a listing paused so that the conversion stage could catch up",
    ["source"],
)

LISTING_BACKPRESSURE_PAUSED_SECONDS = Counter(
    "onyx_listing_backpressure_paused_seconds_total",
    "Time that listings paused for the conversion stage",
    ["source"],
)


def record_listing_pause(source: str) -> None:
    """Counts one pause, when it starts."""
    LISTING_BACKPRESSURE_PAUSES.labels(source=source).inc()


def record_listing_paused_seconds(source: str, seconds: float) -> None:
    """Adds paused time as the pause goes, so a long pause shows at once."""
    if seconds > 0:
        LISTING_BACKPRESSURE_PAUSED_SECONDS.labels(source=source).inc(seconds)
