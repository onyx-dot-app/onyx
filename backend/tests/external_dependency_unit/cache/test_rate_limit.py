from uuid import uuid4

import pytest

from onyx.cache import rate_limit
from onyx.cache.interface import CacheBackend
from onyx.cache.rate_limit import within_rate_limit


def test_counts_each_bucket_within_its_window(
    cache: CacheBackend, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(rate_limit, "get_shared_cache_backend", lambda: cache)
    monkeypatch.setattr(rate_limit.time, "time", lambda: 1000.0)
    bucket = f"test-rate-{uuid4()}"
    other = f"test-rate-{uuid4()}"
    assert within_rate_limit(bucket, limit=2, window_seconds=600)
    assert within_rate_limit(bucket, limit=2, window_seconds=600)
    assert not within_rate_limit(bucket, limit=2, window_seconds=600)
    assert within_rate_limit(other, limit=2, window_seconds=600)
    monkeypatch.setattr(rate_limit.time, "time", lambda: 1600.0)
    assert within_rate_limit(bucket, limit=2, window_seconds=600)
