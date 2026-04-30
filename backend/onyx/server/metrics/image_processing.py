"""Prometheus metrics for image processing during document indexing.

Tracks the size of images being processed and the latency of LLM
summarization calls in ``process_image_sections``.
"""

from prometheus_client import Counter
from prometheus_client import Histogram

_IMAGE_SIZE_BUCKETS = (
    1_000,
    10_000,
    50_000,
    100_000,
    500_000,
    1_000_000,
    5_000_000,
    10_000_000,
)

_LLM_LATENCY_BUCKETS = (
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
    25.0,
    60.0,
)

onyx_image_size_bytes = Histogram(
    "onyx_image_size_bytes",
    "Size of images processed during indexing, in bytes.",
    buckets=_IMAGE_SIZE_BUCKETS,
)

onyx_image_summarization_duration_seconds = Histogram(
    "onyx_image_summarization_duration_seconds",
    "Latency of LLM image summarization calls, in seconds.",
    buckets=_LLM_LATENCY_BUCKETS,
)

onyx_image_summarization_total = Counter(
    "onyx_image_summarization_total",
    "Total successful image summarizations.",
)
