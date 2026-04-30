import functools
import inspect
import io
import logging
import time
from collections.abc import Callable
from typing import ParamSpec
from typing import TypeVar

from prometheus_client import Histogram

logger = logging.getLogger(__name__)

P = ParamSpec("P")
R = TypeVar("R")

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

_IMAGE_DIMENSION_BUCKETS = (
    32,
    64,
    128,
    256,
    512,
    1024,
    2048,
    4096,
    8192,
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

_image_size_bytes = Histogram(
    "onyx_image_size_bytes",
    "Size of images processed during indexing, in bytes.",
    buckets=_IMAGE_SIZE_BUCKETS,
)

_image_width_pixels = Histogram(
    "onyx_image_width_pixels",
    "Width of images processed during indexing, in pixels.",
    buckets=_IMAGE_DIMENSION_BUCKETS,
)

_image_height_pixels = Histogram(
    "onyx_image_height_pixels",
    "Height of images processed during indexing, in pixels.",
    buckets=_IMAGE_DIMENSION_BUCKETS,
)

_image_summarization_duration_seconds = Histogram(
    "onyx_image_summarization_duration_seconds",
    "Latency of LLM image summarization calls, in seconds.",
    buckets=_LLM_LATENCY_BUCKETS,
)


def track_image_summarization(
    fn: Callable[P, R],
) -> Callable[P, R]:
    """Decorator that records image metrics around an image summarization function.

    Looks for an ``image_data`` parameter (positional or keyword) containing
    the raw image bytes. If found, records size and dimensions. Always records
    the wall-clock duration of the wrapped call.
    """

    @functools.wraps(fn)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        bound = inspect.signature(fn).bind(*args, **kwargs)
        bound.apply_defaults()
        image_data: bytes | None = bound.arguments.get("image_data")  # type: ignore[assignment]

        if image_data is not None:
            try:
                from PIL import Image

                _image_size_bytes.observe(len(image_data))
                img = Image.open(io.BytesIO(image_data))
                w, h = img.size
                _image_width_pixels.observe(w)
                _image_height_pixels.observe(h)
            except Exception:
                logger.warning(
                    "Failed to record image processing metrics.", exc_info=True
                )

        start = time.monotonic()
        result = fn(*args, **kwargs)
        elapsed = time.monotonic() - start

        try:
            _image_summarization_duration_seconds.observe(elapsed)
        except Exception:
            logger.warning(
                "Failed to record image summarization metrics.", exc_info=True
            )

        return result

    return wrapper
