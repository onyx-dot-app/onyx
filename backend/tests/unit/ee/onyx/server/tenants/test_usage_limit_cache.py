"""Unit tests for the cache of each playground tenant's trial start and
limit overrides."""

from collections.abc import Generator
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from redis.exceptions import RedisError

from ee.onyx.server.tenants import usage_limit_cache as ulc
from ee.onyx.server.tenants.models import TenantUsageLimitState
from onyx.db.usage import UsageType

_TENANT = "tenant_abc"
_START = datetime(2026, 11, 25, 14, 7, tzinfo=timezone.utc)
_STATE = TenantUsageLimitState(trial_start=_START, limits={"llm_cost_cents": 10000})


def _fake_cache(
    get_return: bytes | None = None,
    raise_on_get: Exception | None = None,
    raise_on_set: Exception | None = None,
) -> MagicMock:
    cache = MagicMock()
    cache.get = MagicMock(side_effect=raise_on_get, return_value=get_return)
    cache.set = MagicMock(side_effect=raise_on_set, return_value=True)
    return cache


@pytest.fixture(autouse=True)
def _empty_trial_start_memory() -> Generator[None, None, None]:
    ulc._trial_starts.clear()
    yield
    ulc._trial_starts.clear()


class TestCachedState:
    def test_hit_does_not_read_the_control_plane(self) -> None:
        cache = _fake_cache(get_return=_STATE.model_dump_json().encode())
        with (
            patch.object(ulc, "get_shared_cache_backend", return_value=cache),
            patch.object(ulc, "fetch_tenant_usage_limit_state") as fetch,
        ):
            assert ulc.cached_tenant_usage_limit_state(_TENANT) == _STATE
        fetch.assert_not_called()

    def test_miss_reads_the_control_plane_and_caches_it(self) -> None:
        cache = _fake_cache(get_return=None)
        with (
            patch.object(ulc, "get_shared_cache_backend", return_value=cache),
            patch.object(ulc, "fetch_tenant_usage_limit_state", return_value=_STATE),
            patch.object(ulc, "BILLING_CACHE_TTL_SECONDS", 3600),
        ):
            assert ulc.cached_tenant_usage_limit_state(_TENANT) == _STATE
        cache.set.assert_called_once_with(
            "usage_limits:tenant_abc", _STATE.model_dump_json(), ex=3600
        )

    def test_failed_read_caches_an_empty_value_briefly(self) -> None:
        cache = _fake_cache(get_return=None)
        with (
            patch.object(ulc, "get_shared_cache_backend", return_value=cache),
            patch.object(
                ulc,
                "fetch_tenant_usage_limit_state",
                side_effect=RuntimeError("404"),
            ),
        ):
            state = ulc.cached_tenant_usage_limit_state(_TENANT)
        assert state == TenantUsageLimitState()
        assert cache.set.call_args.kwargs["ex"] == ulc._FETCH_FAILED_TTL_SECONDS

    def test_cache_error_reads_the_control_plane_without_caching(self) -> None:
        cache = _fake_cache(raise_on_get=RedisError("down"))
        with (
            patch.object(ulc, "get_shared_cache_backend", return_value=cache),
            patch.object(ulc, "fetch_tenant_usage_limit_state", return_value=_STATE),
        ):
            assert ulc.cached_tenant_usage_limit_state(_TENANT) == _STATE
        cache.set.assert_not_called()

    def test_unreadable_entry_is_refetched(self) -> None:
        cache = _fake_cache(get_return=b"not json")
        with (
            patch.object(ulc, "get_shared_cache_backend", return_value=cache),
            patch.object(
                ulc, "fetch_tenant_usage_limit_state", return_value=_STATE
            ) as fetch,
        ):
            assert ulc.cached_tenant_usage_limit_state(_TENANT) == _STATE
        fetch.assert_called_once_with(_TENANT)


class TestTrialStart:
    def test_kept_in_memory_after_the_first_read(self) -> None:
        with patch.object(
            ulc, "cached_tenant_usage_limit_state", return_value=_STATE
        ) as read:
            assert ulc.cached_tenant_trial_start(_TENANT) == _START
            assert ulc.cached_tenant_trial_start(_TENANT) == _START
        read.assert_called_once_with(_TENANT)

    def test_missing_start_is_not_kept(self) -> None:
        with patch.object(
            ulc,
            "cached_tenant_usage_limit_state",
            return_value=TenantUsageLimitState(),
        ) as read:
            assert ulc.cached_tenant_trial_start(_TENANT) is None
            assert ulc.cached_tenant_trial_start(_TENANT) is None
        assert read.call_count == 2


class TestOverride:
    def test_reads_the_override_for_one_usage_type(self) -> None:
        with patch.object(ulc, "cached_tenant_usage_limit_state", return_value=_STATE):
            assert (
                ulc.cached_tenant_limit_override(_TENANT, UsageType.LLM_COST) == 10000
            )
            assert (
                ulc.cached_tenant_limit_override(_TENANT, UsageType.CHUNKS_INDEXED)
                is None
            )


class TestStateModel:
    def test_overrides_are_keyed_by_usage_type(self) -> None:
        state = TenantUsageLimitState.model_validate(
            {"limits": {"llm_cost_cents": 10000}}
        )
        assert state.limits == {UsageType.LLM_COST: 10000}

    def test_unknown_usage_types_are_dropped_and_known_ones_kept(self) -> None:
        state = TenantUsageLimitState.model_validate(
            {"limits": {"llm_cost_cents": 10000, "messages_from_the_future": 5}}
        )
        assert state.limits == {UsageType.LLM_COST: 10000}

    def test_round_trips_through_the_cache_format(self) -> None:
        assert (
            TenantUsageLimitState.model_validate_json(_STATE.model_dump_json())
            == _STATE
        )


class TestStore:
    def test_writes_the_pushed_value_and_remembers_the_trial_start(self) -> None:
        cache = _fake_cache()
        with patch.object(ulc, "get_shared_cache_backend", return_value=cache):
            assert ulc.store_tenant_usage_limit_state(_TENANT, _STATE) is True
        cache.set.assert_called_once()
        assert ulc._trial_starts[_TENANT] == _START

    def test_reports_a_failed_write(self) -> None:
        cache = _fake_cache(raise_on_set=RedisError("down"))
        with patch.object(ulc, "get_shared_cache_backend", return_value=cache):
            assert ulc.store_tenant_usage_limit_state(_TENANT, _STATE) is False

    def test_enum_keys_are_kept(self) -> None:
        state = TenantUsageLimitState(limits={UsageType.LLM_COST: 10000})
        assert state.limits == {UsageType.LLM_COST: 10000}
