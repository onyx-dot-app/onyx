"""Cache enriched passage vectors without merging source documents."""

import hashlib
import math
import struct
from collections.abc import Callable

from onyx.cache.factory import get_cache_backend
from onyx.cache.interface import CACHE_TRANSIENT_ERRORS
from onyx.utils.logger import setup_logger
from shared_configs.model_server_models import Embedding

logger = setup_logger()


def embed_cached_passages(
    texts: list[str],
    encode: Callable[[list[str]], list[Embedding]],
    scope: str,
    dimension: int,
    tenant_id: str | None,
    ttl_seconds: int,
) -> list[Embedding]:
    """Encode unique misses, then restore input order, including duplicates.

    The caller supplies a scope for the settings generation and encode options.
    CacheBackend owns tenant isolation and expiry. A cache outage bypasses all
    further cache operations in this batch to avoid a timeout for every chunk.
    """
    if not texts:
        return []
    unique_texts = list(dict.fromkeys(texts))
    keys = {
        text: f"passage_emb:v2:{scope}:{hashlib.sha256(text.encode('utf-8', errors='surrogatepass')).hexdigest()}"
        for text in unique_texts
    }
    vectors: dict[str, Embedding] = {}
    try:
        cache = get_cache_backend(tenant_id=tenant_id, operation_timeout_s=0.2)
        for text in unique_texts:
            raw = cache.get(keys[text])
            if raw is not None and len(raw) == dimension * 4:
                vector = list(struct.unpack(f"<{dimension}f", raw))
                if all(math.isfinite(value) for value in vector):
                    vectors[text] = vector
    except CACHE_TRANSIENT_ERRORS:
        logger.warning(
            "Passage embedding cache unavailable; encoding misses.", exc_info=True
        )
        cache = None

    misses = [text for text in unique_texts if text not in vectors]
    if misses:
        fresh = encode(misses)
        if len(fresh) != len(misses):
            raise ValueError("Embedding count does not match the passage count")
        for vector in fresh:
            if len(vector) != dimension or not all(math.isfinite(v) for v in vector):
                raise ValueError("Invalid passage embedding dimension or value")
        for text, vector in zip(misses, fresh, strict=True):
            vectors[text] = vector
            if cache is not None:
                try:
                    packed = struct.pack(f"<{dimension}f", *vector)
                    cache.set(keys[text], packed, ex=ttl_seconds)
                except (struct.error, OverflowError):
                    logger.warning("Cannot serialize passage embedding.", exc_info=True)
                except CACHE_TRANSIENT_ERRORS:
                    logger.warning(
                        "Passage embedding cache write failed.", exc_info=True
                    )
                    cache = None

    return [list(vectors[text]) for text in texts]
