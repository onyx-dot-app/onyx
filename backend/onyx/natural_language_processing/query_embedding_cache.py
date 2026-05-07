"""Tenant-scoped Redis/Postgres cache for query embeddings.

Sits in front of ``EmbeddingModel.encode`` for ``EmbedTextType.QUERY`` calls. A
cache hit avoids a network round-trip to the embedding provider.

Tenancy is handled by ``TenantRedis`` automatically prefixing every key with the
current tenant id, so two tenants never share an entry even if model id and
query text are identical. Model identity comes from ``search_settings.id`` —
``PRESERVED_SEARCH_FIELDS`` guarantees that every field that affects the
resulting vector is immutable for a given id, so a model swap allocates a new
row + new id and old entries simply expire.

Vectors are stored as packed little-endian ``float32`` (``4 * dim`` bytes); the
consumer already knows the dim from ``SearchSettings`` so no length prefix is
needed.
"""

import hashlib
import struct

from onyx.cache.factory import get_cache_backend
from onyx.cache.interface import CACHE_TRANSIENT_ERRORS
from onyx.server.metrics.embedding import observe_query_embedding_cache_lookup
from onyx.server.metrics.embedding import observe_query_embedding_cache_write
from onyx.server.metrics.embedding import QueryEmbeddingCacheLookupOutcome
from onyx.server.metrics.embedding import QueryEmbeddingCacheWriteOutcome
from onyx.utils.logger import setup_logger
from shared_configs.enums import EmbeddingProvider
from shared_configs.model_server_models import Embedding

logger = setup_logger()


_EMBEDDING_CACHE_KEY_PREFIX = "query_emb"


def _build_key(query: str, search_settings_id: int) -> str:
    digest = hashlib.sha256(query.encode("utf-8")).hexdigest()
    return f"{_EMBEDDING_CACHE_KEY_PREFIX}:{search_settings_id}:{digest}"


def _safe_pack_or_none(vector: Embedding) -> bytes | None:
    """Serializes an embedding to a little-endian float32 buffer.

    Args:
        vector: The embedding to serialize.

    Returns:
        The little-endian float32 buffer or None if the packing failed.
    """
    try:
        return struct.pack(f"<{len(vector)}f", *vector)
    except struct.error:
        logger.warning("Failed to pack embedding.", exc_info=True)
        return None


def _safe_unpack_or_none(buf: bytes) -> Embedding | None:
    """Deserializes a little-endian float32 buffer to an embedding.

    Args:
        buf: The little-endian float32 buffer to deserialize.

    Returns:
        The deserialized embedding or None if the unpacking failed.
    """
    if len(buf) % 4 != 0 or len(buf) == 0:
        logger.warning("Invalid embedding buffer length: %d bytes.", len(buf))
        return None
    try:
        num_floats = len(buf) // 4
        return list(struct.unpack(f"<{num_floats}f", buf))
    except struct.error:
        logger.warning("Failed to unpack embedding.", exc_info=True)
        return None


