import struct
from unittest.mock import Mock, patch

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy.exc import OperationalError

from onyx.cache.interface import CacheBackend
from onyx.natural_language_processing.passage_embedding_cache import (
    embed_cached_passages,
)


def test_duplicates_mixed_hits_and_tenant_isolation() -> None:
    stores: dict[str | None, dict[str, bytes]] = {}

    def backend(*, tenant_id: str | None, operation_timeout_s: float) -> Mock:
        assert operation_timeout_s == 0.2
        store = stores.setdefault(tenant_id, {})
        cache = Mock(spec=CacheBackend)
        cache.get.side_effect = store.get
        cache.set.side_effect = lambda key, value, **_kwargs: store.__setitem__(
            key, value
        )
        return cache

    encode = Mock(side_effect=lambda texts: [[float(len(text)), 2.0] for text in texts])
    with patch(
        "onyx.natural_language_processing.passage_embedding_cache.get_cache_backend",
        side_effect=backend,
    ):

        def run(
            texts: list[str], tenant: str = "a", scope: str = "model"
        ) -> list[list[float]]:
            return embed_cached_passages(texts, encode, scope, 2, tenant, 60)

        assert run(["one", "one"]) == [[3.0, 2.0], [3.0, 2.0]]
        encode.assert_called_once_with(["one"])
        encode.reset_mock()
        assert run(["two!", "one", "two!"]) == [[4.0, 2.0], [3.0, 2.0], [4.0, 2.0]]
        encode.assert_called_once_with(["two!"])
        encode.reset_mock()
        run(["one"])
        encode.assert_not_called()
        run(["one"], tenant="b")
        run(["one"], scope="other-model")
        assert encode.call_count == 2


@pytest.mark.parametrize("stage", ["factory", "get", "set"])
@pytest.mark.parametrize(
    "error",
    [
        RedisConnectionError("offline"),
        OperationalError("select", {}, Exception("offline")),
    ],
)
def test_cache_outage_stops_cache_operations(stage: str, error: Exception) -> None:
    cache = Mock(spec=CacheBackend)
    cache.get.return_value = None
    encode = Mock(return_value=[[1.0], [2.0]])
    if stage != "factory":
        (cache.get if stage == "get" else cache.set).side_effect = error
    with patch(
        "onyx.natural_language_processing.passage_embedding_cache.get_cache_backend",
        return_value=cache,
        side_effect=error if stage == "factory" else None,
    ):
        assert embed_cached_passages(["a", "b", "a"], encode, "scope", 1, None, 60) == [
            [1.0],
            [2.0],
            [1.0],
        ]
    encode.assert_called_once_with(["a", "b"])
    if stage == "get":
        assert cache.get.call_count == 1
        cache.set.assert_not_called()
    if stage == "set":
        assert cache.set.call_count == 1


@pytest.mark.parametrize(
    "raw", [b"", b"bad", struct.pack("<f", 1), struct.pack("<2f", float("nan"), 1)]
)
def test_corrupt_cache_entry_is_replaced(raw: bytes) -> None:
    cache = Mock(spec=CacheBackend)
    cache.get.return_value = raw
    encode = Mock(return_value=[[1.0, 2.0]])
    with patch(
        "onyx.natural_language_processing.passage_embedding_cache.get_cache_backend",
        return_value=cache,
    ):
        assert embed_cached_passages(["a"], encode, "scope", 2, "tenant", 60) == [
            [1.0, 2.0]
        ]
    assert cache.set.call_args.kwargs == {"ex": 60}


@pytest.mark.parametrize("vectors", [[], [[1.0]], [[float("inf"), 2.0]]])
def test_invalid_provider_response_is_not_cached(vectors: list[list[float]]) -> None:
    cache = Mock(spec=CacheBackend)
    cache.get.return_value = None
    with patch(
        "onyx.natural_language_processing.passage_embedding_cache.get_cache_backend",
        return_value=cache,
    ):
        with pytest.raises(ValueError):
            embed_cached_passages(
                ["a"], Mock(return_value=vectors), "scope", 2, None, 60
            )
    cache.set.assert_not_called()


def test_empty_batch_avoids_cache_and_provider() -> None:
    encode = Mock()
    with patch(
        "onyx.natural_language_processing.passage_embedding_cache.get_cache_backend"
    ) as factory:
        assert embed_cached_passages([], encode, "scope", 2, None, 60) == []
    factory.assert_not_called()
    encode.assert_not_called()
