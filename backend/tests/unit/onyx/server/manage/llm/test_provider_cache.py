import pytest
from redis.exceptions import RedisError

from onyx.server.manage.llm import provider_cache
from onyx.server.manage.llm.models import DefaultModel
from onyx.server.manage.llm.models import LLMProviderDescriptor
from onyx.server.manage.llm.models import LLMProviderResponse


class _FakeCache:
    def __init__(self) -> None:
        self._vals: dict[str, bytes] = {}

    def get(self, key: str) -> bytes | None:
        return self._vals.get(key)

    def set(
        self,
        key: str,
        value: str | bytes,
        ex: int | None = None,  # noqa: ARG002
    ) -> None:
        self._vals[key] = value.encode("utf-8") if isinstance(value, str) else value


class _BrokenCache:
    def get(self, key: str) -> bytes | None:  # noqa: ARG002
        raise RedisError("redis down")

    def set(
        self,
        key: str,  # noqa: ARG002
        value: str | bytes,  # noqa: ARG002
        ex: int | None = None,  # noqa: ARG002
    ) -> None:
        raise RedisError("redis down")


def _make_response() -> LLMProviderResponse[LLMProviderDescriptor]:
    descriptor = LLMProviderDescriptor(
        id=1,
        name="openai",
        provider="openai",
        provider_display_name="OpenAI",
        model_configurations=[],
    )
    return LLMProviderResponse[LLMProviderDescriptor].from_models(
        providers=[descriptor],
        default_text=DefaultModel(provider_id=1, model_name="gpt-5-mini"),
        default_vision=None,
    )


@pytest.fixture
def fake_cache(monkeypatch: pytest.MonkeyPatch) -> _FakeCache:
    cache = _FakeCache()
    monkeypatch.setattr(provider_cache, "get_cache_backend", lambda: cache)
    return cache


@pytest.mark.usefixtures("fake_cache")
def test_miss_returns_none() -> None:
    assert (
        provider_cache.get_cached_provider_listing(
            persona_id=None, is_admin=False, user_group_ids=set()
        )
        is None
    )


@pytest.mark.usefixtures("fake_cache")
def test_round_trip() -> None:
    response = _make_response()
    provider_cache.cache_provider_listing(
        persona_id=None, is_admin=False, user_group_ids={3, 1}, response=response
    )
    cached = provider_cache.get_cached_provider_listing(
        persona_id=None, is_admin=False, user_group_ids={1, 3}
    )
    assert cached == response


@pytest.mark.usefixtures("fake_cache")
def test_key_isolation_across_users_and_personas() -> None:
    response = _make_response()
    provider_cache.cache_provider_listing(
        persona_id=None, is_admin=False, user_group_ids={1}, response=response
    )

    assert (
        provider_cache.get_cached_provider_listing(
            persona_id=None, is_admin=False, user_group_ids={2}
        )
        is None
    )
    assert (
        provider_cache.get_cached_provider_listing(
            persona_id=None, is_admin=True, user_group_ids={1}
        )
        is None
    )
    assert (
        provider_cache.get_cached_provider_listing(
            persona_id=7, is_admin=False, user_group_ids={1}
        )
        is None
    )


@pytest.mark.usefixtures("fake_cache")
def test_invalidation_drops_all_entries() -> None:
    response = _make_response()
    provider_cache.cache_provider_listing(
        persona_id=None, is_admin=False, user_group_ids=set(), response=response
    )
    provider_cache.cache_provider_listing(
        persona_id=7, is_admin=True, user_group_ids=set(), response=response
    )

    provider_cache.invalidate_provider_listing_cache()

    assert (
        provider_cache.get_cached_provider_listing(
            persona_id=None, is_admin=False, user_group_ids=set()
        )
        is None
    )
    assert (
        provider_cache.get_cached_provider_listing(
            persona_id=7, is_admin=True, user_group_ids=set()
        )
        is None
    )


def test_invalid_cached_payload_is_discarded(fake_cache: _FakeCache) -> None:
    provider_cache.cache_provider_listing(
        persona_id=None, is_admin=False, user_group_ids=set(), response=_make_response()
    )
    for key in list(fake_cache._vals):
        if key.startswith("llm_provider_listing:entry"):
            fake_cache._vals[key] = b'{"providers": "not-a-list"}'

    assert (
        provider_cache.get_cached_provider_listing(
            persona_id=None, is_admin=False, user_group_ids=set()
        )
        is None
    )


def test_cache_failures_are_non_fatal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(provider_cache, "get_cache_backend", lambda: _BrokenCache())

    assert (
        provider_cache.get_cached_provider_listing(
            persona_id=None, is_admin=False, user_group_ids=set()
        )
        is None
    )
    provider_cache.cache_provider_listing(
        persona_id=None, is_admin=False, user_group_ids=set(), response=_make_response()
    )
    provider_cache.invalidate_provider_listing_cache()