def get_cached_query_embeddings(
    queries: list[str],
    search_settings_id: int,
    provider_type: EmbeddingProvider | None,
    ttl_seconds: int,
) -> list[Embedding | None]:
    """Looks up each query in the cache.

    Returns a list aligned with ``queries``: ``Embedding`` for hits, ``None``
    for misses. On a hit, the entry's TTL is refreshed so hot keys stay resident
    and cold ones expire.

    Fails open: any ``CACHE_TRANSIENT_ERRORS`` is logged and treated as a miss
    for that query.

    Args:
        queries: The queries to look up.
        search_settings_id: The row ID of the search settings. NOTE: This is
            only uniquely-identifying within a tenant. This function must use a
            Redis client that is scoped to the current tenant.
        provider_type: The type of the embedding provider. Only used for
            observability.
        ttl_seconds: The TTL for the cache entries in seconds.

    Returns:
        The list of embeddings or None for misses.
    """
    if not queries:
        return []

    results: list[Embedding | None] = [None] * len(queries)
    try:
        cache_backend = get_cache_backend()
    except CACHE_TRANSIENT_ERRORS:
        logger.warning(
            "Failed to obtain cache backend for query embedding cache; "
            "treating all queries as misses.",
            exc_info=True,
        )
        observe_query_embedding_cache_lookup(
            provider_type,
            outcome=QueryEmbeddingCacheLookupOutcome.ERROR,
            count=len(queries),
        )
        return results

    hits = 0
    misses = 0
    errors = 0

    for i, query in enumerate(queries):
        key = _build_key(query, search_settings_id)
        try:
            raw = cache_backend.get(key)
        except CACHE_TRANSIENT_ERRORS:
            logger.warning(
                "Query embedding cache get failed; treating as miss.", exc_info=True
            )
            errors += 1
            continue

        if raw is None:
            misses += 1
            continue

        results[i] = _safe_unpack_or_none(raw)
        if results[i] is None:
            logger.warning(
                "Corrupt query embedding cache entry at %s; treating as miss.", key
            )
            misses += 1
            continue

        hits += 1
        # Refresh TTL by re-setting the value. ``backend.expire`` would be a
        # cheaper round trip but ``TenantRedis`` doesn't currently prefix
        # ``EXPIRE`` calls, so the EXPIRE would target the wrong key. Re-set is
        # one byte heavier on the wire and entirely safe.
        try:
            cache_backend.set(key, raw, ex=ttl_seconds)
        except CACHE_TRANSIENT_ERRORS:
            logger.debug("Failed to refresh TTL for %s.", key, exc_info=True)

    observe_query_embedding_cache_lookup(
        provider_type, outcome=QueryEmbeddingCacheLookupOutcome.HIT, count=hits
    )
    observe_query_embedding_cache_lookup(
        provider_type, outcome=QueryEmbeddingCacheLookupOutcome.MISS, count=misses
    )
    observe_query_embedding_cache_lookup(
        provider_type, outcome=QueryEmbeddingCacheLookupOutcome.ERROR, count=errors
    )

    logger.debug(
        "Query embedding cache lookup: hits=%d misses=%d errors=%d total=%d",
        hits,
        misses,
        errors,
        len(queries),
    )
    return results


def cache_query_embeddings(
    queries: list[str],
    embeddings: list[Embedding],
    search_settings_id: int,
    provider_type: EmbeddingProvider | None,
    ttl_seconds: int,
) -> None:
    """Writes each (query, embedding) pair into the cache with the given TTL.

    Fails open: any ``CACHE_TRANSIENT_ERRORS`` is logged and swallowed so cache
    write errors never break a search.

    Args:
        queries: The queries to cache.
        embeddings: The embeddings to cache.
        search_settings_id: The row ID of the search settings. NOTE: This is
            only uniquely-identifying within a tenant. This function must use a
            Redis client that is scoped to the current tenant.
        provider_type: The type of the embedding provider. Only used for
            observability.
        ttl_seconds: The TTL for the cache entries in seconds.

    Raises:
        ValueError: If the length of ``queries`` and ``embeddings`` are not the
            same.
    """
    if not queries:
        return

    if len(queries) != len(embeddings):
        raise ValueError(
            f"queries ({len(queries)}) and embeddings ({len(embeddings)}) "
            "must be the same length."
        )

    try:
        cache_backend = get_cache_backend()
    except CACHE_TRANSIENT_ERRORS:
        logger.warning(
            "Failed to obtain cache backend for query embedding cache write.",
            exc_info=True,
        )
        observe_query_embedding_cache_write(
            provider_type,
            outcome=QueryEmbeddingCacheWriteOutcome.ERROR,
            count=len(queries),
        )
        return

    successes = 0
    errors = 0
    for query, embedding in zip(queries, embeddings):
        key = _build_key(query, search_settings_id)
        try:
            packed = _safe_pack_or_none(embedding)
            if packed is None:
                errors += 1
                continue
            cache_backend.set(key, packed, ex=ttl_seconds)
            successes += 1
        except CACHE_TRANSIENT_ERRORS:
            logger.warning(
                "Query embedding cache set failed; continuing.", exc_info=True
            )
            errors += 1

    observe_query_embedding_cache_write(
        provider_type,
        outcome=QueryEmbeddingCacheWriteOutcome.SUCCESS,
        count=successes,
    )
    observe_query_embedding_cache_write(
        provider_type, outcome=QueryEmbeddingCacheWriteOutcome.ERROR, count=errors
    )


def record_cache_skipped(provider_type: EmbeddingProvider | None, count: int) -> None:
    """
    Records that the cache was skipped for ``count`` queries (e.g. because the
    kill-switch is off, or no ``search_settings`` was available).
    """
    observe_query_embedding_cache_lookup(
        provider_type,
        outcome=QueryEmbeddingCacheLookupOutcome.SKIPPED,
        count=count,
    )
