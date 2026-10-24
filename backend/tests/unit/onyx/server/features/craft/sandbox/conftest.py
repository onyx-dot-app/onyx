from unittest.mock import MagicMock

import pytest

from onyx.server.features.build.sandbox import locks


@pytest.fixture(autouse=True)
def runtime_lock_cache(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    cache = MagicMock()
    monkeypatch.setattr(locks, "get_cache_backend", lambda **_kwargs: cache)
    return cache
