"""Tests for the query embedding cache module against a real cache backend."""

from unittest.mock import patch
from uuid import uuid4

from prometheus_client import REGISTRY
from redis.exceptions import RedisError

from onyx.cache.factory import get_cache_backend
from onyx.natural_language_processing.query_embedding_cache import _build_key
from onyx.natural_language_processing.query_embedding_cache import (
    cache_query_embeddings,
)
from onyx.natural_language_processing.query_embedding_cache import (
    get_cached_query_embeddings,
)
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR


def _unique_query() -> str:
    return f"hello world {uuid4().hex[:8]}"


def _lookup_count(provider: str, outcome: str) -> float:
    value = REGISTRY.get_sample_value(
        "onyx_query_embedding_cache_lookups_total",
        {"provider": provider, "outcome": outcome},
    )
    return value or 0.0


def _write_count(provider: str, outcome: str) -> float:
    value = REGISTRY.get_sample_value(
        "onyx_query_embedding_cache_writes_total",
        {"provider": provider, "outcome": outcome},
    )
    return value or 0.0


class TestCacheThenRetrieve:
    def test_round_trip_preserves_floats(self, test_embedding: list[float]) -> None:
        """
        Tests that the cache round trip preserves the floats.
        """
        # Precondition.
        query = _unique_query()
        cache_query_embeddings(
            queries=[query],
            embeddings=[test_embedding],
            search_settings_id=1,
            provider_type=None,
            ttl_seconds=60,
        )

        # Under test.
        got = get_cached_query_embeddings(
            queries=[query],
            search_settings_id=1,
            provider_type=None,
            ttl_seconds=60,
        )

        # Postcondition.
        assert got[0] is not None
        assert got[0] == test_embedding

    def test_miss_returns_none(self) -> None:
        """
        Tests that a miss returns None.
        """
        # Under test.
        got = get_cached_query_embeddings(
            queries=[_unique_query()],
            search_settings_id=1,
            provider_type=None,
            ttl_seconds=60,
        )

        # Postcondition.
        assert got == [None]


class TestPartialFill:
    def test_partial_fill_preserves_order(self) -> None:
        """
        Tests that the partial fill preserves the order of the queries.
        """
        # Precondition.
        q_hit_a = _unique_query()
        q_hit_b = _unique_query()
        q_miss = _unique_query()

        emb_a = [1.0, 2.0]
        emb_b = [3.0, 4.0]

        cache_query_embeddings(
            queries=[q_hit_a, q_hit_b],
            embeddings=[emb_a, emb_b],
            search_settings_id=42,
            provider_type=None,
            ttl_seconds=60,
        )

        # Under test.
        results = get_cached_query_embeddings(
            queries=[q_hit_a, q_miss, q_hit_b],
            search_settings_id=42,
            provider_type=None,
            ttl_seconds=60,
        )

        # Postcondition.
        assert results[0] is not None and results[0] == emb_a
        assert results[1] is None
        assert results[2] is not None and results[2] == emb_b


class TestModelIdIsolation:
    def test_different_search_settings_ids_do_not_collide(self) -> None:
        """
        Tests that different search settings IDs are isolated from each other.
        """
        # Precondition.
        query = _unique_query()
        cache_query_embeddings(
            queries=[query],
            embeddings=[[1.0, 2.0]],
            search_settings_id=100,
            provider_type=None,
            ttl_seconds=60,
        )

        # Under test.
        got = get_cached_query_embeddings(
            queries=[query],
            search_settings_id=101,  # Different search settings ID.
            provider_type=None,
            ttl_seconds=60,
        )

        # Postcondition.
        assert got == [None]


class TestTenantIsolation:
    def test_other_tenant_does_not_see_entry(self) -> None:
        """
        Tests that tenants do not see entries for other tenants.
        """
        # Precondition.
        query = _unique_query()
        cache_query_embeddings(
            queries=[query],
            embeddings=[[1.0, 2.0]],
            search_settings_id=200,
            provider_type=None,
            ttl_seconds=60,
        )

        other_tenant = f"tenant_test_other_{uuid4().hex[:8]}"
        token = CURRENT_TENANT_ID_CONTEXTVAR.set(other_tenant)
        try:
            # Under test.
            got = get_cached_query_embeddings(
                queries=[query],
                search_settings_id=200,
                provider_type=None,
                ttl_seconds=60,
            )
        finally:
            CURRENT_TENANT_ID_CONTEXTVAR.reset(token)

        # Postcondition.
        assert got == [None]


class TestTTLRefresh:
    def test_hit_refreshes_ttl(self) -> None:
        """
        Tests that a hit refreshes the TTL.
        """
        # Precondition.
        query = _unique_query()
        cache_query_embeddings(
            queries=[query],
            embeddings=[[1.0]],
            search_settings_id=300,
            provider_type=None,
            ttl_seconds=1,
        )
        backend = get_cache_backend()
        key = _build_key(query, 300)
        assert backend.ttl(key) <= 1

        # Under test.
        get_cached_query_embeddings(
            queries=[query],
            search_settings_id=300,
            provider_type=None,
            ttl_seconds=600,
        )

        # Postcondition.
        # After hit, TTL should be back near the new ttl.
        ttl_after = backend.ttl(key)
        assert 1 <= ttl_after <= 600


class TestFailOpen:
    def test_get_swallows_backend_error(self) -> None:
        """
        Tests that a get swallows a backend error.
        """
        # Precondition.
        query = _unique_query()
        # Pre-populate so we'd otherwise hit; the error must still flow through
        # as a miss.
        cache_query_embeddings(
            queries=[query],
            embeddings=[[1.0]],
            search_settings_id=400,
            provider_type=None,
            ttl_seconds=60,
        )

        with patch(
            "onyx.cache.redis_backend.RedisCacheBackend.get",
            side_effect=RedisError("boom"),
        ):
            # Under test.
            got = get_cached_query_embeddings(
                queries=[query],
                search_settings_id=400,
                provider_type=None,
                ttl_seconds=60,
            )

        # Postcondition.
        assert got == [None]

    def test_set_swallows_backend_error(self) -> None:
        """
        Tests that a set swallows a backend error.
        """
        # Precondition.
        query = _unique_query()
        with patch(
            "onyx.cache.redis_backend.RedisCacheBackend.set",
            side_effect=RedisError("boom"),
        ):
            # Under test.
            # Must not raise.
            cache_query_embeddings(
                queries=[query],
                embeddings=[[1.0]],
                search_settings_id=401,
                provider_type=None,
                ttl_seconds=60,
            )
