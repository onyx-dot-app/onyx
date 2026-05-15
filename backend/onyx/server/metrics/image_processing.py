import bisect
import functools
import inspect
import io
import logging
import time
from collections.abc import Callable
from typing import ParamSpec
from typing import TypeVar

from prometheus_client import Counter
from prometheus_client import Histogram

logger = logging.getLogger(__name__)

P = ParamSpec("P")
R = TypeVar("R")

_SIZE_TIERS = (10_000, 100_000, 1_000_000, 5_000_000)
_SIZE_TIER_LABELS = ("< 10KB", "10KB-100KB", "100KB-1MB", "1MB-5MB", ">= 5MB")

_DIM_TIERS = (128, 512, 1024, 2048, 4096)
_DIM_TIER_LABELS = ("< 128", "128-512", "512-1024", "1024-2048", "2048-4096", ">= 4096")

_LLM_LATENCY_BUCKETS = (
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
    25.0,
    60.0,
)

_LABEL_NAMES = ["size_bucket", "width_bucket", "height_bucket"]


def _size_tier(size_bytes: int) -> str:
    return _SIZE_TIER_LABELS[bisect.bisect_right(_SIZE_TIERS, size_bytes)]


def _dim_tier(pixels: int) -> str:
    return _DIM_TIER_LABELS[bisect.bisect_right(_DIM_TIERS, pixels)]


_image_summarization_duration_seconds = Histogram(
    "onyx_image_summarization_duration_seconds",
    "Latency of LLM image summarization calls, in seconds.",
    _LABEL_NAMES,
    buckets=_LLM_LATENCY_BUCKETS,
)

_image_summarization_total = Counter(
    "onyx_image_summarization_total",
    "Total image summarizations processed.",
    _LABEL_NAMES,
)


def track_image_summarization(
    fn: Callable[P, R],
) -> Callable[P, R]:
    """Decorator that records image metrics around an image summarization function.

    Looks for an ``image_data`` parameter (positional or keyword) containing
    the raw image bytes. If found, records size and dimension labels. Always
    records the wall-clock duration of the wrapped call.
    """

    @functools.wraps(fn)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        bound = inspect.signature(fn).bind(*args, **kwargs)
        bound.apply_defaults()
        image_data: bytes | None = bound.arguments.get("image_data")  # type: ignore[assignment]

        labels: dict[str, str] = {
            "size_bucket": "unknown",
            "width_bucket": "unknown",
            "height_bucket": "unknown",
        }
        if image_data is not None:
            try:
                from PIL import Image

                labels["size_bucket"] = _size_tier(len(image_data))
                with Image.open(io.BytesIO(image_data)) as img:
                    w, h = img.size
                labels["width_bucket"] = _dim_tier(w)
                labels["height_bucket"] = _dim_tier(h)
            except Exception:
                logger.warning(
                    "Failed to record image processing metrics.", exc_info=True
                )

        try:
            # Metrics for all images that attempt to get processed
            # We want to know the size distribution
            _image_summarization_total.labels(**labels).inc()
        except Exception:
            logger.warning(
                "Failed to record image summarization metrics.", exc_info=True
            )

        start = time.monotonic()
        result = fn(*args, **kwargs)
        elapsed = time.monotonic() - start

        try:
            # Metrics for how long image X took to upload plus the details about it
            _image_summarization_duration_seconds.labels(**labels).observe(elapsed)
        except Exception:
            logger.warning(
                "Failed to record image summarization metrics.", exc_info=True
            )

        return result

    return wrapper
