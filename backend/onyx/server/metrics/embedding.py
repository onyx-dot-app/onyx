"""Prometheus metrics for embedding generation latency and throughput.

Tracks client-side round-trip latency (as seen by callers of
``EmbeddingModel.encode``) and server-side execution time (as measured inside
the model server for the local-model path). Both API-provider and local-model
paths flow through the client-side metric; only the local path populates the
server-side metric.
"""

import logging
from collections.abc import Generator
from contextlib import contextmanager

from prometheus_client import Counter
from prometheus_client import Gauge
from prometheus_client import Histogram

from shared_configs.enums import EmbeddingProvider
from shared_configs.enums import EmbedTextType

logger = logging.getLogger(__name__)

LOCAL_PROVIDER_LABEL = "local"

_EMBEDDING_LATENCY_BUCKETS = (
    0.005,
    0.01,
    0.025,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
    25.0,
)

PROVIDER_LABEL_NAME = "provider"
TEXT_TYPE_LABEL_NAME = "text_type"
STATUS_LABEL_NAME = "status"

_client_duration = Histogram(
    "onyx_embedding_client_duration_seconds",
    "Client-side end-to-end latency of an embedding batch as seen by the caller.",
    [PROVIDER_LABEL_NAME, TEXT_TYPE_LABEL_NAME],
    buckets=_EMBEDDING_LATENCY_BUCKETS,
)

_embedding_requests_total = Counter(
    "onyx_embedding_requests_total",
    "Total embedding batch requests, labeled by outcome.",
    [PROVIDER_LABEL_NAME, TEXT_TYPE_LABEL_NAME, STATUS_LABEL_NAME],
)

_embedding_texts_total = Counter(
    "onyx_embedding_texts_total",
    "Total number of individual texts submitted for embedding.",
    [PROVIDER_LABEL_NAME, TEXT_TYPE_LABEL_NAME],
)

_embedding_input_chars_total = Counter(
    "onyx_embedding_input_chars_total",
    "Total number of input characters submitted for embedding.",
    [PROVIDER_LABEL_NAME, TEXT_TYPE_LABEL_NAME],
)

_embeddings_in_progress = Gauge(
    "onyx_embeddings_in_progress",
    "Number of embedding batches currently in-flight.",
    [PROVIDER_LABEL_NAME, TEXT_TYPE_LABEL_NAME],
)


def provider_label(provider: EmbeddingProvider | None) -> str:
    if provider is None:
        return LOCAL_PROVIDER_LABEL
    return provider.value


def observe_embedding_client(
    provider: EmbeddingProvider | None,
    text_type: EmbedTextType,
    duration_s: float,
    num_texts: int,
    num_chars: int,
    success: bool,
) -> None:
    """Records a completed embedding batch.

    Args:
        provider: The embedding provider, or ``None`` for the local model path.
        text_type: Whether this was a query- or passage-style embedding.
        duration_s: Wall-clock duration measured on the client side, in seconds.
        num_texts: Number of texts in the batch.
        num_chars: Total number of input characters in the batch.
        success: Whether the embedding call succeeded.
    """
    try:
        provider_lbl = provider_label(provider)
        text_type_lbl = text_type.value
        status_lbl = "success" if success else "failure"

        _embedding_requests_total.labels(
            provider=provider_lbl, text_type=text_type_lbl, status=status_lbl
        ).inc()
        _client_duration.labels(provider=provider_lbl, text_type=text_type_lbl).observe(
            duration_s
        )
        if success:
            _embedding_texts_total.labels(
                provider=provider_lbl, text_type=text_type_lbl
            ).inc(num_texts)
            _embedding_input_chars_total.labels(
                provider=provider_lbl, text_type=text_type_lbl
            ).inc(num_chars)
    except Exception:
        logger.warning("Failed to record embedding client metrics.", exc_info=True)


@contextmanager
def track_embedding_in_progress(
    provider: EmbeddingProvider | None,
    text_type: EmbedTextType,
) -> Generator[None, None, None]:
    """Context manager that tracks in-flight embedding batches via a Gauge."""
    incremented = False
    provider_lbl = provider_label(provider)
    text_type_lbl = text_type.value
    try:
        _embeddings_in_progress.labels(
            provider=provider_lbl, text_type=text_type_lbl
        ).inc()
        incremented = True
    except Exception:
        logger.warning(
            "Failed to increment in-progress embedding gauge.", exc_info=True
        )
    try:
        yield
    finally:
        if incremented:
            try:
                _embeddings_in_progress.labels(
                    provider=provider_lbl, text_type=text_type_lbl
                ).dec()
            except Exception:
                logger.warning(
                    "Failed to decrement in-progress embedding gauge.", exc_info=True
                )
